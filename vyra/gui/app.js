// FRIDAY Holographic Technical HUD Controller
// Precision-engineered, minimalist architecture
const HOST = window.location.host;
const WS_URL = (location.protocol === 'https:' ? 'wss://' : 'ws://') + HOST + '/ws';

let ws = null;
let currentState = 'idle'; // idle | listening | thinking | speaking | attentive
let isMuted = false;

// DOM Elements
const coreReactor = document.getElementById('coreReactor');
const coreIcon = document.getElementById('coreIcon');
const reactorState = document.getElementById('reactorState');
const reactorHint = document.getElementById('reactorHint');
const commandInput = document.getElementById('commandInput');
const sendBtn = document.getElementById('sendBtn');
const micToggleBtn = document.getElementById('micToggleBtn');
const liveSpeechText = document.getElementById('liveSpeechText');
const consoleFeed = document.getElementById('consoleFeed');
const cpuVal = document.getElementById('cpuVal');
const cpuBar = document.getElementById('cpuBar');
const ramVal = document.getElementById('ramVal');
const ramBar = document.getElementById('ramBar');
const ramText = document.getElementById('ramText');
const gpuName = document.getElementById('gpuName');
const modelName = document.getElementById('modelName');
const providerBadge = document.getElementById('providerBadge');
const pingVal = document.getElementById('pingVal');
const liveTime = document.getElementById('liveTime');
const liveDate = document.getElementById('liveDate');
const muteBtn = document.getElementById('muteBtn');
const wakeToggleBtn = document.getElementById('wakeToggleBtn');
const wakeStatusText = document.getElementById('wakeStatusText');
const chatStream = document.getElementById('chatStream');
const clearChatBtn = document.getElementById('clearChatBtn');
let isWakeEnabled = true;

// Tab switcher elements
const tabLogsBtn = document.getElementById('tabLogsBtn');
const tabMemoryBtn = document.getElementById('tabMemoryBtn');
const tabLogs = document.getElementById('tabLogs');
const tabMemory = document.getElementById('tabMemory');
const profileList = document.getElementById('profileList');
const linksList = document.getElementById('linksList');
const journalText = document.getElementById('journalText');

// Vector SVGs for dynamic icons
const MUTE_OFF_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path><path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path></svg>`;
const MUTE_ON_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><line x1="23" y1="9" x2="17" y2="15"></line><line x1="17" y1="9" x2="23" y2="15"></line></svg>`;

const PIP_EXPAND_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><rect x="11" y="11" width="8" height="8" rx="1" ry="1"></rect></svg>`;
const PIP_SHRINK_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"></path></svg>`;

// Clock formatting
function updateClock() {
  const now = new Date();
  const timeStr = now.toTimeString().split(' ')[0];
  const dateStr = now.toLocaleDateString('en-US', { month: 'short', day: '2-digit', year: 'numeric' }).toUpperCase();
  if (liveTime) liveTime.textContent = timeStr;
  if (liveDate) liveDate.textContent = dateStr;
}
setInterval(updateClock, 1000);
updateClock();

// Tab Switcher
if (tabLogsBtn && tabMemoryBtn && tabLogs && tabMemory) {
  tabLogsBtn.addEventListener('click', () => {
    tabLogsBtn.classList.add('active');
    tabMemoryBtn.classList.remove('active');
    tabLogs.classList.add('active');
    tabMemory.classList.remove('active');
  });

  tabMemoryBtn.addEventListener('click', () => {
    tabMemoryBtn.classList.add('active');
    tabLogsBtn.classList.remove('active');
    tabMemory.classList.add('active');
    tabLogs.classList.remove('active');
    fetchMemory();
  });
}

// Append Chat Message to Stream
function appendChatMessage(sender, text, type = 'user') {
  if (!chatStream || !text) return;
  const lastBubble = chatStream.lastElementChild;
  if (lastBubble && lastBubble.classList.contains(type)) {
    const lastContent = lastBubble.querySelector('.chat-text');
    if (lastContent && lastContent.textContent === text) {
      return; // Deduplicate
    }
  }
  const bubble = document.createElement('div');
  bubble.className = `chat-bubble ${type}`;

  const speaker = document.createElement('span');
  speaker.className = 'chat-speaker';
  const displaySender = sender.toLowerCase() === 'vyra' ? 'FRIDAY' : sender;
  speaker.textContent = displaySender.toUpperCase();

  const content = document.createElement('span');
  content.className = 'chat-text';
  content.textContent = text;

  bubble.appendChild(speaker);
  bubble.appendChild(content);
  chatStream.appendChild(bubble);
  chatStream.scrollTop = chatStream.scrollHeight;
}

