'use strict';

// ── Constants ──────────────────────────────────────────────────────────────
const MAX_W = 1920;
const MAX_H = 1080;

// ── State ──────────────────────────────────────────────────────────────────
let queue = [];   // [{file, itemEl}]
let busy  = false;

// ── Elements ───────────────────────────────────────────────────────────────
const dropZone   = document.getElementById('drop-zone');
const fileInput  = document.getElementById('file-input');
const queueSec   = document.getElementById('queue-section');
const queueList  = document.getElementById('queue-list');
const photoGrid  = document.getElementById('photo-grid');
const emptyMsg   = document.getElementById('empty-msg');
const countBadge = document.getElementById('photo-count');
const serverInfo = document.getElementById('server-info');

// ── Utility ────────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function fmtMB(bytes) { return (bytes / 1048576).toFixed(1) + ' MB'; }

function toJpgName(name) { return name.replace(/\.[^.]+$/, '') + '.jpg'; }

// ── Drag-and-drop ──────────────────────────────────────────────────────────
dropZone.addEventListener('dragover', e => {
  e.preventDefault();
  dropZone.classList.add('drag-over');
});
['dragleave', 'dragend'].forEach(ev =>
  dropZone.addEventListener(ev, () => dropZone.classList.remove('drag-over'))
);
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  enqueue(Array.from(e.dataTransfer.files));
});

// Keyboard activation for the drop zone (accessibility)
dropZone.addEventListener('keydown', e => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
});

fileInput.addEventListener('change', () => {
  enqueue(Array.from(fileInput.files));
  fileInput.value = '';
});

// ── Queue management ───────────────────────────────────────────────────────
function enqueue(files) {
  const images = files.filter(f => f.type.startsWith('image/'));
  if (images.length === 0) return;

  queueSec.hidden = false;
  images.forEach(f => {
    const itemEl = buildQueueItem(f.name);
    queue.push({ file: f, itemEl });
  });
  drain();
}

function buildQueueItem(name) {
  const li = document.createElement('li');
  li.className = 'queue-item';
  li.innerHTML =
    '<div class="q-name"><span class="q-filename">' + escHtml(name) + '</span>' +
    '<span class="q-size"></span></div>' +
    '<span class="q-status">waiting</span>' +
    '<div class="progress-track"><div class="progress-bar"></div></div>';
  queueList.appendChild(li);
  queueList.scrollTop = queueList.scrollHeight;
  return li;
}

async function drain() {
  if (busy || queue.length === 0) return;
  busy = true;
  const job = queue.shift();
  await upload(job.file, job.itemEl);
  busy = false;
  drain();
}

// ── EXIF orientation ───────────────────────────────────────────────────────

// Read the first 64 KB of the file and return the EXIF orientation tag value
// (1–8), or 1 if absent / unreadable.
async function readFileExifOrientation(file) {
  try {
    return parseExifOrientation(await file.slice(0, 65536).arrayBuffer());
  } catch (_) {
    return 1;
  }
}

// Walk JPEG APP markers looking for the Orientation tag (0x0112) in IFD0.
function parseExifOrientation(buffer) {
  const v = new DataView(buffer);
  if (v.byteLength < 4 || v.getUint16(0) !== 0xFFD8) return 1; // not JPEG
  let off = 2;
  while (off + 2 <= v.byteLength) {
    const marker = v.getUint16(off);
    off += 2;
    if (marker === 0xFFD9 || marker === 0xFFDA) break; // EOI / SOS
    if ((marker & 0xFF00) !== 0xFF00) break;
    if (off + 2 > v.byteLength) break;
    const segLen = v.getUint16(off); // includes these 2 bytes
    if (segLen < 2 || off + segLen > v.byteLength) break;
    if (marker === 0xFFE1 && segLen >= 8 &&
        v.getUint8(off+2) === 0x45 && v.getUint8(off+3) === 0x78 && // Ex
        v.getUint8(off+4) === 0x69 && v.getUint8(off+5) === 0x66 && // if
        v.getUint8(off+6) === 0x00 && v.getUint8(off+7) === 0x00) { // \0\0
      const tiff = off + 8;
      if (tiff + 8 > v.byteLength) break;
      const le  = v.getUint16(tiff) === 0x4949;        // 'II' = little-endian
      if (v.getUint16(tiff + 2, le) !== 42) break;     // TIFF magic
      const ifd0 = tiff + v.getUint32(tiff + 4, le);
      if (ifd0 + 2 > v.byteLength) break;
      const n = v.getUint16(ifd0, le);
      for (let i = 0; i < n; i++) {
        const e = ifd0 + 2 + i * 12;
        if (e + 12 > v.byteLength) break;
        if (v.getUint16(e, le) === 0x0112)              // Orientation tag
          return v.getUint16(e + 8, le);
      }
    }
    off += segLen;
  }
  return 1;
}

