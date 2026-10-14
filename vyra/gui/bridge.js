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

  // Minimal window controls (borderless window) — minimise & close.
  function winCall(apiName, httpPath) {
    if (window.pywebview && window.pywebview.api && window.pywebview.api[apiName]) {
      try { window.pywebview.api[apiName](); return; } catch (_) {}
    }
    fetch(withPin(httpPath), { method: 'POST' }).catch(() => {});
  }
  const ctl = document.createElement('div');
  ctl.style.cssText = 'position:fixed;top:7px;right:9px;z-index:99999;display:flex;gap:7px;font:12px sans-serif';
  const mk = (label, title, fn) => {
    const b = document.createElement('button');
    b.textContent = label; b.title = title;
    b.style.cssText = 'width:22px;height:22px;border:1px solid rgba(120,180,220,.35);background:rgba(10,20,30,.5);color:#9fd4e6;border-radius:5px;cursor:pointer;line-height:1;padding:0';
    b.onclick = fn; return b;
  };
  ctl.appendChild(mk('—', 'Minimise', () => winCall('minimize', '/api/window/minimize')));
  ctl.appendChild(mk('✕', 'Close', () => winCall('close', '/api/window/close')));
  document.body.appendChild(ctl);
})();
