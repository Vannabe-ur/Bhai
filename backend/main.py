"""
Bhai Irrfan — Main Backend (port 8000)
Handles: tasks, chat (Gemini), Google Calendar
Does NOT handle TTS — that lives in notebooks/tts_server.py (port 8001)
"""

import os, json, re, asyncio, threading, io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ── Google Calendar ───────────────────────────────────────────
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle

# ── Google Gemini ─────────────────────────────────────────────
#import google.generativeai as genai
from google import genai
from google.genai import types

# ── TTS microservice client ───────────────────────────────────
import httpx

TTS_SERVICE = "http://127.0.0.1:8001"   # tts_server.py lives here

# ─────────────────────────────────────────────────────────────

app = FastAPI(title="Bhai Irrfan API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Paths ─────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent
DATA_DIR   = BASE_DIR / "data"
CREDS_FILE = BASE_DIR / "credentials" / "google_credentials.json"
TOKEN_FILE = BASE_DIR / "credentials" / "token.pickle"
TASKS_FILE = DATA_DIR / "tasks.json"

for d in [DATA_DIR, BASE_DIR / "credentials"]:
    d.mkdir(parents=True, exist_ok=True)

SCOPES      = ["https://www.googleapis.com/auth/calendar.readonly"]
GEMINI_KEY  = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL= os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _parse_datetime(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


# ── Tasks ─────────────────────────────────────────────────────
DONE_TTL_SECONDS = 120

def prune_finished_tasks(tasks):
    now     = datetime.now()
    kept    = []
    changed = False
    for task in tasks:
        if task.get("done"):
            done_at = task.get("completed_at")
            if done_at:
                try:
                    parsed = _parse_datetime(done_at)
                    if parsed is None:
                        raise ValueError("missing")
                    age = now - parsed
                    if age.total_seconds() >= DONE_TTL_SECONDS:
                        changed = True
                        continue
                except (ValueError, TypeError):
                    task["completed_at"] = now.isoformat()
                    changed = True
            else:
                task["completed_at"] = now.isoformat()
                changed = True
        else:
            if task.get("completed_at") is not None:
                task["completed_at"] = None
                changed = True
        kept.append(task)
    return kept, changed

def load_tasks():
    if TASKS_FILE.exists():
        tasks = json.loads(TASKS_FILE.read_text())
        tasks, changed = prune_finished_tasks(tasks)
        if changed:
            save_tasks(tasks)
        return tasks
    return []

def save_tasks(tasks):
    TASKS_FILE.write_text(json.dumps(tasks, indent=2))


# ── Google Calendar ───────────────────────────────────────────
def get_calendar_service():
    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS_FILE.exists():
                raise HTTPException(503, "Google credentials not found.")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return build("calendar", "v3", credentials=creds)


# ── Gemini system prompt ──────────────────────────────────────
def build_system_prompt(tasks, calendar_events=None):
    now     = datetime.now().strftime("%A %d %B %Y, %H:%M")
    pending = [t for t in tasks if not t.get("done")]
    overdue = [t for t in pending if t.get("deadline") and
               datetime.fromisoformat(t["deadline"]) < datetime.now()]

    cal_str = ""
    if calendar_events:
        cal_str = "\n\nGMAIL CALENDAR TODAY:\n" + "\n".join(
            f"- {e['summary']} at {e['start']}" for e in calendar_events
        )

    return f"""
You are Bhai Irrfan — channeling the spirit of great Bollywood actor Irrfan Khan.
A sharp, loyal, slightly sarcastic AI task agent and life companion.
You speak like a knowledgeable wise man, uncle, best friend who knows tech.
Direct, warm, never verbose. Max 3 sentences per reply unless listing tasks.
You may use "Janu", "Golu" or "Chiku" as casual address.
Respond entirely in English — switch to Hindi, Urdu, or Urdu poetry only
for sweet, funny, or poetic moments, not regularly.
You know I love Qawwali (NFAK, Fareed Ayaz), Ghazals (Jagjit & Chitra Singh),
Rajasthani music, and Bollywood. My favorite film is The Lunchbox (2013).
Encourage me to learn by pointing to sources rather than giving full answers.
Support me mentally above all. No markdown. No bullet symbols.

CURRENT TIME: {now}
PENDING TASKS: {len(pending)} ({len(overdue)} overdue)
TASKS: {json.dumps(pending)}{cal_str}

When asked about tasks, read them conversationally.
When something is overdue, be dramatic about it.
When all is clear, be encouraging.
"""


# ═══════════════════════════════════════════════════════════════
# REQUEST MODELS
# ═══════════════════════════════════════════════════════════════

class ChatMessage(BaseModel):
    message: str
    history: list = []

class Task(BaseModel):
    id:           Optional[int] = None
    title:        str
    deadline:     Optional[str] = None
    done:         bool = False
    notes:        Optional[str] = None
    completed_at: Optional[str] = None

class SpeakRequest(BaseModel):
    text:         str
    message_type: str = "normal"   # normal | greeting | alert | done


# ═══════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════

# ── Health ────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """Check status of this backend + TTS microservice."""
    tts_status  = "offline"
    voice_clone = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{TTS_SERVICE}/health")
            d = r.json()
            if d.get("ready"):
                tts_status  = "coqui-xtts"
                voice_clone = d.get("voice_clone", False)
            else:
                tts_status  = "loading"
    except Exception:
        tts_status = "offline"

    return {
        "status":      "online",
        "tts":         tts_status,
        "voice_clone": voice_clone,
        "calendar":    TOKEN_FILE.exists(),
        "gemini":      bool(GEMINI_KEY),
    }


# ── Tasks ─────────────────────────────────────────────────────
@app.get("/tasks")
def get_tasks():
    return load_tasks()

@app.post("/tasks")
def create_task(task: Task):
    tasks   = load_tasks()
    task.id = int(datetime.now().timestamp() * 1000)
    if task.done and not task.completed_at:
        task.completed_at = datetime.now().isoformat()
    tasks.append(task.dict())
    save_tasks(tasks)
    return task

@app.put("/tasks/{task_id}")
def update_task(task_id: int, task: Task):
    tasks = load_tasks()
    for i, t in enumerate(tasks):
        if t["id"] == task_id:
            updated = {**t, **task.dict(), "id": task_id}
            updated["completed_at"] = (
                updated.get("completed_at") or datetime.now().isoformat()
                if updated.get("done") else None
            )
            tasks[i] = updated
            save_tasks(tasks)
            return tasks[i]
    raise HTTPException(404, "Task not found")

@app.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    tasks = [t for t in load_tasks() if t["id"] != task_id]
    save_tasks(tasks)
    return {"ok": True}


# ── Calendar ──────────────────────────────────────────────────
@app.get("/calendar/today")
def get_today_events():
    try:
        service = get_calendar_service()
        now_iso = datetime.utcnow().isoformat() + "Z"
        end_iso = (datetime.utcnow() + timedelta(days=1)).isoformat() + "Z"
        result  = service.events().list(
            calendarId="primary",
            timeMin=now_iso, timeMax=end_iso,
            maxResults=20, singleEvents=True, orderBy="startTime",
        ).execute()
        events = []
        for e in result.get("items", []):
            start = e["start"].get("dateTime", e["start"].get("date", ""))
            if "T" in start:
                start = datetime.fromisoformat(start.replace("Z", "")).strftime("%H:%M")
            events.append({"summary": e.get("summary", "(no title)"), "start": start})
        return events
    except Exception as ex:
        print(f"⚠ Calendar error: {ex}")
        return {"error": str(ex), "events": []}

@app.get("/calendar/auth")
def trigger_auth():
    try:
        get_calendar_service()
        return {"status": "authenticated"}
    except Exception as ex:
        raise HTTPException(500, str(ex))


# ── Chat ──────────────────────────────────────────────────────
@app.post("/chat")
async def chat(req: ChatMessage):
    if not GEMINI_KEY:
        raise HTTPException(503, "GEMINI_API_KEY not set — add it to .env")

    tasks    = load_tasks()
    calendar = []
    try:
        result   = get_today_events() if TOKEN_FILE.exists() else []
        calendar = result if isinstance(result, list) else []
    except Exception as ex:
        print(f"⚠ Calendar fetch failed in chat: {ex}")

    # ── DEBUG: print what we're sending ───────────────────────
    # Add inside /chat route, just before client.models.generate_content(...)
    print("\n" + "="*60)
    print(f"MESSAGE: {req.message}")
    print(f"HISTORY ITEMS: {len(req.history)}")
    for i, h in enumerate(req.history):
        if isinstance(h, dict):
            print(f"  [{i}] {h.get('role')}: {str(h.get('content',''))[:80]}")
        else:
            print(f"  [{i}] RAW: {str(h)[:80]}")
    print("="*60)
    # ──────────────────────────────────────────────────────────

    client = genai.Client(api_key=GEMINI_KEY)

    history = []
    for msg in req.history[-10:]:
        history.append(types.Content(
            role="user" if msg["role"] == "user" else "model",
            parts=[types.Part(text=msg["content"])],
        ))

    history.append(types.Content(
        role="user",
        parts=[types.Part(text=req.message)],
    ))

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=history,
            config=types.GenerateContentConfig(
                system_instruction=build_system_prompt(tasks, calendar),
                max_output_tokens=300,
                temperature=0.8,
            ),
        )
        reply = response.text.strip()
    except Exception as ex:
        err = str(ex)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            raise HTTPException(429, "Bhai is resting — free tier limit hit. Try again in a minute.")
        elif "quota" in err.lower():
            raise HTTPException(429, "Daily quota exceeded — upgrade plan or wait until tomorrow.")
        else:
            raise HTTPException(500, f"Gemini error: {err}")

    return {"reply": reply}


# ── TTS — delegates to port 8001 ──────────────────────────────
@app.post("/speak")
async def speak(req: SpeakRequest):
    """
    Forward speech request to the TTS microservice (port 8001).
    tts_server.py handles model loading, voice cloning, and audio generation.
    This backend stays lightweight — no torch, no model, no blocking.
    """
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            r = await client.post(
                f"{TTS_SERVICE}/speak",
                json={"text": req.text, "message_type": req.message_type},
            )
            if r.status_code != 200:
                raise HTTPException(r.status_code, f"TTS service error: {r.text}")
            return StreamingResponse(
                io.BytesIO(r.content),
                media_type="audio/wav",
                headers={"Content-Disposition": "inline"},
            )
    except httpx.ConnectError:
        raise HTTPException(503, "TTS service offline — start notebooks/tts_server.py")
    except httpx.TimeoutException:
        raise HTTPException(504, "TTS generation timed out — CPU is slow, try shorter text")


# ── Serve frontend ────────────────────────────────────────────
frontend_dir = BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="static")