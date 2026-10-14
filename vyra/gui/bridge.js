// Bridge: connects the JARVIS HUD front-end to Rusty's backend
// (WebSocket /ws + /api/*). The HUD exposes window.JARVIS; we drive it from
// real server events and route the command bar / core to the real brain + mic.
(function () {
  const J = window.JARVIS;
  if (!J) return;
  try { J.demo(false); } catch (_) {}

  const PIN = new URLSearchParams(location.search).get('pin') || '';
  const withPin = (p) => p + (PIN ? ((p.includes('?') ? '&' : '?') + 'pin=' + encodeURIComponent(PIN)) : '');
  const WS_URL = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws' + (PIN ? ('?pin=' + encodeURIComponent(PIN)) : '');

  const STATE_MAP = { idle: 'idle', listening: 'listening', attentive: 'listening', thinking: 'thinking', speaking: 'speaking', wake: 'wake', alert: 'alert' };
  let listening = false, muted = false;

  async function post(path, body) {
    try {
      const r = await fetch(withPin(path), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
      return await r.json();
    } catch (_) { return null; }
  }

  // Command bar text => brain; empty (core/space hold) => real voice capture.
  J.onCommand = (text) => {
    text = (text || '').trim();
    if (text) {
      try { J.log(text, 'usr'); } catch (_) {}
      post('/api/chat', { message: text, mute: muted });
    } else {
      if (listening) return;
      listening = true;
      post('/api/voice/listen', { mute: muted }).then(() => { listening = false; });
    }
  };

  // Server events -> HUD
  function connect() {
    let ws;
    try { ws = new WebSocket(WS_URL); } catch (_) { setTimeout(connect, 2000); return; }
    ws.onmessage = (e) => {
      let d; try { d = JSON.parse(e.data); } catch (_) { return; }
      try {
        if (d.type === 'telemetry') {
          J.setGauges({ cpu: d.cpu, ram: d.ram_percent, battery: (typeof d.battery_percent === 'number' ? d.battery_percent : 100) });
        } else if (d.type === 'state') {
          J.setStatus(STATE_MAP[d.state] || 'idle');
        } else if (d.type === 'audio_meter') {
          J.setVoice(d.level || 0);
        } else if (d.type === 'speech') {
          J.say(d.text);
        } else if (d.type === 'wake_detected') {
          J.wake(); if (d.command) J.log(d.command, 'usr');
        } else if (d.type === 'log') {
          const kind = d.level === 'user' ? 'usr' : (d.level === 'vyra' ? 'jrv' : (d.level === 'alt' ? 'alt' : 'sys'));
          J.log(d.message || d.text || '', kind);
        }
      } catch (_) {}
    };
    ws.onclose = () => setTimeout(connect, 2000);
  }
  connect();

  // Wire the HUD's action chips (Wake / Alert / Standby) to real backend actions
  // (the Status/Scan/Time chips and Send already route through onCommand).
  document.querySelectorAll('.chips button[data-act]').forEach((b) => {
    const act = b.getAttribute('data-act');
    b.addEventListener('click', () => {
      if (act === 'wake') {
        if (!listening) { listening = true; post('/api/voice/listen', { mute: muted }).then(() => { listening = false; }); }
      } else if (act === 'standby') {
        post('/api/voice/stop', {});
      } else if (act === 'alert') {
        try { J.log('Alert check', 'usr'); } catch (_) {}
        post('/api/chat', { message: 'Quick alert check — anything urgent with my battery, system, or reminders?', mute: muted });
      }
    });
  });

  // Tactical HUD window & audio controls
  function winCall(apiName, httpPath) {
    if (window.pywebview && window.pywebview.api && window.pywebview.api[apiName]) {
      try { window.pywebview.api[apiName](); return; } catch (_) {}
    }
    fetch(withPin(httpPath), { method: 'POST' }).catch(() => {});
  }

  let isPinned = true;
  let isPip = true;

  const ctl = document.createElement('div');
  ctl.className = 'tactical-window-controls';
  ctl.style.cssText = 'position:fixed;top:8px;right:14px;z-index:99999;display:flex;gap:6px;align-items:center;';

  const mk = (icon, title, fn, id) => {
    const b = document.createElement('button');
    b.id = id || '';
    b.innerHTML = icon;
    b.title = title;
    b.style.cssText = 'width:26px;height:24px;border:1px solid rgba(79,216,255,0.4);background:rgba(2,16,25,0.75);color:#d7f5ff;border-radius:3px;cursor:pointer;font-size:12px;display:flex;align-items:center;justify-content:center;transition:all 0.2s;box-shadow:0 0 6px rgba(79,216,255,0.15);';
    b.onmouseenter = () => { b.style.borderColor = 'rgba(79,216,255,0.9)'; b.style.boxShadow = '0 0 10px rgba(79,216,255,0.5)'; b.style.background = 'rgba(79,216,255,0.15)'; };
    b.onmouseleave = () => { b.style.borderColor = 'rgba(79,216,255,0.4)'; b.style.boxShadow = '0 0 6px rgba(79,216,255,0.15)'; b.style.background = 'rgba(2,16,25,0.75)'; };
    b.onclick = fn;
    return b;
  };

  const muteBtn = mk('🔊', 'Toggle Voice Mute', () => {
    muted = !muted;
    muteBtn.innerHTML = muted ? '🔇' : '🔊';
    muteBtn.title = muted ? 'Unmute Rusty' : 'Mute Rusty';
    try { J.log(muted ? 'Voice synthesis muted.' : 'Voice synthesis active.', 'sys'); } catch (_) {}
  }, 'hudMuteBtn');

  const pinBtn = mk('📌', 'Pin to Top (Always on Top)', () => {
    isPinned = !isPinned;
    pinBtn.style.opacity = isPinned ? '1' : '0.5';
    winCall('toggle_pin', '/api/window/pin');
  }, 'hudPinBtn');

  const modeBtn = mk('⛶', 'Toggle Window Layout (PiP / Full)', () => {
    isPip = !isPip;
    winCall('toggle_mode', '/api/window/mode');
  }, 'hudModeBtn');

  const minBtn = mk('—', 'Minimise', () => winCall('minimize', '/api/window/minimize'), 'hudMinBtn');
  const closeBtn = mk('✕', 'Close', () => winCall('close', '/api/window/close'), 'hudCloseBtn');

  ctl.appendChild(muteBtn);
  ctl.appendChild(pinBtn);
  ctl.appendChild(modeBtn);
  ctl.appendChild(minBtn);
  ctl.appendChild(closeBtn);
  document.body.appendChild(ctl);
})();