// Clear Chat Button
if (clearChatBtn) {
  clearChatBtn.addEventListener('click', () => {
    if (chatStream) {
      chatStream.innerHTML = `
        <div class="chat-bubble vyra">
          <span class="chat-speaker">FRIDAY</span>
          <span class="chat-text">Stream cleared, boss. Standing by for directives.</span>
        </div>
      `;
    }
  });
}

// Console & Terminal Logs
function addLog(type, text) {
  const entry = document.createElement('div');
  entry.className = `log-entry ${type}`;
  const now = new Date();
  const timeStr = now.toTimeString().split(' ')[0];
  entry.innerHTML = `<span class="log-time">[${timeStr}]</span> ${escapeHtml(text)}`;
  if (consoleFeed) {
    consoleFeed.appendChild(entry);
    consoleFeed.scrollTop = consoleFeed.scrollHeight;
  }
  const drawerFeed = document.getElementById('drawerConsoleFeed');
  if (drawerFeed) {
    drawerFeed.appendChild(entry.cloneNode(true));
    drawerFeed.scrollTop = drawerFeed.scrollHeight;
  }
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Kinetic Reactor Core State Controller
function setReactorState(state) {
  currentState = state;
  if (!coreReactor) return;
  coreReactor.className = `arc-core state-${state}`;

  if (state === 'idle') {
    if (coreIcon) coreIcon.textContent = '⚡';
    if (reactorState) reactorState.textContent = 'CORE STATE: STANDBY';
    if (reactorHint) {
      reactorHint.textContent = isWakeEnabled
        ? '[SAY "FRIDAY" / "BUDDY" // OR PRESS SPACE]'
        : '[CLICK CORE OR PRESS SPACE TO TRANSMIT]';
    }
  } else if (state === 'listening') {
    if (coreIcon) coreIcon.textContent = '🎙️';
    if (reactorState) reactorState.textContent = 'CORE STATE: LISTENING';
    if (reactorHint) reactorHint.textContent = '[SPEAK NOW // DETECTING AUDIO INPUT]';
  } else if (state === 'thinking') {
    if (coreIcon) coreIcon.textContent = '⚙️';
    if (reactorState) reactorState.textContent = 'CORE STATE: INFERENCE';
    if (reactorHint) reactorHint.textContent = '[PROCESSING DIRECTIVE WITH GEMINI]';
  } else if (state === 'speaking') {
    if (coreIcon) coreIcon.textContent = '🔊';
    if (reactorState) reactorState.textContent = 'CORE STATE: VOCALIZING';
    if (reactorHint) reactorHint.textContent = '[TRANSMITTING AUDIO SYNTHESIS]';
  } else if (state === 'attentive') {
    if (coreIcon) coreIcon.textContent = '👂';
    if (reactorState) reactorState.textContent = 'CORE STATE: ATTENTIVE';
    if (reactorHint) reactorHint.textContent = '[CONTINUOUS FOLLOW-UP // SAY "THAT\'S ALL" TO SLEEP]';
    coreReactor.className = 'arc-core state-listening';
  }
}

// WebSocket Telemetry Connection
function connectWebSocket() {
  const startTime = Date.now();
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    addLog('system', 'Neural duplex telemetry link established.');
    if (pingVal) pingVal.textContent = `${Date.now() - startTime}ms`;
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleServerEvent(data);
    } catch (e) {
      console.error('Failed to parse WS data:', e);
    }
  };

  ws.onclose = () => {
    addLog('system', 'Neural link disconnected. Retrying in 2s...');
    setTimeout(connectWebSocket, 2000);
  };
}