// Set the canvas 2-D transform so that ctx.drawImage(img, 0, 0, drawW, drawH)
// produces a correctly oriented output.  dw/dh are the canvas dimensions
// (already axis-swapped for transposed orientations 5–8).
//
// Derivation: for each orientation the matrix maps drawing coordinates
// (proportional to stored pixel position) to canvas pixel coordinates.
function applyExifTransform(ctx, orientation, dw, dh) {
  switch (orientation) {
    case 2: ctx.transform(-1,  0,  0,  1, dw,  0); break; // flip H
    case 3: ctx.transform(-1,  0,  0, -1, dw, dh); break; // rotate 180°
    case 4: ctx.transform( 1,  0,  0, -1,  0, dh); break; // flip V
    case 5: ctx.transform( 0,  1,  1,  0,  0,  0); break; // transpose
    case 6: ctx.transform( 0,  1, -1,  0, dw,  0); break; // rotate 90° CW
    case 7: ctx.transform( 0, -1, -1,  0, dw, dh); break; // transverse
    case 8: ctx.transform( 0, -1,  1,  0,  0, dh); break; // rotate 90° CCW
    // case 1: identity — no transform needed
  }
}

// ── Canvas resize ──────────────────────────────────────────────────────────
// Reads EXIF orientation, disables browser auto-correction so we get raw
// stored pixels, scales to fit MAX_W × MAX_H (Pillow thumbnail() logic),
// applies the orientation transform, and re-encodes as JPEG at quality 0.85.
async function resizeToJpeg(file) {
  const orientation = await readFileExifOrientation(file);

  return new Promise((resolve, reject) => {
    const img = new Image();
    // Disable the browser's automatic EXIF orientation so naturalWidth/Height
    // reflect the stored (pre-rotation) dimensions and drawImage gives raw
    // pixels — we apply the correct transform ourselves via applyExifTransform.
    img.style.imageOrientation = 'none';
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      const sw = img.naturalWidth;   // stored width  (pre-rotation)
      const sh = img.naturalHeight;  // stored height (pre-rotation)

      // Orientations 5–8 swap axes; compute the logical (display) dimensions.
      const transposed = orientation >= 5 && orientation <= 8;
      let dw = transposed ? sh : sw;
      let dh = transposed ? sw : sh;

      if (dw > MAX_W || dh > MAX_H) {
        const scale = Math.min(MAX_W / dw, MAX_H / dh);
        dw = Math.round(dw * scale);
        dh = Math.round(dh * scale);
      }

      const canvas = document.createElement('canvas');
      canvas.width  = dw;
      canvas.height = dh;
      const ctx = canvas.getContext('2d');

      applyExifTransform(ctx, orientation, dw, dh);

      // For transposed orientations the draw dimensions are swapped relative
      // to the canvas dimensions (the transform maps stored x↔y axes).
      ctx.drawImage(img, 0, 0, transposed ? dh : dw, transposed ? dw : dh);

      canvas.toBlob(
        blob => blob ? resolve(blob) : reject(new Error('canvas.toBlob failed')),
        'image/jpeg', 0.85
      );
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('image decode failed'));
    };
    img.src = url;
  });
}

