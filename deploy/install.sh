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
    libopenjp2-7 \
    python3-pip

# Cog (WPE WebKit kiosk browser for DRM/KMS — primary Path A).
# On some DietPi/Debian versions the package may be named differently; we
# try the canonical name and fall back gracefully.
if apt-get install -y --no-install-recommends cog 2>/dev/null; then
    KIOSK_READY=1
else
    warn "'cog' not found in apt.  Installing surf + minimal X as fallback."
    warn "See README § Troubleshooting for the surf kiosk service variant."
    apt-get install -y --no-install-recommends \
        surf xserver-xorg-core xinit x11-xserver-utils
    KIOSK_READY=0
fi

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

# ── 4. DRM group memberships ───────────────────────────────────────────────
info "Granting $SERVICE_USER DRM/KMS access (video + render groups)..."
usermod -aG video,render "$SERVICE_USER" \
    || warn "usermod failed — add $SERVICE_USER to 'video' and 'render' manually."

# ── 5. Systemd units ───────────────────────────────────────────────────────
info "Installing systemd units..."
cp "$INSTALL_DIR/deploy/piframe.service"       /etc/systemd/system/piframe.service
cp "$INSTALL_DIR/deploy/piframe-kiosk.service" /etc/systemd/system/piframe-kiosk.service

# If cog is absent, patch the kiosk unit to use surf via startx.
if [[ $KIOSK_READY -eq 0 ]]; then
    warn "Patching piframe-kiosk.service to use surf (no cog available)."
    sed -i \
        's|ExecStart=/usr/bin/cog.*|ExecStart=/usr/bin/xinit /usr/bin/surf -F http://127.0.0.1:5000/ -- :0 vt1|' \
        /etc/systemd/system/piframe-kiosk.service
fi

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
if [[ $KIOSK_READY -eq 0 ]]; then
    warn "cog was unavailable; surf fallback applied.  See README § Troubleshooting."
fi
