# PiFrame

A self-contained photo slideshow and weather dashboard for the **Raspberry Pi Zero W (v1)**.
On boot it opens a full-screen kiosk showing your photos with crossfade transitions and a live
weather overlay.  Anyone on your home network can add or remove photos from a phone or laptop —
no app required.

---

## Contents

1. [What it does](#what-it-does)
2. [Hardware requirements](#hardware-requirements)
3. [Getting started](#getting-started)
   - [1 — Flash DietPi](#1--flash-dietpi)
   - [2 — Headless WiFi and first-boot config](#2--headless-wifi-and-first-boot-config)
   - [3 — Set GPU memory](#3--set-gpu-memory)
   - [4 — First boot](#4--first-boot)
   - [5 — Copy PiFrame to the Pi](#5--copy-piframe-to-the-pi)
   - [6 — Run the installer](#6--run-the-installer)
4. [Using PiFrame](#using-piframe)
5. [Configuration](#configuration)
6. [Path B — Pi Zero 2 W + Chromium kiosk](#path-b--pi-zero-2-w--chromium-kiosk)
7. [Security](#security)
8. [Troubleshooting](#troubleshooting)

---

## What it does

| Feature | Detail |
|---|---|
| **Slideshow** | Full-screen, crossfade transitions, photos shuffled on each cycle |
| **Weather overlay** | Current conditions, AQI, 12-hour rain probability strip, 3-day forecast — powered by [Open-Meteo](https://open-meteo.com) (free, no API key) |
| **Upload page** | Drag-and-drop or file-picker on any phone/laptop; per-file progress bars; sequential queue (kind to the Zero W's single core) |
| **Auto-ingest** | Uploaded originals are scaled to display resolution in the background; photos appear in rotation once ready — no restart needed |
| **Dedup** | Files are identified by SHA-256 content hash; re-uploading the same image is a no-op |
| **Offline-first** | The kiosk page loads zero external resources; weather panel shows cached/stale data if WiFi drops |

---

## Hardware requirements

**Primary target — Pi Zero W v1**

| | |
|---|---|
| SoC | BCM2835, single-core ARMv6 @ 1 GHz |
| RAM | 512 MB (shared with GPU) |
| WiFi | 2.4 GHz 802.11n |
| Storage | microSD (8 GB minimum; 16 GB recommended) |

> **ARMv6 matters.**  Modern Chromium does not ship for ARMv6.  PiFrame uses
> **Cog** (WPE WebKit kiosk browser) which renders directly to the display
> via DRM/KMS — no X server, no desktop, saving ~100 MB of RAM.
>
> If your hardware is actually a **Pi Zero 2 W** (ARMv8, quad-core), see
> [Path B](#path-b--pi-zero-2-w--chromium-kiosk) for the native Chromium kiosk variant.

---

## Getting started

### 1 — Flash DietPi

1. Download the **ARMv6** DietPi image from <https://dietpi.com/#download>:
   select *Raspberry Pi* → **"Raspberry Pi 1 / Zero / Zero W"** (labelled ARMv6).

2. Flash to a microSD card with [Balena Etcher](https://etcher.balena.io/) or `dd`:

   ```bash
   # Linux/macOS (replace /dev/sdX with your card — verify carefully)
   xz -dc DietPi_RPi-ARMv6-Bookworm.img.xz | sudo dd of=/dev/sdX bs=4M conv=fsync status=progress
   ```

3. **Do not eject yet** — edit three files on the `boot` partition before
   first boot.

---

### 2 — Headless WiFi and first-boot config

Mount the `boot` partition (it appears as a small FAT volume, readable on any OS).

#### `dietpi.txt` — automate first-boot setup

Open `dietpi.txt` and set (or add) these lines.  Everything else can stay at
its default:

```ini
# ── Locale / time ──────────────────────────────────────────────────────────
AUTO_SETUP_LOCALE=en_US.UTF-8
AUTO_SETUP_KEYBOARD_LAYOUT=us
AUTO_SETUP_TIMEZONE=America/New_York      # change to your timezone

# ── Network ────────────────────────────────────────────────────────────────
AUTO_SETUP_NET_WIFI_ENABLED=1
AUTO_SETUP_NET_WIFI_COUNTRY_CODE=US       # 2-letter country code for WiFi regs

# ── Unattended first boot ──────────────────────────────────────────────────
AUTO_SETUP_HEADLESS=1
AUTO_SETUP_AUTOMATED=1
AUTO_SETUP_GLOBAL_PASSWORD=changeme       # SSH and root password — change this!

# ── Skip the interactive software survey on first run ─────────────────────
AUTO_SETUP_INSTALL_SOFTWARE_ID=0
```

#### `dietpi-wifi.txt` — WiFi credentials

```ini
aSSID[0]=YourNetworkName
aWIFI_KEY[0]=YourWiFiPassword
aWIFI_KEYMGMT[0]=WPA-PSK
```

---

### 3 — Set GPU memory

The X framebuffer driver needs the GPU memory split set to at least 64 MB.
Open **`/boot/firmware/config.txt`** and add or replace the `gpu_mem` line:

```ini
gpu_mem=64
```

128 MB gives slightly smoother rendering if you can spare the RAM.  Do not go
above 128 on a 512 MB Zero W — the OS needs the rest.

---

### 4 — First boot

Insert the microSD, connect power.  DietPi's automated setup runs once and
takes **5–15 minutes** (package installs, locale generation, etc.).  The Pi
will reboot when finished.

Find the Pi's IP address from your router's DHCP lease table, or use:

```bash
# From another machine on the same network
ping dietpi.local
# or
nmap -sn 192.168.1.0/24 | grep -i dietpi
```

SSH in to confirm it's ready:

```bash
ssh dietpi@<pi-ip>     # password: whatever you set in AUTO_SETUP_GLOBAL_PASSWORD
```

---

### 5 — Copy PiFrame to the Pi

Choose whichever method suits your setup.

**Option A — Git clone on the Pi** (requires internet on the Pi):

```bash
ssh dietpi@<pi-ip>
git clone https://github.com/yourname/piframe.git ~/piframe
```

**Option B — Copy from your machine:**

```bash
scp -r /path/to/piframe dietpi@<pi-ip>:~/piframe
```

**Option C — USB drive:**
Copy the folder to a FAT/exFAT USB drive, insert it in the Pi (via OTG
adapter), and `cp -r /media/usbdrive/piframe ~/piframe`.

---

### 6 — Run the installer

```bash
ssh dietpi@<pi-ip>
cd ~/piframe
sudo bash deploy/install.sh
```

The script is **idempotent** — safe to re-run after pulling updates:

```bash
git pull && sudo bash deploy/install.sh
```

What it does:

1. `apt install cog python3-pip libopenjp2-7 rsync curl`
2. `pip3 install` from [piwheels](https://www.piwheels.org/) (pre-built ARMv6 wheels)
3. `rsync` project files to `/opt/piframe/` (preserves `data/` across updates)
4. Adds `dietpi` to the `video` and `render` groups (DRM access)
5. Installs and enables `piframe.service` and `piframe-kiosk.service`
6. Starts both services and prints the upload URL

After install, the slideshow opens on the display automatically on every boot.

---

## Using PiFrame

### Uploading photos

From any phone or laptop on the same network, open:

```
http://<pi-ip>:5000/upload
```

- Drag files onto the drop zone or tap **Choose files**.
- Progress bars show upload status per file.
- Photos are queued for scaling in the background; they appear in the
  slideshow once the display copy is ready (typically 30–90 s on a Zero W).
- Re-uploading an identical file is silently ignored (content-hash dedup).

### Managing the slideshow

- **Delete a photo** — tap the ✕ button on any thumbnail in the upload page.
- **Add photos in bulk** — select multiple files at once; they upload
  sequentially (the Zero W's single core can only scale one at a time).

### Checking service status

```bash
systemctl status piframe
systemctl status piframe-kiosk
journalctl -u piframe -f          # live backend logs
journalctl -u piframe-kiosk -f    # live kiosk logs
```

---

## Configuration

All tunables live in `config.py` and can be overridden with environment
variables (set them in the `[Service]` section of `piframe.service`):

| Variable | Default | Description |
|---|---|---|
| `PIFRAME_PORT` | `5000` | HTTP port |
| `PIFRAME_PHOTO_DIR` | `data/photos` | Root for originals + display cache |
| `PIFRAME_CACHE_DIR` | `data/cache` | Weather and registry JSON |
| `PIFRAME_DISPLAY_W` | `1920` | Max display copy width (px) |
| `PIFRAME_DISPLAY_H` | `1080` | Max display copy height (px) |
| `PIFRAME_SLIDE_SECONDS` | `10` | Seconds per photo |
| `PIFRAME_FADE_MS` | `1500` | Crossfade duration (ms) |
| `PIFRAME_UNITS` | `celsius` | `celsius` or `fahrenheit` |
| `PIFRAME_FALLBACK_LAT` | `0.0` | Latitude if geolocation fails |
| `PIFRAME_FALLBACK_LON` | `0.0` | Longitude if geolocation fails |

Example — change slide interval and units:

```ini
# /etc/systemd/system/piframe.service  [Service] section
Environment=PIFRAME_SLIDE_SECONDS=15
Environment=PIFRAME_UNITS=fahrenheit
```

After editing: `sudo systemctl daemon-reload && sudo systemctl restart piframe`.

---

## Path B — Pi Zero 2 W + Chromium kiosk

> **Hardware swap only — zero app-code changes required.**

The **Pi Zero 2 W** uses an ARMv8 quad-core Cortex-A53 with the same form
factor and pinout as the Zero W v1.  Chromium is available for ARMv8, and
DietPi can launch it automatically as a kiosk without Cog.

### DietPi automated setup

Add to `dietpi.txt` before first boot:

```ini
# Install Chromium (software ID 113)
AUTO_SETUP_INSTALL_SOFTWARE_ID=113

# Launch Chromium kiosk on boot (autostart index 11)
AUTO_SETUP_AUTOSTART_TARGET_INDEX=11

# The URL Chromium will open
SOFTWARE_CHROMIUM_AUTOSTART_URL=http://127.0.0.1:5000/
```

Use the **Pi Zero 2 W** DietPi image (ARMv8 / 64-bit) from
<https://dietpi.com/#download> — select *Raspberry Pi* → **"Raspberry Pi 2/3/4/Zero 2 W"**.

### Services

Only `piframe.service` is needed — DietPi manages the Chromium autostart itself.
Run the installer as usual; the `piframe-kiosk.service` install step is harmless
(it will simply not be reached before DietPi's own kiosk starts).

Alternatively, skip `piframe-kiosk.service` entirely:

```bash
sudo bash deploy/install.sh
sudo systemctl disable piframe-kiosk.service
```

### `gpu_mem`

Chromium benefits from more GPU memory than Cog.  Set `gpu_mem=128` in
`/boot/firmware/config.txt` for smooth rendering on the Zero 2 W (it has the same 512 MB RAM
but the quad-core handles the extra workload).

---

## Security

The upload page has **no authentication**.  This is intentional — PiFrame is
designed for a trusted home LAN where any device on the network is welcome to
add photos.

**Do not expose port 5000 to the internet** (don't port-forward it on your
router).  If you need remote access, tunnel via SSH (`ssh -L 5000:localhost:5000
dietpi@<pi-ip>`) or put Nginx + HTTP basic auth in front.

---

## Troubleshooting

### `cog` not found after `apt install cog`

On some DietPi/Debian versions the package may not be in the default sources.
Check: `apt-cache search webkit | grep -i kiosk`.

**Surf fallback (Path A alternative):**
The installer automatically falls back to `surf` (webkit2gtk) on a minimal X
stack if `cog` is unavailable.  It patches `piframe-kiosk.service` to call
`xinit surf -F http://127.0.0.1:5000/ -- :0 vt1`.  Additional packages
installed: `surf xserver-xorg-core xinit x11-xserver-utils`.

You can also do this manually:
```bash
sudo apt install surf xserver-xorg-core xinit
# Then edit /etc/systemd/system/piframe-kiosk.service:
#   ExecStart=/usr/bin/xinit /usr/bin/surf -F http://127.0.0.1:5000/ -- :0 vt1
sudo systemctl daemon-reload && sudo systemctl restart piframe-kiosk
```

### Blank screen / cog exits immediately

1. Check groups: `groups dietpi` must include `video` and `render`.
   If not: `sudo usermod -aG video,render dietpi` then **reboot** (group
   changes take effect on next login).
2. Check DRM device exists: `ls /dev/dri/`.
3. Check `gpu_mem` in `/boot/firmware/config.txt` is ≥ 64.
4. Read cog's output: `journalctl -u piframe-kiosk -b`.

### Weather panel shows "⚠ Stale"

The Pi cannot reach the Open-Meteo API.  Check WiFi: `ping 8.8.8.8`.
The panel always shows the last successful fetch — it never goes blank.

### Photos not appearing after upload

The ingest worker scales one photo at a time on the single ARMv6 core.
A 10 MB photo takes 30–90 s.  The slideshow polls the manifest every 60 s,
so expect up to ~2 minutes from upload to first appearance.

Check the queue: `journalctl -u piframe | grep ingest`.

### Backend fails to start

```bash
sudo systemctl status piframe
journalctl -u piframe -b --no-pager
```

Common causes: missing Python packages (`pip3 install -r /opt/piframe/requirements.txt`),
wrong `WorkingDirectory`, or missing `data/` directories
(`mkdir -p /opt/piframe/data/{photos/{originals,display},cache}`).

### Re-running the installer after an update

```bash
cd ~/piframe
git pull
sudo bash deploy/install.sh
```

The installer preserves all photos and the weather cache across updates
(`data/` is excluded from the rsync).