// ── XHR upload ─────────────────────────────────────────────────────────────
async function upload(file, itemEl) {
  const statusEl   = itemEl.querySelector('.q-status');
  const progressEl = itemEl.querySelector('.progress-bar');
  const sizeEl     = itemEl.querySelector('.q-size');

  statusEl.textContent = 'resizing…';

  let blob;
  try {
    blob = await resizeToJpeg(file);
  } catch (err) {
    statusEl.textContent = 'error';
    sizeEl.textContent   = err.message;
    itemEl.classList.add('status-error');
    return;
  }

  sizeEl.textContent   = fmtMB(file.size) + ' → ' + fmtMB(blob.size);
  statusEl.textContent = 'uploading';

  const fd = new FormData();
  fd.append('file', blob, toJpgName(file.name));

  await new Promise(resolve => {
    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', e => {
      if (!e.lengthComputable) return;
      const pct = Math.round(e.loaded / e.total * 100);
      progressEl.style.width = pct + '%';
      statusEl.textContent   = pct + '%';
    });

    xhr.addEventListener('load', () => {
      let status = 'error';
      let hash   = null;
      try {
        const body = JSON.parse(xhr.responseText);
        const res  = Array.isArray(body.results) ? body.results[0] : null;
        if (res) { status = res.status; hash = res.hash; }
      } catch (_) {}

      progressEl.style.width = '100%';
      statusEl.textContent   = status;
      itemEl.classList.add('status-' + status);

      if (status === 'accepted' && hash) {
        waitForPhoto(hash);
      }
      resolve();
    });

    xhr.addEventListener('error', () => {
      statusEl.textContent = 'error';
      itemEl.classList.add('status-error');
      resolve();
    });

    xhr.open('POST', '/api/upload');
    xhr.send(fd);
  });
}

// ── Poll until display copy appears in manifest ────────────────────────────
// Ingest is now synchronous on the backend, so the photo should appear in
// the manifest on the first poll after a brief delay.
async function waitForPhoto(hash) {
  const filename = hash + '.jpg';
  for (let i = 0; i < 5; i++) {
    await sleep(1000);
    try {
      const r = await fetch('/api/photos');
      const d = await r.json();
      if ((d.photos || []).includes(filename)) {
        addThumbnail(filename);
        return;
      }
    } catch (_) {}
  }
}

// ── Photo grid ─────────────────────────────────────────────────────────────
function updateEmptyState() {
  const count = photoGrid.childElementCount;
  emptyMsg.hidden        = count > 0;
  countBadge.textContent = count > 0 ? count : '';
}

function addThumbnail(filename) {
  if (photoGrid.querySelector('[data-filename="' + CSS.escape(filename) + '"]')) return;

  const hash = filename.replace(/\.jpg$/, '');
  const div  = document.createElement('div');
  div.className        = 'thumb-item';
  div.dataset.filename = filename;

  const img   = document.createElement('img');
  img.src     = '/photos/' + filename;
  img.alt     = '';
  img.loading = 'lazy';

  const btn = document.createElement('button');
  btn.className     = 'btn-delete';
  btn.type          = 'button';
  btn.setAttribute('aria-label', 'Delete photo');
  btn.textContent   = '✕';
  btn.addEventListener('click', () => confirmDelete(hash, div));

  div.appendChild(img);
  div.appendChild(btn);
  photoGrid.appendChild(div);
  updateEmptyState();
}

function confirmDelete(hash, itemEl) {
  if (!confirm('Delete this photo from the slideshow?')) return;
  itemEl.classList.add('deleting');
  fetch('/api/photos/' + hash, { method: 'DELETE' })
    .then(r => {
      if (r.status === 204) {
        itemEl.remove();
        updateEmptyState();
      } else {
        itemEl.classList.remove('deleting');
        alert('Delete failed (server error).');
      }
    })
    .catch(() => {
      itemEl.classList.remove('deleting');
      alert('Delete failed (network error).');
    });
}

// ── Initial grid load ──────────────────────────────────────────────────────
async function loadGrid() {
  try {
    const r = await fetch('/api/photos');
    const d = await r.json();
    photoGrid.innerHTML = '';
    (d.photos || []).forEach(addThumbnail);
  } catch (_) {}
}

// ── Server info footer ─────────────────────────────────────────────────────
async function loadServerInfo() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    if (d.pi_ip) {
      serverInfo.textContent = 'PiFrame · ' + d.pi_ip + ':5000';
    }
  } catch (_) {}
}

loadGrid();
loadServerInfo();