function handleServerEvent(data) {
  if (data.type === 'telemetry') {
    if (cpuVal) cpuVal.textContent = `${Math.round(data.cpu)}%`;
    if (cpuBar) cpuBar.style.width = `${Math.round(data.cpu)}%`;
    if (ramVal) ramVal.textContent = `${Math.round(data.ram_percent)}%`;
    if (ramBar) ramBar.style.width = `${Math.round(data.ram_percent)}%`;
    if (ramText) ramText.textContent = `${data.ram_used_gb} / ${data.ram_total_gb} GB`;

    // Battery Telemetry
    const batteryVal = document.getElementById('batteryVal');
    const batteryBar = document.getElementById('batteryBar');
    const batteryStatusText = document.getElementById('batteryStatusText');
    const drawerBatteryVal = document.getElementById('drawerBatteryVal');
    if (typeof data.battery_percent === 'number') {
      const batPct = `${data.battery_percent}%`;
      const charging = data.battery_plugged ? 'CHARGING (AC)' : 'ON BATTERY';
      if (batteryVal) batteryVal.textContent = batPct;
      if (batteryBar) {
        batteryBar.style.width = batPct;
        batteryBar.style.background = data.battery_percent <= 20 ? 'var(--crimson-warn)' : 'var(--cyan-core)';
      }
      if (batteryStatusText) batteryStatusText.textContent = charging;
      if (drawerBatteryVal) drawerBatteryVal.textContent = `${batPct} (${charging})`;
    } else {
      if (batteryVal) batteryVal.textContent = 'AC';
      if (batteryBar) batteryBar.style.width = '100%';
      if (batteryStatusText) batteryStatusText.textContent = 'DESKTOP AC POWER';
      if (drawerBatteryVal) drawerBatteryVal.textContent = 'AC POWER';
    }

    const dCpu = document.getElementById('drawerCpuVal');
    const dRam = document.getElementById('drawerRamVal');
    const dMod = document.getElementById('drawerModelVal');
    if (dCpu) dCpu.textContent = `${Math.round(data.cpu)}%`;
    if (dRam) dRam.textContent = `${Math.round(data.ram_percent)}% (${data.ram_used_gb} GB)`;
    if (dMod && data.model) dMod.textContent = data.model;
    if (data.gpu && gpuName) gpuName.textContent = data.gpu;
    if (data.model && modelName) modelName.textContent = data.model;
    if (data.provider && providerBadge) providerBadge.textContent = data.provider.toUpperCase();
    if (data.ping && pingVal) pingVal.textContent = `${data.ping}ms`;
    if (typeof data.wake_enabled === 'boolean') updateWakeUI(data.wake_enabled);
  } else if (data.type === 'state') {
    setReactorState(data.state);
  } else if (data.type === 'wake_detected') {
    addLog('system', `[WAKE ENGAGED] "${data.phrase}"`);
    if (reactorState) reactorState.textContent = 'CORE STATE: WAKE ENGAGED';
    if (reactorHint) reactorHint.textContent = `[DIRECTIVE: "${data.command || 'LISTENING...'}" ]`;
    if (coreReactor) coreReactor.className = 'arc-core state-listening';
  } else if (data.type === 'wake_toggle') {
    updateWakeUI(data.enabled);
  } else if (data.type === 'audio_meter') {
    liveAudioLevel = data.level || 0.0;
    isUserSpeaking = !!data.speaking;
    if (currentState === 'listening') {
      if (isUserSpeaking) {
        if (reactorState) reactorState.textContent = 'CORE STATE: RECORDING VOICE';
        if (reactorHint) reactorHint.textContent = '[SPEECH DETECTED // PAUSE TO TRANSMIT]';
      } else {
        if (reactorState) reactorState.textContent = 'CORE STATE: LISTENING (MIC ACTIVE)';
        if (reactorHint) reactorHint.textContent = '[SPEAK NOW // DETECTING INPUT]';
      }
    }
  } else if (data.type === 'speech') {
    if (liveSpeechText) liveSpeechText.textContent = data.text;
    addLog('vyra', data.text);
    appendChatMessage('vyra', data.text, 'vyra');
  } else if (data.type === 'log') {
    addLog(data.level || 'system', data.message);
    if (data.level === 'user') {
      appendChatMessage('you', data.message, 'user');
    }
  }
}

