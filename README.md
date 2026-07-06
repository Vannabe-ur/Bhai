# BHAI IRRFAN — Local AI Task Agent
> Draggable terminal HUD · Real-time clock · Google Calendar · AI voice agent · Deadline alerts

---

## 📁 Project Structure

```
bhai-irrfan/
├── backend/
│   └── main.py              ← FastAPI server (tasks, AI, TTS, calendar)
├── frontend/
│   └── index.html           ← The HUD (drag anywhere on screen)
├── desktop_app.py           ← Small always-on-top desktop window launcher
├── credentials/             ← Auto-created — put Google JSON here
│   ├── google_credentials.json   ← Download from Google Cloud Console
│   └── token.pickle         ← Auto-generated after first auth
├── voice/
│   └── irrfan_sample.wav    ← Drop 10–30s WAV here for voice cloning
├── data/
│   └── tasks.json           ← Auto-saved tasks
├── notebooks/
│   ├── voice
|   │   ├── dataset/
|   │   ├── result /
|   │   └── saved_model/
│   ├── tts_notebook.ipynb
│   └── tts_server.py                
├── requirements.txt
├── env.       ← saving GEMENI_KEY
├── start_windows.bat
└── start_mac_linux.sh
```

---

## ⚡ Quick Start

### Step 1 — Gemini API key
1. Go to google console https://console.cloud.google.com
2. Create an API key
3. Keep it ready (we'll paste it on first run)

### Step 2 — Set up Google Calendar (optional but recommended)
1. Go to https://console.cloud.google.com
2. Create a project → Enable **Google Calendar API**
3. Go to **Credentials** → Create **OAuth 2.0 Client ID** (Desktop App)
4. Download the JSON → rename to `google_credentials.json`
5. Place it in the `credentials/` folder
6. Click **[SYNC]** in the HUD to authorize

### Step 3 — Voice cloning (optional)
1. Record a 10–30 second clean WAV of the voice you want
2. Name it `irrfan_sample.wav`
3. Place it in the `voice/` folder or upload it from the HUD with **TRAIN VOICE**
4. Install Coqui TTS: `pip install TTS`
5. Restart the server — Irrfan will now speak in that voice

### Step 4 — Launch

**Windows:**
```
double-click start_windows.bat
```

**Mac / Linux:**
```bash
chmod +x start_mac_linux.sh
./start_mac_linux.sh
```

The desktop HUD opens automatically. If your system cannot load `pywebview`, it falls back to the browser at http://localhost:8000

---

## 🎮 Features

| Feature | Details |
|---|---|
| **Drag HUD** | Grab the green title bar — move anywhere |
| **Pop / compact mode** | Shrinks the HUD into a small desktop widget |
| **Real-time clock** | Live HH:MM:SS + day/date |
| **Uptime timer** | Counts from system boot of the page |
| **Tasks** | Add with deadline, color-coded urgency |
| **Deadline alerts** | Banner + voice alert when overdue |
| **Gmail Calendar** | Today's events pulled via Google API |
| **AI agent** | Ask Irrfan anything about tasks |
| **Persistent tasks** | Saved in `data/tasks.json` |

---

## 🔊 TTS Options (in priority order)

1. **Coqui XTTS-v2** (best) — voice cloning from your WAV sample
   - `pip install TTS` (~4GB, needs 8GB RAM)
2. **Coqui default voice** — no sample needed, just install TTS
3. **pyttsx3** — lightweight, no internet, system voice
4. **Browser speech** — fallback if backend TTS fails

---

## 💬 What to ask Irrfan

- "What do I have today?"
- "What's overdue?"
- "How many tasks are left?"
- "Remind me about the meeting"
- "Am I on track?"
- "Motivate me Bhai"

---

## 🔧 Environment Variables

```bash
GEMINI_API_KEY=your-key-here   # required for AI chat
```

Set in your shell, `.env` file, or paste when prompted on first run.

---

## 🛠 Troubleshooting

**Backend won't start**
→ Check Python version is 3.10+: `python --version`

**TTS not working**
→ Backend still speaks via browser fallback (no error needed)

**Calendar shows error**
→ Run `http://localhost:8000/calendar/auth` to re-authenticate

**Voice cloning sounds wrong**
→ Use a clean recording, 16kHz+ mono WAV, 15–30 seconds is ideal

**Port already in use**
→ The backend now handles TTS itself on port 8000, so no external 8001 service is required.

---

## 📦 Running projects


- Step 1: git clone repo and install dependencies 

```
pip intall -r requirements.txt
```

- Step 2: activate `tts_server.py`

```
python notebooks/tts_server.py
```

- Step 3: run api

```
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

- Step 4: run desktop app

```
python desktop_app.py
```
