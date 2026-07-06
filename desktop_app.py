"""
Bhai Irrfan — Desktop launcher
Starts BOTH servers silently, then opens the UI.

  Port 8000 — main backend  (tasks, chat, calendar)
  Port 8001 — TTS server    (voice cloning, speech)
"""

from __future__ import annotations
import os, signal, subprocess, sys, threading, time
from pathlib import Path

URL          = "http://127.0.0.1:8000"
BASE_DIR     = Path(__file__).parent
BACKEND_DIR  = BASE_DIR / "backend"
NOTEBOOKS_DIR= BASE_DIR / "notebooks"


def _load_env() -> dict:
    """Read .env into a dict to pass to subprocesses."""
    env = os.environ.copy()
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _no_window() -> dict:
    """Windows-only: hide console window for subprocess."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


def start_backend(env: dict) -> subprocess.Popen | None:
    """Start main FastAPI backend on port 8000."""
    main_py = BACKEND_DIR / "main.py"
    if not main_py.exists():
        print(f"⚠  backend/main.py not found")
        return None
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", "8000", "--log-level", "warning"],
        cwd=str(BACKEND_DIR), env=env, **_no_window()
    )


def start_tts(env: dict) -> subprocess.Popen | None:
    """Start TTS microservice on port 8001."""
    tts_py = NOTEBOOKS_DIR / "tts_server.py"
    if not tts_py.exists():
        print(f"⚠  notebooks/tts_server.py not found — voice will be silent")
        return None
    return subprocess.Popen(
        [sys.executable, str(tts_py)],
        cwd=str(NOTEBOOKS_DIR), env=env, **_no_window()
    )


def wait_for(url: str, timeout: int = 20) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def start_tray(procs: list) -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (64, 64), "#0a0a0a")
        d = ImageDraw.Draw(img)
        d.rectangle([12,12,52,52], fill="#00ff41")
        d.rectangle([20,20,44,44], fill="#0a0a0a")
        d.rectangle([26,26,38,38], fill="#00ff41")

        def on_quit(icon, _):
            icon.stop()
            for p in procs:
                if p and p.poll() is None:
                    p.terminate()
            sys.exit(0)

        pystray.Icon("BhaiIrrfan", img, "Bhai Irrfan",
            menu=pystray.Menu(
                pystray.MenuItem("Bhai Irrfan v1.0", lambda *_: None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", on_quit),
            )
        ).run()
    except Exception as e:
        print(f"⚠  Tray unavailable: {e}")


def main() -> None:
    env = _load_env()

    # Start both servers
    print("Starting main backend (port 8000)...")
    main_proc = start_backend(env)

    print("Starting TTS server (port 8001)...")
    tts_proc = start_tts(env)

    # Wait for main backend (required before UI opens)
    if not wait_for("http://127.0.0.1:8000/health", timeout=20):
        print("⚠  Main backend didn't start in time")

    # TTS loads in background — UI opens while XTTS model loads
    # The frontend's /health polling will show "TTS: loading" until ready
    print("✅ Backend ready — opening UI")
    print("⏳ TTS voice loading in background (30-60s on CPU)...")

    # System tray (handles both processes on quit)
    procs = [p for p in [main_proc, tts_proc] if p]
    threading.Thread(target=start_tray, args=(procs,), daemon=True).start()

    # Open PyWebView
    try:
        import webview
        try:
            webview.create_window(
                "Bhai Irrfan", URL,
                width=380, height=720,
                resizable=False, frameless=True,
            )
        except TypeError:
            webview.create_window("Bhai Irrfan", URL, width=380, height=720)
        webview.start(debug=False)
    except ImportError:
        import webbrowser
        webbrowser.open(URL)

    # Cleanup on window close
    for p in procs:
        if p and p.poll() is None:
            p.terminate()


if __name__ == "__main__":
    main()