// Memory & Dossier Loader
async function fetchMemory() {
  try {
    const res = await fetch('/api/memory');
    const data = await res.json();
    
    // Profile
    if (profileList) {
      profileList.innerHTML = '';
      const facts = data.profile?.about || [];
      if (facts.length === 0) {
        profileList.innerHTML = '<div class="vault-item">No personal dossier registered.</div>';
      } else {
        facts.forEach(f => {
          const item = document.createElement('div');
          item.className = 'vault-item';
          item.textContent = `• ${f}`;
          profileList.appendChild(item);
        });
      }
    }

    // Links
    if (linksList) {
      linksList.innerHTML = '';
      const links = data.links || {};
      const linkKeys = Object.keys(links);
      if (linkKeys.length === 0) {
        linksList.innerHTML = '<div class="vault-item">No satellite links saved.</div>';
      } else {
        linkKeys.forEach(k => {
          const item = document.createElement('div');
          item.className = 'vault-item';
          item.innerHTML = `<strong>${k}:</strong> <span style="color:var(--text-cyan)">${links[k]}</span>`;
          linksList.appendChild(item);
        });
      }
    }

    // Journal
    if (journalText && data.journal) {
      journalText.textContent = data.journal;
    }
  } catch (e) {
    console.error('Error fetching memory:', e);
  }
}

// Audio Visualizer Canvas
const canvas = document.getElementById('waveformCanvas');
const ctx = canvas ? canvas.getContext('2d') : null;
let liveAudioLevel = 0.0;
let isUserSpeaking = false;
let isVoiceListening = false;
let isHoldingSpace = false;
let spacePressStartTime = 0;

function drawVisualizer() {
  if (!canvas || !ctx) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const time = Date.now() * 0.003;
  const bars = 40;
  const barWidth = canvas.width / bars;
  const radius = 2;

  for (let i = 0; i < bars; i++) {
    let height = 4;
    let color = 'rgba(0, 240, 255, 0.35)';

    if (currentState === 'listening') {
      const amp = Math.max(0.12, liveAudioLevel);
      height = 5 + (Math.sin(time * 4 + i * 0.4) * 12 + Math.random() * 6) * (amp * 3.5);
      color = isUserSpeaking ? '#10b981' : '#f59e0b';
    } else if (currentState === 'thinking') {
      height = 6 + Math.cos(time * 5 + i * 0.25) * 14;
      color = '#8b5cf6';
    } else if (currentState === 'speaking') {
      height = 8 + Math.sin(time * 4 + i * 0.5) * 20 + Math.random() * 8;
      color = '#10b981';
    } else {
      // Idle gentle wave
      height = 4 + Math.sin(time + i * 0.3) * 6;
      color = 'rgba(0, 240, 255, 0.3)';
    }

    height = Math.max(3, Math.min(canvas.height - 4, height));
    const x = i * barWidth;
    const y = (canvas.height - height) / 2;

    ctx.fillStyle = color;
    // Draw rounded bar
    if (ctx.roundRect) {
      ctx.beginPath();
      ctx.roundRect(x + 2, y, barWidth - 4, height, radius);
      ctx.fill();
    } else {
      ctx.fillRect(x + 2, y, barWidth - 4, height);
    }
  }

  requestAnimationFrame(drawVisualizer);
}
if (canvas && ctx) {
  drawVisualizer();
}

// Send Directive via Text
async function executeDirective(cmd) {
  if (!cmd || !cmd.trim()) return;
  const text = cmd.trim();
  if (commandInput) commandInput.value = '';
  addLog('user', text);
  appendChatMessage('you', text, 'user');
  setReactorState('thinking');

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, mute: isMuted })
    });
    const result = await res.json();
    setReactorState('idle');
    if (result.reply) {
      if (liveSpeechText) liveSpeechText.textContent = result.reply;
      addLog('vyra', result.reply);
      appendChatMessage('vyra', result.reply, 'vyra');
    }
    if (result.tools && result.tools.length > 0) {
      result.tools.forEach(t => {
        const msg = `[PROTOCOL] ${t.name}(${JSON.stringify(t.args)}) -> ${t.output}`;
        addLog('tool', msg);
        appendChatMessage('directive', `${t.name}: ${t.output}`, 'tool');
      });
    }
  } catch (err) {
    setReactorState('idle');
    addLog('system', `Error: ${err.message}`);
  }
}

// Voice Engine Controller
async function startVoiceListen() {
  if (isVoiceListening) return;
  isVoiceListening = true;
  liveAudioLevel = 0.0;
  isUserSpeaking = false;
  setReactorState('listening');
  addLog('system', 'Voice input channel activated.');

  try {
    const res = await fetch('/api/voice/listen', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mute: isMuted })
    });
    const result = await res.json();
    setReactorState('idle');
    isVoiceListening = false;
    liveAudioLevel = 0.0;
    isUserSpeaking = false;

    if (result.heard) {
      addLog('user', result.heard);
      appendChatMessage('you', result.heard, 'user');
    }
    if (result.reply) {
      if (liveSpeechText) liveSpeechText.textContent = result.reply;
      addLog('vyra', result.reply);
      appendChatMessage('vyra', result.reply, 'vyra');
    }
  } catch (err) {
    setReactorState('idle');
    isVoiceListening = false;
    liveAudioLevel = 0.0;
    isUserSpeaking = false;
    addLog('system', `Voice input ended: ${err.message}`);
  }
}

