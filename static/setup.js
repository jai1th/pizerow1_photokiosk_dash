/* PiFrame setup page.

   The important thing here: submitting credentials tears down the hotspot
   this page arrived over, so the request is answered with 202 and then the
   connection dies. There is no success response to wait for. The UI says so
   plainly rather than spinning forever on a fetch that will never resolve. */

(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  function say(el, msg, cls) {
    el.textContent = msg;
    el.className = 'status' + (cls ? ' ' + cls : '');
  }

  // ── Network picker ──────────────────────────────────────────────────────
  var pick = $('ssid-pick');
  var manualRow = $('manual-row');
  var manual = $('ssid');

  function chosenSsid() {
    if (!pick || pick.value === '__manual__') { return manual ? manual.value.trim() : ''; }
    return pick.value;
  }

  if (pick) {
    pick.addEventListener('change', function () {
      var isManual = pick.value === '__manual__';
      manualRow.classList.toggle('hidden', !isManual);
      if (isManual) { manual.focus(); }
    });
  }

  var showPsk = $('show-psk');
  if (showPsk) {
    showPsk.addEventListener('change', function () {
      $('psk').type = showPsk.checked ? 'text' : 'password';
    });
  }

  // ── Rescan ──────────────────────────────────────────────────────────────
  var rescan = $('rescan');
  if (rescan) {
    rescan.addEventListener('click', function () {
      var st = $('status');
      say(st, 'Scanning…', 'work');
      rescan.disabled = true;
      fetch('/api/wifi/scan?force=1')
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var nets = d.networks || [];
          // Rebuild in place, keeping whatever was already selected.
          var prev = pick.value;
          pick.innerHTML = '';
          pick.appendChild(new Option('Choose a network…', ''));
          nets.forEach(function (n) {
            pick.appendChild(new Option(n.ssid + ' (' + Math.round(n.signal) + ' dBm)', n.ssid));
          });
          pick.appendChild(new Option('Other / hidden network…', '__manual__'));
          pick.value = prev;
          say(st, nets.length ? 'Found ' + nets.length + ' networks.' : 'No networks found.',
              nets.length ? 'good' : 'bad');
        })
        .catch(function () { say(st, 'Scan failed.', 'bad'); })
        .then(function () { rescan.disabled = false; });
    });
  }

  // ── Join ────────────────────────────────────────────────────────────────
  var join = $('join');
  if (join) {
    join.addEventListener('click', function () {
      var st = $('status');
      var ssid = chosenSsid();
      var psk = $('psk').value;

      if (!ssid) { say(st, 'Pick a network first.', 'bad'); return; }
      if (psk && (psk.length < 8 || psk.length > 63)) {
        say(st, 'Password must be 8-63 characters.', 'bad');
        return;
      }

      join.disabled = true;
      say(st, 'Sending…', 'work');

      fetch('/api/wifi/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ssid: ssid, password: psk })
      })
        .then(function (r) {
          return r.json().then(function (d) { return { ok: r.ok, status: r.status, body: d }; });
        })
        .then(function (res) {
          if (!res.ok) {
            join.disabled = false;
            say(st, res.body.error || 'Rejected.', 'bad');
            return;
          }
          say(st, 'Switching to "' + ssid + '". This page will go offline now — '
                + 'that is expected. If it worked the frame is on your network; '
                + 'if not, the hotspot returns shortly and you can try again.', 'work');
        })
        .catch(function () {
          // A dropped connection here is the normal case, not a failure: the
          // hotspot can go down before the response finishes arriving.
          say(st, 'Connection closed — the frame is switching networks. '
                + 'Reconnect to your WiFi to check on it.', 'work');
        });
    });
  }

  // ── Hotspot credentials ─────────────────────────────────────────────────
  var saveHs = $('save-hs');
  if (saveHs) {
    saveHs.addEventListener('click', function () {
      var st = $('hs-status');
      var body = { ssid: $('hs-ssid').value.trim() };
      var pw = $('hs-psk').value;
      if (pw) { body.password = pw; }

      saveHs.disabled = true;
      say(st, 'Saving…', 'work');
      fetch('/api/wifi/hotspot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
        .then(function (r) {
          return r.json().then(function (d) { return { ok: r.ok, body: d }; });
        })
        .then(function (res) {
          say(st, res.ok ? 'Saved. Applies next time the hotspot starts.'
                         : (res.body.error || 'Save failed.'),
              res.ok ? 'good' : 'bad');
        })
        .catch(function () { say(st, 'Save failed.', 'bad'); })
        .then(function () { saveHs.disabled = false; });
    });
  }
})();
