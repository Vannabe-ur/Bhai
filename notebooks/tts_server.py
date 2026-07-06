"""
⚠ DEPRECATED — Do not use.

TTS has been integrated directly into backend/main.py on port 8000.
This file is kept for reference only.

Previous architecture (no longer used):
    main backend (8000) ──POST /speak──► tts_server (8001) ──► WAV bytes

New architecture (active):
    main backend (8000) directly handles /speak using XTTS-v2 model
    - Model loads on startup in background thread
    - No separate process needed
    - Single port for all APIs

To use TTS:
    1. Start backend: cd backend && python main.py
    2. POST to http://localhost:8000/speak with {"text": "..."}
    
Do not run this file.
"""

import asyncio
import io
import pickle
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import re
import soundfile as sf
import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import soundfile as _sf
import torch as _torch
import torchaudio

def _sf_load(filepath, frame_offset=0, num_frames=-1, normalize=True, channels_first=True, format=None, backend=None, encoding=None, bits_per_sample=None):
    data, sr = _sf.read(str(filepath), always_2d=True)
    tensor = _torch.tensor(data.T, dtype=_torch.float32)
    if normalize:
        if tensor.abs().max() > 1.0:
            tensor = tensor / tensor.abs().max()
    return tensor, sr

torchaudio.load = _sf_load

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
VOICE_DIR      = BASE_DIR / "voice"
DATASET_DIR    = VOICE_DIR / "dataset"
# Try merged sample first, fall back to single sample
SAMPLE_PATH    = DATASET_DIR / "irrfan_merged.wav" if (DATASET_DIR / "irrfan_merged.wav").exists() else VOICE_DIR / "irrfan_sample1.wav"
EMBEDDING_PATH = VOICE_DIR / "saved_model" / "speaker_embedding.pkl"


# Fallback to individual sample
if not SAMPLE_PATH.exists():
    for fallback in ["irrfan_sample1.wav", "irrfan_sample2.wav", "irrfan_sample3.wav"]:
        candidate = DATASET_DIR / fallback
        if candidate.exists():
            SAMPLE_PATH = candidate
            break
print(f"Voice sample: {SAMPLE_PATH}")
print(f"Embedding: {EMBEDDING_PATH}")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Bhai Irrfan TTS Service", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Model state ───────────────────────────────────────────────────────────────
_tts_model: object            = None
_gpt_cond_latent: object     = None
_speaker_embedding:object  = None
_model_lock      = threading.Lock()
_model_ready: bool         = False
_model_error: Optional[str] = None

SPEECH_SPEED = 1.2

def load_model() -> None:
    """Load XTTS-v2 and speaker embedding at startup. Runs in a background thread."""
    global _tts_model, _gpt_cond_latent, _speaker_embedding, _model_ready, _model_error

    try:
        print("⏳ Loading XTTS-v2 model (this takes 20-60s on CPU)...")

        # Patch torch.load for older TTS serialization
        _orig_load = torch.load
        def _safe_load(*args, **kwargs):
            kwargs.setdefault("weights_only", False)
            return _orig_load(*args, **kwargs)
        torch.load = _safe_load

        from TTS.api import TTS

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"   Device: {device}")

        with _model_lock:
            _tts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

        # Load pre-computed speaker embedding (from notebook Cell 4)
        if EMBEDDING_PATH.exists():
            print(">> Loading pre-computed speaker embedding...")
            with open(EMBEDDING_PATH, "rb") as f:
                data = pickle.load(f)
            if isinstance(data, dict):
                _gpt_cond_latent   = data.get("gpt_cond_latent")
                _speaker_embedding = data.get("speaker_embedding")
            else:
                _gpt_cond_latent, _speaker_embedding = data
            
            print(">> Speaker embedding loaded — voice clone ready")

        elif SAMPLE_PATH.exists():
            # Fallback: compute embedding on the fly from sample WAV
            print("⚠  No pre-computed embedding found — computing from sample WAV...")
            print("   (Run notebook Cell 4 to pre-compute and speed up future starts)")
            with _model_lock:
                _gpt_cond_latent, _speaker_embedding = (
                    _tts_model.synthesizer.tts_model.get_conditioning_latents(
                        audio_path=[str(SAMPLE_PATH)],
                        gpt_cond_len=30,
                        gpt_cond_chunk_len=4,
                        max_ref_length=120,
                    )
                )
            print(">> Speaker embedding computed from sample")

        else:
            print("⚠  No voice sample or embedding found.")
            print(f"   Put irrfan_sample.wav in: {VOICE_DIR}")
            print("   TTS will use XTTS default voice until a sample is provided.")

        _model_ready = True
        print(">> TTS microservice ready on http://localhost:8001")

    except Exception as e:
        _model_error = str(e)
        print(f">> TTS model failed to load: {e}")