async function stopVoiceListen() {
  if (!isVoiceListening) return;
  try {
    await fetch('/api/voice/stop', { method: 'POST' });
  } catch (err) {}
}

async function toggleVoice() {
  if (isVoiceListening) {
    await stopVoiceListen();
  } else {
    await startVoiceListen();
  }
}

// Input Event Handlers
if (sendBtn && commandInput) {
  sendBtn.addEventListener('click', () => executeDirective(commandInput.value));
  commandInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      executeDirective(commandInput.value);
    }
  });
}

// Core and Mic button clicks
if (coreReactor) coreReactor.addEventListener('click', toggleVoice);
if (micToggleBtn) micToggleBtn.addEventListener('click', toggleVoice);

// Spacebar Push-To-Talk & Hold-To-Talk
window.addEventListener('keydown', (e) => {
  if (e.code === 'Space' && (!commandInput || document.activeElement !== commandInput)) {
    e.preventDefault();
    if (e.repeat) return;
    if (!isHoldingSpace) {
      isHoldingSpace = true;
      spacePressStartTime = Date.now();
      if (!isVoiceListening) {
        startVoiceListen();
      } else {
        stopVoiceListen();
      }
    }
  }
});

window.addEventListener('keyup', (e) => {
  if (e.code === 'Space' && (!commandInput || document.activeElement !== commandInput)) {
    if (isHoldingSpace) {
      const duration = Date.now() - spacePressStartTime;
      isHoldingSpace = false;
      if (duration > 400 && isVoiceListening) {
        stopVoiceListen();
      }
    }
  }
});

// Quick Protocol buttons
document.querySelectorAll('.proto-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const cmd = btn.getAttribute('data-cmd');
    if (cmd) executeDirective(cmd);
  });
});

// Mute toggle with SVG preservation
if (muteBtn) {
  muteBtn.addEventListener('click', () => {
    isMuted = !isMuted;
    muteBtn.innerHTML = isMuted ? MUTE_ON_SVG : MUTE_OFF_SVG;
    muteBtn.classList.toggle('active', isMuted);
    addLog('system', isMuted ? 'Voice feedback muted.' : 'Voice feedback active.');
  });
}

// Wake Word Toggle
if (wakeToggleBtn) {
  wakeToggleBtn.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/voice/wake/toggle', { method: 'POST' });
      const d = await res.json();
      updateWakeUI(d.wake_enabled);
    } catch (err) {
      console.error('Failed to toggle wake state:', err);
    }
  });
}

function updateWakeUI(enabled) {
  isWakeEnabled = enabled;
  if (!wakeToggleBtn) return;
  if (enabled) {
    wakeToggleBtn.classList.add('active');
    if (wakeStatusText) wakeStatusText.textContent = 'WAKE: FRIDAY [ON]';
  } else {
    wakeToggleBtn.classList.remove('active');
    if (wakeStatusText) wakeStatusText.textContent = 'WAKE: [OFF]';
  }
  if (currentState === 'idle' && reactorHint) {
    reactorHint.textContent = isWakeEnabled
      ? '[SAY "FRIDAY" / "BUDDY" // OR PRESS SPACE]'
      : '[CLICK CORE OR PRESS SPACE TO TRANSMIT]';
  }
}

// PiP Quick Chips
document.querySelectorAll('.pip-chip').forEach(btn => {
  btn.addEventListener('click', () => {
    const cmd = btn.getAttribute('data-cmd');
    if (cmd) executeDirective(cmd);
  });
});

// Window controls & PiP Mode
const pinBtn = document.getElementById('pinBtn');
const modeToggleBtn = document.getElementById('modeToggleBtn');
const drawerToggleBtn = document.getElementById('drawerToggleBtn');
const closeDrawerBtn = document.getElementById('closeDrawerBtn');
const minBtn = document.getElementById('minBtn');
const closeBtn = document.getElementById('closeBtn');
const hudDrawer = document.getElementById('hudDrawer');
const autostartToggle = document.getElementById('autostartToggle');

