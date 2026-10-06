# VYRA

A JARVIS-style personal assistant for Windows — a buddy that knows you,
remembers your conversations, controls your laptop, and (soon) talks to you.

**Phase 1 is here:** a text brain with persistent memory and real skills.
Voice, full PC control, and browser automation come next.

## Setup

1. Install Python 3.10+ and the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Give VYRA a brain (an API key). Copy the examples and fill them in:

   ```bash
   copy config.example.json config.json
   copy .env.example .env
   ```

   Put your key in `.env`:

   ```
   VYRA_API_KEY=your-key-here
   ```

3. Run her:

   ```bash
   python main.py
   ```

## Choosing / switching the brain

Everything except the LLM is free. The brain is swappable — edit `config.json`:

```json
{
  "llm": { "provider": "claude", "model": "claude-sonnet-5-5" }
}
```

| provider     | model example                 | notes                                  |
|--------------|-------------------------------|----------------------------------------|
| `claude`     | `claude-sonnet-5-5`           | Recommended. Best reasoning/tool use.  |
| `openrouter` | `anthropic/claude-sonnet-5-5` | Many models, some free. Set your key.  |
| `google`     | `gemini-2.0-flash`            | Generous free tier.                    |

Switching providers = change `provider` + `model` and use that provider's key in
`.env`. No code changes. (Model ids drift over time — check the provider's docs
for the current name.)

## What VYRA can do now

- Open apps and folders (`downloads`, `documents`, a full path, …)
- Google search, open any URL, open YouTube (or search it)
- Save named links and reopen them — perfect for Google Meet links
- Remember lasting facts about you, keep notes, know the date/time

Just talk to her: *"save my standup meet as https://meet.google.com/xxx"*, then
later *"open my standup meet"*.

In-chat commands: `/name <you>`, `/links`, `/notes`, `/help`, `/bye`.

## Technical JARVIS HUD (GUI Mode)

Launch the futuristic Stark Industries holographic interface:

```bash
.\run_gui.bat
```

- **Holographic Arc Reactor Core**: Animated rotating HUD rings and pulsing reactor core indicating standby, listening, thinking, and speaking states.
- **Hardware & Telemetry**: Live CPU load, RAM usage, RTX 2050 GPU status, system chronometer, and neural latency.
- **Vocal & Text Interaction**: Click the reactor core or press **Spacebar** to speak, or type directives in the command bar.
- **Live Waveform & Logs**: Real-time audio waveform visualizer and monospace console logging all tool executions and responses.
- **Memory Vault**: Live dossier tab showing user profile facts, saved Google Meet links, and session journal records.

## Talk to her out loud (Voice Mode)

Install the audio extras once, then run the voice loop:

```bash
pip install -r requirements-voice.txt
python voice_chat.py
```

- Default is **push-to-talk**: press Enter, speak, and she replies in a British
  neural voice (`en-GB-RyanNeural`). First run downloads a small Whisper model.
- `python voice_chat.py --wake` is **always-listening**: start a command with
  "VYRA ..." and only then does she act.

Speech is transcribed locally (private); only the brain and the voice synthesis
go online.


## How she remembers

Stored as plain files under `data/` (gitignored, private to you):

- `profile.json` — long-term facts about you
- `links.json` — your saved named links
- `notes.json` — your notes
- `journal/` — a short summary of each session, so tomorrow she recalls today

## Project layout

```
JARVIS/
├── main.py            # the text REPL (Phase 1 entry point)
├── vyra/
│   ├── config.py      # config + env loading, provider swapping
│   ├── llm.py         # provider adapters (claude / openrouter / google)
│   ├── memory.py      # profile, links, notes, daily journal
│   ├── skills.py      # the things she can DO (open/search/save/remember)
│   └── brain.py       # personality + think->act loop
├── config.example.json
└── requirements.txt
```

## Roadmap

1. ✅ Text brain + memory + core skills (provider-swappable)
2. ✅ Voice — local Whisper ears + Edge-TTS voice + "VYRA" wake word *(untested; needs a mic)*
3. 🔜 Full PC control + Brave/YouTube/Meet + GUI automation
4. 🔜 Browser magic — image generation + driving other apps
5. 🔜 Autostart on logon