# ── Text maturalizer ─────────────────────────────────────────────────────────────
def make_natural(text: str, message_type:str = "normal") -> str:
    """
    Add prosody hints to text so XTTS sounds more natural.
    """
    if message_type == "greeting":
        text = text.replace("Good morning, beti", "Aree... good morning")
        text = text.replace("Good afternoon, beti", "Aree... good afternoon")
        text = text.replace("Good evening, beti", "Aree... good evening")

    if message_type == "alert":
        text = text.replace("overdue", "OVERDUE")
        text = text.replace("Alert", "Aree yaar — ALERT")
        text = re.sub(r'(\d+)\s+(task)', r'\1...\2', text)
    
    if message_type == "done":
        text = text.replace("completed", "completed — nice!")
        text = text.replace("Done", "Done! Aree — good job, beti")

    # universal: pad numbers with pause
    text = re.sub(r'(\d+)\s+(task)', r'\1...\2', text)

    # universal: soften question marks
    text = re.sub(r'\?', '...?', text)

    return text

# ── Request model ─────────────────────────────────────────────────────────────
class SpeakRequest(BaseModel):
    text: str
    language: str = "en"
    message_type:str = "normal"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Main backend polls this to decide whether TTS is available."""
    return {
        "ready":            _model_ready,
        "error":            _model_error,
        "voice_clone":      _speaker_embedding is not None,
        "sample_exists":    SAMPLE_PATH.exists(),
        "embedding_exists": EMBEDDING_PATH.exists(),
        "device":           "cuda" if torch.cuda.is_available() else "cpu",
        "speed": SPEECH_SPEED,
    }


@app.post("/speak")
async def speak(req: SpeakRequest):
    """
    Generate speech WAV in the cloned voice.
    Returns raw WAV bytes — main backend streams these directly to the frontend.

    Async: the actual generation runs in a thread pool so FastAPI stays
    responsive while XTTS crunches on CPU (which blocks the GIL).
    """
    if not _model_ready:
        if _model_error:
            raise HTTPException(503, f"TTS model failed to load: {_model_error}")
        raise HTTPException(503, "TTS model still loading — try again in a moment")
    
    text = make_natural(req.text.strip()[:400], req.message_type)
    if not req.text.strip():
        raise HTTPException(400, "text field is empty")

    # Cap length — very long text causes OOM on CPU
    #text = req.text.strip()[:400]

    def _generate() -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            model = _tts_model.synthesizer.tts_model
            model.eval()

            with _model_lock:
                with torch.no_grad():
                    out = model.inference(
                        text=text,
                        language=req.language,
                        gpt_cond_latent=_gpt_cond_latent,
                        speaker_embedding=_speaker_embedding,
                        speed=SPEECH_SPEED,
                        temperature=0.7,
                        repetition_penalty=10.0,
                        top_k=50,
                        top_p=0.85,
                    )
            sf.write(str(tmp_path), out["wav"], 24000)
            return tmp_path.read_bytes()
        finally:
            tmp_path.unlink(missing_ok=True)

    # Run blocking generation in thread pool — keeps the event loop free
    loop = asyncio.get_event_loop()
    wav_bytes = await loop.run_in_executor(None, _generate)

    return StreamingResponse(
        io.BytesIO(wav_bytes),
        media_type="audio/wav",
        headers={"Content-Disposition": "inline", "X-Generated-At": datetime.now().isoformat()},
    )


# @app.get("/voice/status")
# def voice_status():
#     """Detailed status for debugging from the notebook or curl."""
#     return {
#         "model_ready":       _model_ready,
#         "model_error":       _model_error,
#         "voice_clone_ready": _speaker_embedding is not None,
#         "sample_path":       str(SAMPLE_PATH),
#         "sample_exists":     SAMPLE_PATH.exists(),
#         "embedding_path":    str(EMBEDDING_PATH),
#         "embedding_exists":  EMBEDDING_PATH.exists(),
#     }


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    """Load model in background so server starts instantly and accepts /health checks."""
    thread = threading.Thread(target=load_model, daemon=True)
    thread.start()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Starting Bhai Irrfan TTS microservice on port 8001...")
    print(f"Voice sample : {SAMPLE_PATH}")
    print(f"Embedding    : {EMBEDDING_PATH}")
    print()
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")