let isPipMode = true;
if (modeToggleBtn) {
  modeToggleBtn.addEventListener('click', async () => {
    isPipMode = !isPipMode;
    document.body.classList.toggle('pip-mode', isPipMode);
    modeToggleBtn.innerHTML = isPipMode ? PIP_EXPAND_SVG : PIP_SHRINK_SVG;
    modeToggleBtn.title = isPipMode ? 'Expand to Full Command Deck' : 'Shrink to Corner PiP Widget';
    if (window.pywebview && window.pywebview.api && window.pywebview.api.toggle_mode) {
      window.pywebview.api.toggle_mode();
    } else {
      fetch('/api/window/mode', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ mode: isPipMode ? 'pip' : 'full' })
      }).catch(() => {});
    }
  });
}

let isPinned = true;
if (pinBtn) {
  pinBtn.addEventListener('click', async () => {
    isPinned = !isPinned;
    pinBtn.classList.toggle('active', isPinned);
    if (window.pywebview && window.pywebview.api && window.pywebview.api.toggle_pin) {
      window.pywebview.api.toggle_pin();
    } else {
      fetch('/api/window/pin', { method: 'POST' }).catch(() => {});
    }
  });
}

if (minBtn) {
  minBtn.addEventListener('click', () => {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.minimize) {
      window.pywebview.api.minimize();
    } else {
      fetch('/api/window/minimize', { method: 'POST' }).catch(() => {});
    }
  });
}

if (closeBtn) {
  closeBtn.addEventListener('click', () => {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.close) {
      window.pywebview.api.close();
    } else {
      fetch('/api/window/close', { method: 'POST' }).catch(() => {});
    }
  });
}

// Drawer Toggle
if (drawerToggleBtn && hudDrawer) {
  drawerToggleBtn.addEventListener('click', () => {
    hudDrawer.classList.toggle('open');
  });
}
if (closeDrawerBtn && hudDrawer) {
  closeDrawerBtn.addEventListener('click', () => {
    hudDrawer.classList.remove('open');
  });
}

// Drawer Tabs
const drawerLogsTab = document.getElementById('drawerLogsTab');
const drawerStatsTab = document.getElementById('drawerStatsTab');
const drawerMemoryTab = document.getElementById('drawerMemoryTab');
const drawerLogsContent = document.getElementById('drawerLogsContent');
const drawerStatsContent = document.getElementById('drawerStatsContent');
const drawerMemoryContent = document.getElementById('drawerMemoryContent');

if (drawerLogsTab) {
  drawerLogsTab.addEventListener('click', () => {
    drawerLogsTab.classList.add('active'); drawerStatsTab.classList.remove('active'); drawerMemoryTab.classList.remove('active');
    drawerLogsContent.classList.add('active'); drawerStatsContent.classList.remove('active'); drawerMemoryContent.classList.remove('active');
  });
  drawerStatsTab.addEventListener('click', () => {
    drawerStatsTab.classList.add('active'); drawerLogsTab.classList.remove('active'); drawerMemoryTab.classList.remove('active');
    drawerStatsContent.classList.add('active'); drawerLogsContent.classList.remove('active'); drawerMemoryContent.classList.remove('active');
  });
  drawerMemoryTab.addEventListener('click', () => {
    drawerMemoryTab.classList.add('active'); drawerLogsTab.classList.remove('active'); drawerStatsTab.classList.remove('active');
    drawerMemoryContent.classList.add('active'); drawerLogsContent.classList.remove('active'); drawerStatsContent.classList.remove('active');
  });
}

// Autostart on boot checkbox
async function loadAutostartStatus() {
  if (!autostartToggle) return;
  try {
    const res = await fetch('/api/autostart');
    const d = await res.json();
    autostartToggle.checked = !!d.enabled;
  } catch (err) {}
}

if (autostartToggle) {
  autostartToggle.addEventListener('change', async () => {
    try {
      const res = await fetch('/api/autostart/toggle', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ enabled: autostartToggle.checked })
      });
      const d = await res.json();
      addLog('system', d.enabled ? 'Auto-start enabled for Windows boot.' : 'Auto-start disabled.');
    } catch (err) {
      console.error('Failed to toggle autostart:', err);
    }
  });
}

// Initial Boot Sequence
connectWebSocket();
fetchMemory();
loadAutostartStatus();
