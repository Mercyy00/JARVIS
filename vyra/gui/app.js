// FRIDAY — Aurora Glass controller.
// Same server contract as before (WS /ws + /api/*), new interface.

const HOST = window.location.host;
// When opened from the phone, the URL carries ?pin=XXXX — pass it on every request.
const PIN = new URLSearchParams(location.search).get('pin') || '';
const WS_URL = (location.protocol === 'https:' ? 'wss://' : 'ws://') + HOST + '/ws' + (PIN ? ('?pin=' + encodeURIComponent(PIN)) : '');
if (PIN) {
  const _fetch = window.fetch.bind(window);
  window.fetch = (u, o) => _fetch(
    (typeof u === 'string' && u.startsWith('/')) ? (u + (u.includes('?') ? '&' : '?') + 'pin=' + encodeURIComponent(PIN)) : u, o);
}

let ws = null;
let state = 'idle';
let isMuted = false;
let isPip = true;
let isPinned = true;
let wakeOn = true;
let listening = false;
let holdingSpace = false;
let spaceStart = 0;

const $ = (id) => document.getElementById(id);
const orb = $('orb'), orbWrap = document.querySelector('.orb-wrap'), ring = $('orbRing');
const stateLine = $('stateLine'), transcript = $('transcript'), logFeed = $('logFeed');
const input = $('input');

// --- icons ---
const S = (inner) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
const ICONS = {
  volOn: S('<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>'),
  volOff: S('<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/>'),
  pin: S('<path d="M12 17v5"/><path d="M5 17h14v-2l-2-3V5a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7l-2 3v2z"/>'),
  expand: S('<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>'),
  collapse: S('<path d="M4 14h6v6"/><path d="M20 10h-6V4"/><path d="M14 10l7-7"/><path d="M3 21l7-7"/>'),
  settings: S('<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>'),
  min: S('<line x1="5" y1="12" x2="19" y2="12"/>'),
  close: S('<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>'),
  mic: S('<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/>'),
  send: S('<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>'),
};
$('muteBtn').innerHTML = ICONS.volOn;
$('pinBtn').innerHTML = ICONS.pin;
$('expandBtn').innerHTML = ICONS.expand;
$('settingsBtn').innerHTML = ICONS.settings;
$('minBtn').innerHTML = ICONS.min;
$('closeBtn').innerHTML = ICONS.close;
$('sheetClose').innerHTML = ICONS.close;
$('micBtn').innerHTML = ICONS.mic;
$('sendBtn').innerHTML = ICONS.send;

