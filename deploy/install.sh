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

# Pillow (installed from piwheels below) links against Debian's system imaging
# libraries rather than bundling them.  Without these, "from PIL import Image"
# raises at import time — e.g. "libopenjp2.so.7: cannot open shared object
# file" — and piframe.service crash-loops before it ever binds port 5000,
# which in turn starves piframe-kiosk's readiness poll.
info "Installing Pillow runtime libraries..."
# These package names drift between Debian releases (libtiff5/libtiff6,
# libwebp6/libwebp7), so ask apt which ones this release actually ships and
# install the survivors in ONE transaction.  apt-cache is a local lookup and
# costs milliseconds; the previous one-apt-get-per-package loop cost about a
# minute each on a Pi Zero W, which dominated the whole install.
_pillow_libs="libopenjp2-7 libtiff6 libtiff5 libjpeg62-turbo libwebp7 libwebp6
              libwebpdemux2 libwebpmux3 liblcms2-2 libfreetype6 zlib1g"
apt-cache show libopenjp2-7 &>/dev/null \
    || die "libopenjp2-7 unavailable in apt — Pillow cannot import without it"
_available=""
for _lib in $_pillow_libs; do
    apt-cache show "$_lib" &>/dev/null && _available="$_available $_lib"
done
info "  resolved:$_available"
apt-get install -y --no-install-recommends $_available

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

# Fail loudly here rather than letting the backend crash-loop after install.
# A Pillow that imports cleanly is the single best signal that the imaging
# libraries above are complete for this Debian release.
info "Verifying Python imports..."
/usr/bin/python3 -c 'import flask, waitress, requests; from PIL import Image' \
  || die "Python dependency check failed (see the ImportError above).
       A missing lib*.so usually means an imaging package is absent for this
       Debian release — install it and re-run:  sudo bash deploy/install.sh"

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

# ── 5b. Setup hotspot (AP fallback) ───────────────────────────────────────
info "Installing hotspot packages..."
apt-get install -y --no-install-recommends hostapd dnsmasq iw

# hostapd and dnsmasq are driven exclusively by piframe-netctl, never by their
# own units. Masking the stock ones stops apt's copies from claiming wlan0 at
# boot and stranding the frame as an access point with no uplink.
systemctl disable --now hostapd dnsmasq &>/dev/null || true
systemctl mask hostapd dnsmasq &>/dev/null || true

mkdir -p /etc/piframe

# piframe-netctl runs as root via sudo. If $SERVICE_USER could write it, the
# sudoers rule below would be a root escalation — so force ownership here
# rather than trusting whatever rsync happened to copy.
chown root:root "$INSTALL_DIR/deploy/piframe-netctl"
chmod 0755 "$INSTALL_DIR/deploy/piframe-netctl"

# Validate in a temp file first: a malformed drop-in in /etc/sudoers.d breaks
# sudo system-wide, including the ability to fix it.
info "Installing sudoers rule for $SERVICE_USER..."
command -v visudo >/dev/null || die "visudo not found — cannot safely install sudoers rule"
_sudo_tmp="$(mktemp)"
echo "$SERVICE_USER ALL=(root) NOPASSWD: $INSTALL_DIR/deploy/piframe-netctl" > "$_sudo_tmp"
chmod 0440 "$_sudo_tmp"
visudo -cf "$_sudo_tmp" >/dev/null || { rm -f "$_sudo_tmp"; die "sudoers rule failed validation"; }
mv "$_sudo_tmp" /etc/sudoers.d/piframe-netctl
chmod 0440 /etc/sudoers.d/piframe-netctl

cp "$INSTALL_DIR/deploy/piframe-hostapd.service"  /etc/systemd/system/piframe-hostapd.service
cp "$INSTALL_DIR/deploy/piframe-dnsmasq.service"  /etc/systemd/system/piframe-dnsmasq.service
cp "$INSTALL_DIR/deploy/piframe-netwatch.service" /etc/systemd/system/piframe-netwatch.service
systemctl daemon-reload

# NOT enabled here on purpose. piframe-netwatch can switch wlan0 into AP mode,
# which drops SSH — so it stays off until `piframe-netctl status` has been
# confirmed correct on this hardware. See README, "Setup hotspot".
warn "piframe-netwatch installed but NOT enabled — verify status first, then:"
warn "  systemctl enable --now piframe-netwatch"

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
