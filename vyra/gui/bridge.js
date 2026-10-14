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
  let lastTelemetry = null;

  // --- Procedural Sci-Fi Earcons (Web Audio API) ---
  let audioCtx = null;
  function getAudioCtx() {
    try {
      if (!audioCtx) {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (AudioContext) audioCtx = new AudioContext();
      }
      if (audioCtx && audioCtx.state === 'suspended') {
        audioCtx.resume();
      }
      return audioCtx;
    } catch (_) { return null; }
  }

  function playChime(type) {
    if (muted) return;
    try {
      const ctx = getAudioCtx();
      if (!ctx) return;
      const t = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);

      if (type === 'wake') {
        // High dual-tone rising chirp (Iron Man HUD style)
        osc.type = 'sine';
        osc.frequency.setValueAtTime(587.33, t); // D5
        osc.frequency.exponentialRampToValueAtTime(880.00, t + 0.12); // A5
        osc.frequency.exponentialRampToValueAtTime(1174.66, t + 0.22); // D6
        gain.gain.setValueAtTime(0.08, t);
        gain.gain.exponentialRampToValueAtTime(0.001, t + 0.25);
        osc.start(t);
        osc.stop(t + 0.25);
      } else if (type === 'done') {
        // Subtle acknowledgment blip
        osc.type = 'sine';
        osc.frequency.setValueAtTime(880.00, t);
        osc.frequency.exponentialRampToValueAtTime(1318.51, t + 0.14);
        gain.gain.setValueAtTime(0.06, t);
        gain.gain.exponentialRampToValueAtTime(0.001, t + 0.18);
        osc.start(t);
        osc.stop(t + 0.18);
      } else if (type === 'standby') {
        // Descending power-down tone
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(520, t);
        osc.frequency.exponentialRampToValueAtTime(260, t + 0.2);
        gain.gain.setValueAtTime(0.06, t);
        gain.gain.exponentialRampToValueAtTime(0.001, t + 0.22);
        osc.start(t);
        osc.stop(t + 0.22);
      } else if (type === 'alert') {
        // Tactical dual pulse
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(440, t);
        osc.frequency.setValueAtTime(660, t + 0.08);
        gain.gain.setValueAtTime(0.06, t);
        gain.gain.exponentialRampToValueAtTime(0.001, t + 0.2);
        osc.start(t);
        osc.stop(t + 0.2);
      }
    } catch (_) {}
  }

  // Pre-unlock audio context on first user click anywhere
  window.addEventListener('pointerdown', () => getAudioCtx(), { once: true });

  async function post(path, body) {
    try {
      const r = await fetch(withPin(path), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
      return await r.json();
    } catch (_) { return null; }
  }

  async function get(path) {
    try {
      const r = await fetch(withPin(path));
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
      playChime('wake');
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
          lastTelemetry = d;
          J.setGauges({
            cpu: d.cpu,
            ram: d.ram_percent,
            battery: (typeof d.battery_percent === 'number' ? d.battery_percent : 100)
          });
        } else if (d.type === 'state') {
          J.setStatus(STATE_MAP[d.state] || 'idle');
        } else if (d.type === 'audio_meter') {
          J.setVoice(d.level || 0);
          if (d.spectrum && J.setSpectrum) {
            J.setSpectrum(d.spectrum);
          }
        } else if (d.type === 'speech') {
          J.say(d.text);
          playChime('done');
        } else if (d.type === 'wake_detected') {
          playChime('wake');
          J.wake(); if (d.command) J.log(d.command, 'usr');
        } else if (d.type === 'mode_changed') {
          if (window._applyModeUI) {
            window._applyModeUI(d.mode, d.muted);
          }
        } else if (d.type === 'progress') {
          if (d.message) {
            if (J.setProgress) {
              J.setProgress(d.message);
            } else {
              J.say(d.message, { after: 'thinking' });
            }
          }
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
  document.querySelectorAll('.chips button[data-act]').forEach((b) => {
    const act = b.getAttribute('data-act');
    b.addEventListener('click', () => {
      if (act === 'wake') {
        playChime('wake');
        if (!listening) { listening = true; post('/api/voice/listen', { mute: muted }).then(() => { listening = false; }); }
      } else if (act === 'standby') {
        playChime('standby');
        post('/api/voice/stop', {});
      } else if (act === 'alert') {
        playChime('alert');
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

  // --- Operational Mode Management ---
  let currentMode = 'tactical';
  const MODE_STYLES = {
    tactical: { label: '⚡ TACTICAL', color: '#4fd8ff', bg: 'rgba(79,216,255,0.15)', border: 'rgba(79,216,255,0.6)', glow: 'rgba(79,216,255,0.35)' },
    engineer: { label: '🛠️ ENGINEER', color: '#f59e0b', bg: 'rgba(245,158,11,0.15)', border: 'rgba(245,158,11,0.6)', glow: 'rgba(245,158,11,0.35)' },
    ghost:    { label: '👻 GHOST',    color: '#c084fc', bg: 'rgba(192,132,252,0.15)', border: 'rgba(192,132,252,0.6)', glow: 'rgba(192,132,252,0.35)' }
  };

  const modeBadge = document.createElement('button');
  modeBadge.id = 'hudModeBadge';
  modeBadge.style.cssText = 'height:24px;padding:0 8px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:10px;font-weight:bold;letter-spacing:1px;border-radius:3px;cursor:pointer;display:flex;align-items:center;gap:4px;transition:all 0.25s;text-transform:uppercase;';

  function applyModeUI(mode, isMuted) {
    currentMode = (mode || 'tactical').toLowerCase();
    const st = MODE_STYLES[currentMode] || MODE_STYLES.tactical;
    modeBadge.innerHTML = st.label;
    modeBadge.title = `Current Mode: ${currentMode.toUpperCase()} (Click to cycle: Tactical -> Engineer -> Ghost)`;
    modeBadge.style.color = st.color;
    modeBadge.style.background = st.bg;
    modeBadge.style.border = `1px solid ${st.border}`;
    modeBadge.style.boxShadow = `0 0 10px ${st.glow}`;

    const modeEl = document.getElementById('mode');
    if (modeEl) {
      modeEl.textContent = currentMode.toUpperCase();
      modeEl.style.color = st.color;
      modeEl.style.textShadow = `0 0 16px ${st.glow}`;
    }

    if (isMuted !== undefined) {
      muted = Boolean(isMuted);
      muteBtn.innerHTML = muted ? '🔇' : '🔊';
      muteBtn.title = muted ? 'Unmute Rusty' : 'Mute Rusty';
    }

    const sel = document.getElementById('selMode');
    if (sel && sel.value !== currentMode) {
      sel.value = currentMode;
    }
  }
  window._applyModeUI = applyModeUI;
  applyModeUI('tactical', false);

  modeBadge.onclick = async () => {
    const res = await post('/api/mode', {});
    if (res && res.mode) {
      applyModeUI(res.mode, res.muted);
      try { J.log(`Operational mode set to ${res.mode.toUpperCase()}`, 'sys'); } catch (_) {}
    }
  };


  // --- Tactical Settings & Memory Drawer Modal ---
  const drawer = document.createElement('div');
  drawer.id = 'hudSettingsDrawer';
  drawer.style.cssText = 'position:fixed;top:40px;right:14px;width:340px;max-height:80vh;background:rgba(3,18,30,0.95);border:1px solid rgba(79,216,255,0.45);box-shadow:0 0 24px rgba(79,216,255,0.25),inset 0 0 16px rgba(79,216,255,0.06);border-radius:6px;backdrop-filter:blur(10px);z-index:99998;display:none;flex-direction:column;font-family:ui-monospace,Menlo,Consolas,monospace;color:#d7f5ff;padding:12px;overflow:hidden;box-sizing:border-box;';

  drawer.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid rgba(79,216,255,0.25);padding-bottom:8px;margin-bottom:10px;">
      <span style="font-size:11px;font-weight:bold;letter-spacing:1.5px;color:#4fd8ff;">RUSTY TACTICAL CONFIG</span>
      <button id="drawerCloseBtn" style="background:none;border:none;color:#4fd8ff;cursor:pointer;font-size:14px;">✕</button>
    </div>
    <div style="display:flex;gap:6px;margin-bottom:10px;">
      <button id="tabDiag" style="flex:1;background:rgba(79,216,255,0.15);border:1px solid #4fd8ff;color:#d7f5ff;font-size:10px;padding:4px;cursor:pointer;border-radius:2px;">SYSTEM</button>
      <button id="tabMem" style="flex:1;background:rgba(2,16,25,0.6);border:1px solid rgba(79,216,255,0.3);color:#8ad7f5;font-size:10px;padding:4px;cursor:pointer;border-radius:2px;">MEMORY</button>
      <button id="tabToggles" style="flex:1;background:rgba(2,16,25,0.6);border:1px solid rgba(79,216,255,0.3);color:#8ad7f5;font-size:10px;padding:4px;cursor:pointer;border-radius:2px;">CONTROL</button>
    </div>
    <div id="drawerBody" style="flex:1;overflow-y:auto;font-size:11px;line-height:1.45;max-height:55vh;">
      <div id="paneDiag">Loading telemetry...</div>
      <div id="paneMem" style="display:none;">Loading memory profile...</div>
      <div id="paneToggles" style="display:none;">Loading controls...</div>
    </div>
    <div style="border-top:1px solid rgba(79,216,255,0.25);padding-top:8px;margin-top:10px;display:flex;justify-content:space-between;">
      <button id="copyLogBtn" style="background:rgba(79,216,255,0.1);border:1px solid rgba(79,216,255,0.4);color:#4fd8ff;font-size:10px;padding:4px 8px;cursor:pointer;border-radius:3px;">📋 Copy Terminal Log</button>
      <span style="font-size:9px;color:rgba(215,245,255,0.4);align-self:center;">MK VII · 2026</span>
    </div>
  `;
  document.body.appendChild(drawer);

  async function refreshDrawer() {
    const pDiag = document.getElementById('paneDiag');
    const pMem = document.getElementById('paneMem');
    const pTog = document.getElementById('paneToggles');

    // Telemetry view
    if (lastTelemetry) {
      pDiag.innerHTML = `
        <div style="margin-bottom:8px;"><strong style="color:#4fd8ff;">NEURAL CORE:</strong> ${lastTelemetry.model || 'Gemini'} (${lastTelemetry.provider || 'Google'})</div>
        <div style="margin-bottom:8px;"><strong style="color:#4fd8ff;">ACCELERATOR:</strong> ${lastTelemetry.gpu || 'Discrete GPU'}</div>
        <div style="margin-bottom:8px;"><strong style="color:#4fd8ff;">HOST SYSTEM:</strong> CPU ${Math.round(lastTelemetry.cpu)}% · RAM ${lastTelemetry.ram_used_gb}/${lastTelemetry.ram_total_gb} GB (${lastTelemetry.ram_percent}%)</div>
        <div style="margin-bottom:8px;"><strong style="color:#4fd8ff;">BATTERY:</strong> ${lastTelemetry.battery_percent}% (${lastTelemetry.battery_plugged ? 'Charging' : 'Discharging'})</div>
        <div style="margin-bottom:8px;"><strong style="color:#4fd8ff;">LINK:</strong> Port 8765 · WS Active · Latency ~${lastTelemetry.ping || 6}ms</div>
      `;
    }

    // Memory view
    const mem = await get('/api/memory');
    if (mem) {
      let factsHtml = (mem.profile && mem.profile.about && mem.profile.about.length)
        ? mem.profile.about.map(f => `<div style="margin-bottom:4px;color:#a8e6ff;">• ${f}</div>`).join('')
        : '<div style="color:rgba(215,245,255,0.4);">No user facts indexed yet.</div>';
      
      let linksHtml = (mem.links && Object.keys(mem.links).length)
        ? Object.entries(mem.links).map(([k, v]) => `<div style="margin-bottom:4px;"><strong style="color:#4fd8ff;">${k}:</strong> <span style="word-break:break-all;color:#a8e6ff;">${v}</span></div>`).join('')
        : '<div style="color:rgba(215,245,255,0.4);">No saved links.</div>';

      pMem.innerHTML = `
        <div style="margin-bottom:10px;"><strong style="color:#4fd8ff;">ABOUT USER:</strong><br>${factsHtml}</div>
        <div style="margin-bottom:10px;"><strong style="color:#4fd8ff;">QUICK LINKS:</strong><br>${linksHtml}</div>
        <div><strong style="color:#4fd8ff;">JOURNAL:</strong><br><div style="font-size:10px;color:rgba(215,245,255,0.7);max-height:100px;overflow-y:auto;white-space:pre-wrap;">${mem.journal || 'No entries.'}</div></div>
      `;
    }

    // Toggles view
    const auto = await get('/api/autostart');
    const autoEnabled = auto && auto.enabled;
    pTog.innerHTML = `
      <div style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;">
        <span>Operational Mode</span>
        <select id="selMode" style="background:#021019;border:1px solid #4fd8ff;color:#d7f5ff;font-size:11px;padding:3px 6px;border-radius:3px;cursor:pointer;">
          <option value="tactical" ${currentMode === 'tactical' ? 'selected' : ''}>⚡ Tactical</option>
          <option value="engineer" ${currentMode === 'engineer' ? 'selected' : ''}>🛠️ Engineer</option>
          <option value="ghost" ${currentMode === 'ghost' ? 'selected' : ''}>👻 Ghost (Stealth)</option>
        </select>
      </div>
      <div style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;">
        <span>Autostart with Windows</span>
        <input type="checkbox" id="chkAuto" ${autoEnabled ? 'checked' : ''} style="cursor:pointer;">
      </div>
      <div style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;">
        <span>Voice Wake Detection</span>
        <input type="checkbox" id="chkWake" ${(!lastTelemetry || lastTelemetry.wake_enabled !== false) ? 'checked' : ''} style="cursor:pointer;">
      </div>
      <div style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;">
        <span>Voice Synthesis Mute</span>
        <input type="checkbox" id="chkMute" ${muted ? 'checked' : ''} style="cursor:pointer;">
      </div>
    `;

    const selMode = document.getElementById('selMode');
    if (selMode) {
      selMode.onchange = async () => {
        const res = await post('/api/mode', { mode: selMode.value });
        if (res && res.mode) {
          applyModeUI(res.mode, res.muted);
          try { J.log(`Mode set to ${res.mode.toUpperCase()}`, 'sys'); } catch (_) {}
        }
      };
    }


    const chkAuto = document.getElementById('chkAuto');
    if (chkAuto) {
      chkAuto.onchange = async () => {
        const res = await post('/api/autostart/toggle', { enabled: chkAuto.checked });
        try { J.log(res && res.enabled ? 'Autostart enabled.' : 'Autostart disabled.', 'sys'); } catch (_) {}
      };
    }
    const chkWake = document.getElementById('chkWake');
    if (chkWake) {
      chkWake.onchange = async () => {
        const res = await post('/api/voice/wake/toggle', {});
        try { J.log(res && res.wake_enabled ? 'Wake word active.' : 'Wake word paused.', 'sys'); } catch (_) {}
      };
    }
    const chkMute = document.getElementById('chkMute');
    if (chkMute) {
      chkMute.onchange = () => {
        muted = chkMute.checked;
        muteBtn.innerHTML = muted ? '🔇' : '🔊';
        muteBtn.title = muted ? 'Unmute Rusty' : 'Mute Rusty';
        try { J.log(muted ? 'Voice synthesis muted.' : 'Voice synthesis active.', 'sys'); } catch (_) {}
      };
    }
  }

  const setTab = (activeTab) => {
    ['Diag', 'Mem', 'Toggles'].forEach(t => {
      const b = document.getElementById('tab' + t);
      const p = document.getElementById('pane' + t);
      if (t === activeTab) {
        b.style.background = 'rgba(79,216,255,0.2)';
        b.style.borderColor = '#4fd8ff';
        b.style.color = '#fff';
        p.style.display = 'block';
      } else {
        b.style.background = 'rgba(2,16,25,0.6)';
        b.style.borderColor = 'rgba(79,216,255,0.3)';
        b.style.color = '#8ad7f5';
        p.style.display = 'none';
      }
    });
  };

  document.getElementById('tabDiag').onclick = () => setTab('Diag');
  document.getElementById('tabMem').onclick = () => setTab('Mem');
  document.getElementById('tabToggles').onclick = () => setTab('Toggles');
  document.getElementById('drawerCloseBtn').onclick = () => { drawer.style.display = 'none'; };
  document.getElementById('copyLogBtn').onclick = () => {
    const feed = document.getElementById('feed');
    if (feed) {
      const txt = Array.from(feed.children).map(c => c.innerText).join('\n');
      navigator.clipboard.writeText(txt).then(() => {
        try { J.log('Terminal log copied to clipboard.', 'sys'); } catch (_) {}
      });
    }
  };

  const settingsBtn = mk('⚙', 'Tactical Config & Memory', () => {
    if (drawer.style.display === 'none' || !drawer.style.display) {
      drawer.style.display = 'flex';
      refreshDrawer();
    } else {
      drawer.style.display = 'none';
    }
  }, 'hudSettingsBtn');

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

  ctl.appendChild(modeBadge);
  ctl.appendChild(muteBtn);
  ctl.appendChild(settingsBtn);
  ctl.appendChild(pinBtn);
  ctl.appendChild(modeBtn);
  ctl.appendChild(minBtn);
  ctl.appendChild(closeBtn);
  document.body.appendChild(ctl);
})();
