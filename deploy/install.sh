#!/usr/bin/env bash
# PiFrame installer — idempotent, safe to re-run after updates.
# Run as root from any directory: sudo bash deploy/install.sh
set -euo pipefail

# ── Colour helpers ─────────────────────────────────────────────────────────
_grn='\033[0;32m'; _yel='\033[1;33m'; _red='\033[0;31m'; _nc='\033[0m'
info() { echo -e "${_grn}[piframe]${_nc} $*"; }
warn() { echo -e "${_yel}[piframe WARN]${_nc} $*" >&2; }
die()  { echo -e "${_red}[piframe ERROR]${_nc} $*" >&2; exit 1; }

# ── Sanity checks ──────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Run as root:  sudo bash deploy/install.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
INSTALL_DIR=/opt/piframe
SERVICE_USER=dietpi

id -u "$SERVICE_USER" &>/dev/null \
  || die "User '$SERVICE_USER' not found.  Create it or set SERVICE_USER at the top of this script."

# ── 1. System packages ─────────────────────────────────────────────────────
info "Updating package lists..."
apt-get update -qq

info "Installing system packages..."
apt-get install -y --no-install-recommends \
    curl \
    rsync \
    python3-pip

# Kiosk browser: Python GTK+WebKit2 under a minimal X/fbdev stack.
# surf triggers "Invalid value for lock" on BCM2835/ARMv6 due to a subprocess
# IPC FD setup failure.  The GTK+WebKit2 Python launcher (deploy/kiosk-browser.py)
# uses the same WebKit engine but avoids the surf-specific lock initialisation.
# Debian's cog package on ARMv6 ships only the fdo (Wayland) platform plugin —
# the DRM plugin required by "cog -P drm" is absent, so cog is not viable here.
apt-get install -y --no-install-recommends \
    xserver-xorg \
    xserver-xorg-video-fbdev \
    xserver-xorg-legacy \
    xinit \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-3.0 \
    gir1.2-webkit2-4.1

# ── 2. Python packages (piwheels pre-built wheels for ARMv6) ───────────────
info "Installing Python packages..."
# --break-system-packages is required on Debian Bookworm+ to install outside
# a venv.  Ignored on older Debian/pip versions that don't know the flag.
pip3 install \
    --extra-index-url https://www.piwheels.org/simple \
    --break-system-packages \
    --quiet \
    -r "$PROJECT_DIR/requirements.txt"

# ── 3. Deploy project files ────────────────────────────────────────────────
info "Syncing project files → $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
rsync -a --delete \
    --exclude='.git/' \
    --exclude='data/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.venv/' \
    --exclude='.devcontainer/' \
    "$PROJECT_DIR/" "$INSTALL_DIR/"

# Ensure data directories exist (app creates them too, but be explicit).
mkdir -p \
    "$INSTALL_DIR/data/photos/originals" \
    "$INSTALL_DIR/data/photos/display" \
    "$INSTALL_DIR/data/cache"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "$INSTALL_DIR/data"

# ── 4. Group memberships for X / framebuffer access ───────────────────────
info "Adding $SERVICE_USER to video group (framebuffer / X access)..."
usermod -aG video "$SERVICE_USER" \
    || warn "usermod failed — add $SERVICE_USER to 'video' manually."

# ── 4b. Allow the dietpi service user to start an X server ────────────────
# xserver-xorg-legacy provides a setuid Xorg wrapper; Xwrapper.config lets
# non-root users invoke it (required when starting X from a systemd service
# rather than a PAM login session).
info "Configuring X server permissions..."
mkdir -p /etc/X11
cat > /etc/X11/Xwrapper.config << 'EOF'
allowed_users=anybody
needs_root_rights=auto
EOF

# Keep the display always on: disable X screensaver blanking + DPMS.
# (Without this, the fbdev X server blanks the screen after ~10 min idle.)
info "Disabling screen blanking / DPMS..."
mkdir -p /etc/X11/xorg.conf.d
cp "$INSTALL_DIR/deploy/10-piframe-noblank.conf" /etc/X11/xorg.conf.d/10-piframe-noblank.conf

# ── 5. Systemd units ───────────────────────────────────────────────────────
info "Installing systemd units..."
cp "$INSTALL_DIR/deploy/piframe.service"       /etc/systemd/system/piframe.service
cp "$INSTALL_DIR/deploy/piframe-kiosk.service" /etc/systemd/system/piframe-kiosk.service

systemctl daemon-reload
systemctl enable piframe.service piframe-kiosk.service

# ── 6. Start / restart services ────────────────────────────────────────────
info "Starting piframe.service..."
systemctl restart piframe.service

# Brief pause so the backend is likely ready before the kiosk polls it.
sleep 3

info "Starting piframe-kiosk.service..."
systemctl restart piframe-kiosk.service

# ── 7. Summary ─────────────────────────────────────────────────────────────
PI_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "unknown")

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "PiFrame installed successfully."
echo ""
echo "  Slideshow : http://${PI_IP}:5000/"
echo "  Upload    : http://${PI_IP}:5000/upload"
echo ""
echo "  Service logs:"
echo "    journalctl -u piframe        -f"
echo "    journalctl -u piframe-kiosk  -f"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
