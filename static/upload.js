'use strict';

// ── State ──────────────────────────────────────────────────────────────────
let queue    = [];   // [{file, itemEl}]
let busy     = false;

// ── Elements ───────────────────────────────────────────────────────────────
const dropZone    = document.getElementById('drop-zone');
const fileInput   = document.getElementById('file-input');
const queueSec    = document.getElementById('queue-section');
const queueList   = document.getElementById('queue-list');
const photoGrid   = document.getElementById('photo-grid');
const emptyMsg    = document.getElementById('empty-msg');
const countBadge  = document.getElementById('photo-count');
const serverInfo  = document.getElementById('server-info');

// ── Utility ────────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

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
    '<span class="q-name">' + escHtml(name) + '</span>' +
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

// ── XHR upload ─────────────────────────────────────────────────────────────
function upload(file, itemEl) {
  return new Promise(resolve => {
    const statusEl   = itemEl.querySelector('.q-status');
    const progressEl = itemEl.querySelector('.progress-bar');

    statusEl.textContent = 'uploading';

    const fd  = new FormData();
    fd.append('file', file);

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

// ── Poll until scaled display copy appears ─────────────────────────────────
async function waitForPhoto(hash) {
  const filename  = hash + '.jpg';
  const maxTries  = 40;  // 40 × 3 s = 120 s max wait
  for (let i = 0; i < maxTries; i++) {
    await sleep(3000);
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
  emptyMsg.hidden     = count > 0;
  countBadge.textContent = count > 0 ? count : '';
}

function addThumbnail(filename) {
  if (photoGrid.querySelector('[data-filename="' + CSS.escape(filename) + '"]')) return;

  const hash = filename.replace(/\.jpg$/, '');
  const div  = document.createElement('div');
  div.className        = 'thumb-item';
  div.dataset.filename = filename;

  const img  = document.createElement('img');
  img.src    = '/photos/' + filename;
  img.alt    = '';
  img.loading = 'lazy';

  const btn  = document.createElement('button');
  btn.className       = 'btn-delete';
  btn.type            = 'button';
  btn.setAttribute('aria-label', 'Delete photo');
  btn.textContent     = '✕';
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
