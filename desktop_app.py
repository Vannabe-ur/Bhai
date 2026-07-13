"""
Bhai Irrfan — Desktop Launcher
Starts backend (8000) + TTS (8001) silently, opens frameless transparent UI.
Right-click system tray → Quit / Restart Voice / Show Window
"""

from __future__ import annotations
import os, signal, subprocess, sys, threading, time
from pathlib import Path

URL           = "http://127.0.0.1:8000"   # FastAPI serves frontend/index.html here
BASE_DIR      = Path(__file__).parent
BACKEND_DIR   = BASE_DIR / "backend"
NOTEBOOKS_DIR = BASE_DIR / "notebooks"

class Api:
    def __init__(self):
        self._window = None

    def set_window(self, window):
        self._window = window

    def resize_to_content(self, height: int):
        """Called from JS when content height changes"""
        if self._window:
            new_height = max(300, min(int(height) + 2, 1000))
            self._window.resize(420, new_height)

# ── Environment ───────────────────────────────────────────────
def _load_env() -> dict:
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
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


# ── Server launchers ──────────────────────────────────────────
def start_backend(env: dict) -> subprocess.Popen | None:
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
    tts_py = NOTEBOOKS_DIR / "tts_server.py"
    if not tts_py.exists():
        print(f"⚠  notebooks/tts_server.py not found — voice silent")
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


# ── System tray ───────────────────────────────────────────────
def start_tray(procs: list, window=None) -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw

        # Green terminal icon — transparent background
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle([12, 12, 52, 52], fill="#00ff41")
        d.rectangle([20, 20, 44, 44], fill="#000000")
        d.rectangle([26, 26, 38, 38], fill="#00ff41")

        def on_quit(icon, _):
            icon.stop()
            for p in procs:
                if p and p.poll() is None:
                    p.terminate()
            sys.exit(0)

        def on_show(icon, _):
            if window:
                try: window.show()
                except Exception: pass

        def on_restart_tts(icon, _):
            env = _load_env()
            tts_py = NOTEBOOKS_DIR / "tts_server.py"
            if not tts_py.exists():
                return
            kwargs = {
                "args": [sys.executable, str(tts_py)],
                "cwd":  str(tts_py.parent),
                "env":  env,
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            else:
                kwargs["stdout"] = subprocess.DEVNULL
                kwargs["stderr"] = subprocess.DEVNULL
            subprocess.Popen(**kwargs)
            print("✅ TTS restarted from tray")

        pystray.Icon("BhaiIrrfan", img, "Bhai Irrfan",
            menu=pystray.Menu(
                pystray.MenuItem("Bhai Irrfan  v1.0", lambda *_: None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Show Window",   on_show),
                pystray.MenuItem("Restart Voice", on_restart_tts),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit",          on_quit),
            )
        ).run()
    except Exception as e:
        print(f"⚠  Tray unavailable ({e}) — use Ctrl+Shift+Q inside the window")


# ── Main ──────────────────────────────────────────────────────
def main() -> None:
    env = _load_env()

    # 1. Start both servers silently
    print("Starting backend  (port 8000)...")
    main_proc = start_backend(env)

    print("Starting TTS      (port 8001)...")
    tts_proc = start_tts(env)

    # 2. Wait for backend to be ready before opening UI
    print("Waiting for backend...")
    if wait_for(f"{URL}/health", timeout=20):
        print("✅ Backend ready")
    else:
        print("⚠  Backend slow to start — opening UI anyway")

    print("⏳ TTS voice loading in background (20-60s on CPU)...")

    # 3. Collect live processes for tray/shutdown
    procs = [p for p in [main_proc, tts_proc] if p]

    # 4. Open PyWebView — frameless + transparent
    api = Api()

    try:
        import webview

        try:
            window = webview.create_window(
                "Bhai Irrfan",
                URL,
                width=420,
                height=500,
                resizable=False,
                frameless=True,
                transparent=True,
                js_api=api,
                # on_top intentionally removed — other windows go over it normally
            )
        except TypeError:
            # Older pywebview without transparent support
            try:
                window = webview.create_window(
                    "Bhai Irrfan",
                    URL,
                    width=420,
                    height=600,
                    resizable=False,
                    frameless=True,
                )
            except TypeError:
                window = webview.create_window(
                    "Bhai Irrfan", URL,
                    width=420, height=500,
                )
                
        api.set_window(window)

        # Start tray with window reference (enables Show Window)
        threading.Thread(
            target=start_tray,
            args=(procs, window),
            daemon=True
        ).start()

        webview.start(debug=False, private_mode=False)

    except ImportError:
        import webbrowser
        print("⚠  PyWebView not installed — opening browser instead")
        # Start tray anyway
        threading.Thread(target=start_tray, args=(procs,), daemon=True).start()
        webbrowser.open(URL)
        # Keep process alive for tray
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            pass

    # 5. Cleanup when window closes
    print("Shutting down...")
    for p in procs:
        if p and p.poll() is None:
            try: p.terminate(); p.wait(timeout=3)
            except Exception: pass


if __name__ == "__main__":
    main()