// --- clock ---
function tick() {
  const now = new Date();
  const c = $('clock');
  if (c) c.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
setInterval(tick, 1000); tick();

// --- state + reactive orb ---
function setLevel(v) { if (orbWrap) orbWrap.style.setProperty('--level', Math.max(0, Math.min(1, v))); }

function setState(s) {
  state = s;
  document.body.classList.remove('state-idle', 'state-listening', 'state-thinking', 'state-speaking', 'state-attentive');
  document.body.classList.add('state-' + s);
  const words = { idle: 'Standing by.', listening: "I'm listening…", attentive: 'Still here — go on.', thinking: 'Thinking…', speaking: 'Speaking…' };
  stateLine.textContent = words[s] || '';
  if (s !== 'listening' && s !== 'attentive') setLevel(0);
}

// --- transcript + activity log ---
function addMsg(role, text) {
  if (!transcript || !text) return;
  const last = transcript.lastElementChild;
  if (last && last.classList.contains(role) && last.dataset.text === text) return;
  const el = document.createElement('div');
  el.className = 'msg ' + role; el.dataset.text = text;
  const who = document.createElement('span'); who.className = 'who';
  who.textContent = role === 'you' ? 'You' : role === 'friday' ? 'Rusty' : 'Action';
  const body = document.createElement('span'); body.textContent = text;
  el.append(who, body);
  transcript.appendChild(el);
  transcript.scrollTop = transcript.scrollHeight;
}

function addLog(level, text) {
  if (!logFeed || !text) return;
  const row = document.createElement('div'); row.className = 'log-row ' + (level || 'system');
  const t = document.createElement('span'); t.className = 't';
  t.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const m = document.createElement('span'); m.className = 'm'; m.textContent = text;
  row.append(t, m);
  logFeed.appendChild(row);
  logFeed.scrollTop = logFeed.scrollHeight;
}

// --- websocket ---
function connect() {
  const t0 = Date.now();
  ws = new WebSocket(WS_URL);
  ws.onopen = () => { $('connDot').classList.remove('down'); addLog('system', 'Connected to Rusty.'); const p = $('ping'); if (p) p.textContent = (Date.now() - t0) + 'ms'; };
  ws.onmessage = (e) => { try { onEvent(JSON.parse(e.data)); } catch (_) {} };
  ws.onclose = () => { $('connDot').classList.add('down'); addLog('system', 'Link lost — reconnecting…'); setTimeout(connect, 2000); };
}

function onEvent(d) {
  switch (d.type) {
    case 'telemetry': onTelemetry(d); break;
    case 'state': setState(d.state); break;
    case 'audio_meter':
      setLevel(d.level || 0);
      if (state === 'listening' || state === 'attentive') stateLine.textContent = d.speaking ? 'I hear you…' : "I'm listening…";
      break;
    case 'speech': addMsg('friday', d.text); addLog('friday', d.text); break;
    case 'wake_detected': addLog('system', 'Woke to “' + d.phrase + '”'); break;
    case 'wake_toggle': setWake(d.enabled); break;
    case 'log':
      addLog(d.level || 'system', d.message || d.text);
      if (d.level === 'user') addMsg('you', d.message || d.text);
      break;
  }
}

function onTelemetry(d) {
  const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };
  const bar = (id, pct) => { const e = $(id); if (e) e.style.width = Math.round(pct) + '%'; };
  set('cpu', Math.round(d.cpu) + '%'); bar('cpuBar', d.cpu);
  set('ram', Math.round(d.ram_percent) + '%'); bar('ramBar', d.ram_percent);
  set('ramSub', d.ram_used_gb + ' / ' + d.ram_total_gb + ' GB');
  if (typeof d.battery_percent === 'number') {
    set('battery', d.battery_percent + '%'); bar('batteryBar', d.battery_percent);
    set('batterySub', d.battery_plugged ? 'Charging' : 'On battery');
    const bb = $('batteryBar'); if (bb) bb.style.background = d.battery_percent <= 20 ? 'linear-gradient(90deg, var(--warn), var(--danger))' : '';
  } else { set('battery', 'AC'); bar('batteryBar', 100); set('batterySub', 'Desktop power'); }
  if (d.gpu) set('gpu', d.gpu);
  if (d.model) { set('model', d.model); set('sheetModel', d.model); }
  if (d.provider) set('sheetProvider', d.provider);
  if (d.ping) set('ping', d.ping + 'ms');
  if (typeof d.wake_enabled === 'boolean') setWake(d.wake_enabled);
}

// --- chat + voice ---
async function send(text) {
  text = (text || '').trim(); if (!text) return;
  input.value = '';
  addMsg('you', text); addLog('user', text);
  setState('thinking');
  try {
    const r = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: text, mute: isMuted }) });
    const d = await r.json();
    setState('idle');
    if (d.reply) { addMsg('friday', d.reply); addLog('friday', d.reply); }
  } catch (err) { setState('idle'); addLog('system', 'Something went wrong: ' + err.message); }
}

async function startVoice() {
  if (listening) return;
  listening = true; setLevel(0); setState('listening'); addLog('system', 'Listening…');
  try {
    const r = await fetch('/api/voice/listen', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mute: isMuted }) });
    const d = await r.json();
    listening = false; setState('idle');
    if (d.heard) addMsg('you', d.heard);
    if (d.reply) addMsg('friday', d.reply);
  } catch (err) { listening = false; setState('idle'); addLog('system', 'Voice ended: ' + err.message); }
}
async function stopVoice() { if (!listening) return; try { await fetch('/api/voice/stop', { method: 'POST' }); } catch (_) {} }
function toggleVoice() { listening ? stopVoice() : startVoice(); }

function setWake(on) {
  wakeOn = on;
  const b = $('wakeBtn'), t = $('wakeText');
  if (b) b.classList.toggle('on', on);
  if (t) t.textContent = on ? 'Listening for “Rusty”' : 'Wake word off';
}

// --- input wiring ---
$('sendBtn').addEventListener('click', () => send(input.value));
input.addEventListener('keydown', (e) => { if (e.key === 'Enter') send(input.value); });
$('micBtn').addEventListener('click', toggleVoice);
orb.addEventListener('click', toggleVoice);
$('wakeBtn').addEventListener('click', async () => {
  try { const r = await fetch('/api/voice/wake/toggle', { method: 'POST' }); const d = await r.json(); setWake(d.wake_enabled); } catch (_) {}
});
$('muteBtn').addEventListener('click', () => {
  isMuted = !isMuted;
  $('muteBtn').innerHTML = isMuted ? ICONS.volOff : ICONS.volOn;
  $('muteBtn').classList.toggle('on', isMuted);
  addLog('system', isMuted ? 'Voice muted.' : 'Voice on.');
});
document.querySelectorAll('.chip').forEach(c => c.addEventListener('click', () => { const cmd = c.getAttribute('data-cmd'); if (cmd) send(cmd); }));

