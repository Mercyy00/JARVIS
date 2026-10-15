# Rusty // Autonomous AI Operating System

A JARVIS-class personal AI assistant and desktop operating system for Windows — engineered for low-latency voice interaction, local whisper transcription, tactical holographic HUD telemetry, system automation, and cross-platform remote phone control.

---

## Architecture Overview

Rusty is built on an asynchronous, modular architecture separating the neural reasoning engine from machine automation and secure interfaces:

```
JARVIS/
├── main.py                     # Interactive terminal REPL
├── config.json                 # Core system configuration
├── requirements.txt            # Dependency specification
├── tests/                      # Automated test suite (32 unit tests)
│   ├── test_config.py          # Config merging and validation
│   ├── test_security.py        # Sandbox & credential protection gates
│   ├── test_memory.py          # Persistent memory and journal tests
│   ├── test_skills_registry.py # 75-skill schema and integrity tests
│   └── test_skills_system.py   # System automation and file tests
├── vyra/
│   ├── brain.py                # ReAct think-act loop & multi-hop tool execution
│   ├── config.py               # Layered configuration & environment parser
│   ├── gui_server.py           # Aiohttp HUD server & WebSocket bridge
│   ├── llm.py                  # Multi-provider client (Claude / Gemini / OpenRouter)
│   ├── memory.py               # Three-tier local persistent memory (JSON/MD)
│   ├── office_skills.py        # Comprehensive Office, PDF, PPTX & project generation
│   ├── remote_telegram.py      # Encrypted Telegram bot gateway (voice + commands)
│   ├── voice.py                # Local Faster-Whisper ASR + Neural Edge-TTS engine
│   ├── wake.py                 # Continuous passive wake word detection
│   └── skills/                 # Modular 75-Skill Dispatcher
│       ├── common.py           # Path resolution, security validation, Win32 desktop API
│       ├── system.py           # Terminal, window management, volume, hotkeys, input
│       ├── files.py            # File I/O, search, listing, and safe recycling
│       ├── browser.py          # Browser automation, tab control, web research, links
│       ├── media.py            # Raaga music app, audio controls, screen vision, screenshots
│       ├── comms.py            # Telegram file transfer, WhatsApp, Drive backup, GitHub CLI
│       └── assistant.py        # Memory facts, notes, reminders, routines, deep thinking
└── .github/workflows/
    └── ci.yml                  # Automated continuous integration workflow
```

---

## Core Capabilities (75 Registered Skills)

1. **Voice & Hearing Pipeline**:
   - Local, privacy-first transcription with **Faster-Whisper** (`small` model on NVIDIA CUDA with CPU fallback).
   - High-fidelity neural voice synthesis via Microsoft Edge-TTS with multi-lingual auto-switching (English + Hindi `hi-IN-MadhurNeural`).
   - Non-blocking continuous wake-word monitoring (`"Rusty"`, `"Friday"`, `"Jarvis"`).
2. **Tactical Holographic HUD (Stark Industries Interface)**:
   - High-FPS canvas-based Arc Reactor core, real-time audio spectrum, and live hardware telemetry (CPU, RAM, GPU, battery, ping).
   - Borderless desktop PiP application or browser view.
3. **Hardware & Desktop Automation**:
   - Win32 window enumeration, smart tab closing (`Ctrl+W`), process management, master volume control, screen brightness, and lock/sleep triggers.
4. **Autonomous Office & Document Generation**:
   - Generates fully populated, styled Word documents (`.docx`), presentation decks (`.pptx`), Excel sheets (`.xlsx`), and clean formatted PDFs (`reportlab`).
5. **Secure Remote Gateway (Phone Control)**:
   - Control your PC from anywhere in the world via Telegram with constant-time HMAC authentication, rate-limiting, and 15-minute brute-force lockout.
   - Send files from PC to phone with a single voice directive.

---

## Security Model & Hardening

Rusty enforces strict security boundaries designed for autonomous systems:
- **Sandbox Validation (`is_path_safe`)**: Blocks access, deletion, or exfiltration of system credentials, `.env`, `.ssh`, AWS keys, GPG keys, and browser session cookies.
- **Terminal Execution Gates**: Catastrophic disk and system commands (`bcdedit`, `bootrec`, `vssadmin`, `iex`, encoded payloads) are blocked at the regex parsing layer. Destructive operations (`rmdir`, `del`, `taskkill /f`, `git reset --hard`) require explicit `confirm=True` validation.
- **Localhost Default**: HUD server binds strictly to `127.0.0.1` by default.
- **HMAC Constant-Time PIN Verification**: Protects against timing attacks on remote endpoints.

---

## Quickstart

### 1. Requirements & Setup
Ensure Python 3.10+ (Python 3.12 recommended) is installed:

```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Copy configuration templates and specify your LLM key:

```bash
copy config.example.json config.json
copy .env.example .env
```

Edit `.env`:
```env
VYRA_API_KEY=your_gemini_or_claude_api_key
```

### 3. Launch Rusty

- **Tactical Desktop HUD**:
  ```bash
  .\launch_rusty.bat
  # or: python -m vyra.gui_server
  ```
- **Text Command REPL**:
  ```bash
  python main.py
  ```

---

## Automated Test Suite

Rusty includes a comprehensive 32-test unit testing suite verifying configuration parsing, security boundaries, memory persistence, schema validity, and tool dispatch:

```bash
python -m unittest discover tests -v
```

All pull requests and pushes are automatically validated via GitHub Actions CI (`.github/workflows/ci.yml`).