window.addEventListener('keydown', (e) => {
  if (e.code === 'Space' && document.activeElement !== input) {
    e.preventDefault(); if (e.repeat) return;
    if (!holdingSpace) { holdingSpace = true; spaceStart = Date.now(); toggleVoice(); }
  }
});
window.addEventListener('keyup', (e) => {
  if (e.code === 'Space' && document.activeElement !== input) {
    if (holdingSpace) { const dur = Date.now() - spaceStart; holdingSpace = false; if (dur > 400 && listening) stopVoice(); }
  }
});

// --- window controls (pywebview js_api, with HTTP fallback) ---
function winCall(apiName, httpPath) {
  if (window.pywebview && window.pywebview.api && window.pywebview.api[apiName]) {
    try { window.pywebview.api[apiName](); return; } catch (_) {}
  }
  fetch(httpPath, { method: 'POST' }).catch(() => {});
}
$('pinBtn').addEventListener('click', () => { isPinned = !isPinned; $('pinBtn').classList.toggle('on', isPinned); winCall('toggle_pin', '/api/window/pin'); });
$('minBtn').addEventListener('click', () => winCall('minimize', '/api/window/minimize'));
$('closeBtn').addEventListener('click', () => winCall('close', '/api/window/close'));
$('expandBtn').addEventListener('click', () => {
  isPip = !isPip;
  document.body.classList.toggle('pip-mode', isPip);
  $('expandBtn').innerHTML = isPip ? ICONS.expand : ICONS.collapse;
  $('expandBtn').title = isPip ? 'Expand' : 'Shrink to corner';
  if (window.pywebview && window.pywebview.api && window.pywebview.api.toggle_mode) {
    try { window.pywebview.api.toggle_mode(); } catch (_) {}
  } else {
    fetch('/api/window/mode', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: isPip ? 'pip' : 'full' }) }).catch(() => {});
  }
  if (!isPip) fetchMemory();
});

// --- settings sheet + tabs ---
const sheet = $('settingsSheet'), backdrop = $('sheetBackdrop');
const openSheet = () => { sheet.classList.add('show'); backdrop.classList.add('show'); sheet.setAttribute('aria-hidden', 'false'); };
const closeSheet = () => { sheet.classList.remove('show'); backdrop.classList.remove('show'); sheet.setAttribute('aria-hidden', 'true'); };
$('settingsBtn').addEventListener('click', openSheet);
$('sheetClose').addEventListener('click', closeSheet);
backdrop.addEventListener('click', closeSheet);

document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('on'));
  tab.classList.add('on');
  const which = tab.getAttribute('data-tab');
  $('tabActivity').classList.toggle('hidden', which !== 'activity');
  $('tabMemory').classList.toggle('hidden', which !== 'memory');
  if (which === 'memory') fetchMemory();
}));

// --- autostart + memory ---
const autostart = $('autostart');
autostart.addEventListener('change', async () => {
  try {
    const r = await fetch('/api/autostart/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: autostart.checked }) });
    const d = await r.json();
    addLog('system', d.enabled ? 'Rusty will start with Windows.' : 'Rusty won’t start with Windows.');
  } catch (_) {}
});
async function loadAutostart() { try { const r = await fetch('/api/autostart'); const d = await r.json(); autostart.checked = !!d.enabled; } catch (_) {} }

function escapeHtml(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
async function fetchMemory() {
  try {
    const r = await fetch('/api/memory'); const d = await r.json();
    const prof = $('memProfile');
    if (prof) {
      prof.innerHTML = '';
      const facts = (d.profile && d.profile.about) || [];
      if (!facts.length) prof.innerHTML = '<div class="mem-empty">Nothing yet.</div>';
      else facts.forEach(f => { const el = document.createElement('div'); el.className = 'mem-item'; el.textContent = f; prof.appendChild(el); });
    }
    const links = $('memLinks');
    if (links) {
      links.innerHTML = '';
      const L = d.links || {}; const keys = Object.keys(L);
      if (!keys.length) links.innerHTML = '<div class="mem-empty">No saved links.</div>';
      else keys.forEach(k => { const el = document.createElement('div'); el.className = 'mem-item'; el.innerHTML = '<strong>' + escapeHtml(k) + '</strong> — <span class="u">' + escapeHtml(L[k]) + '</span>'; links.appendChild(el); });
    }
    const j = $('memJournal'); if (j && d.journal) j.textContent = d.journal;
  } catch (_) {}
}

// --- boot ---
setState('idle');
addMsg('friday', 'Hey Sir — I’m here. Hold space or just type.');
connect(); loadAutostart(); fetchMemory();
