"""
Bhai Irrfan — Desktop launcher
Starts BOTH servers silently, then opens the UI with transparent background.

  Port 8000 — main backend  (tasks, chat, calendar)
  Port 8001 — TTS server    (voice cloning, speech)
  Port 8002 — frontend server (serves index.html)
"""

from __future__ import annotations
import os, signal, subprocess, sys, threading, time, http.server, socketserver
from pathlib import Path

URL          = "http://127.0.0.1:8000"
FRONTEND_URL = "http://127.0.0.1:8002"
BASE_DIR     = Path(__file__).parent
BACKEND_DIR  = BASE_DIR / "backend"
NOTEBOOKS_DIR= BASE_DIR / "notebooks"
FRONTEND_DIR = BASE_DIR / "frontend"


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


def start_frontend_server() -> None:
    """Start a simple HTTP server for frontend files on port 8002."""
    if not FRONTEND_DIR.exists():
        print(f"⚠  Frontend directory not found: {FRONTEND_DIR}")
        return
    
    # Change to frontend directory
    original_dir = os.getcwd()
    os.chdir(str(FRONTEND_DIR))
    
    try:
        # Create handler that serves index.html by default
        handler = http.server.SimpleHTTPRequestHandler
        
        # Allow reuse of address
        socketserver.TCPServer.allow_reuse_address = True
        
        with socketserver.TCPServer(("127.0.0.1", 8002), handler) as httpd:
            print(f"✅ Frontend server running on {FRONTEND_URL}")
            httpd.serve_forever()
    except OSError as e:
        print(f"⚠  Could not start frontend server on port 8002: {e}")
        print("   Trying alternative port 8003...")
        try:
            with socketserver.TCPServer(("127.0.0.1", 8003), handler) as httpd:
                print(f"✅ Frontend server running on http://127.0.0.1:8003")
                httpd.serve_forever()
        except Exception as e2:
            print(f"❌ Failed to start frontend server: {e2}")
    finally:
        os.chdir(original_dir)


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
    """Wait for a URL to become available."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def start_tray(procs: list, window=None) -> None:
    """System tray icon with menu."""
    try:
        import pystray
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (64, 64), (0,0,0,0))
        d = ImageDraw.Draw(img)
        d.rectangle([12,12,52,52], fill="#00ff41")
        d.rectangle([20,20,44,44], fill="#000000")
        d.rectangle([26,26,38,38], fill="#00ff41")

        def on_quit(icon, _):
            icon.stop()
            for p in procs:
                if p and p.poll() is None:
                    p.terminate()
            sys.exit(0)

        def on_show(icon, _):
            """Bring window to front if minimized/ hidden."""
            if window:
                try:
                    window.show()
                except Exception:
                    pass
        
        def on_restart_tts(icon, _):
            """Restart TTS server if it crashed."""
            env = _load_env()
            tts_py = NOTEBOOKS_DIR / "tts_server.py"
            if not tts_py.exists():
                print("⚠  tts_server.py not found")
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
            print(">> TTS server restarted from tray")

        pystray.Icon("BhaiIrrfan", img, "Bhai Irrfan",
            menu=pystray.Menu(
                pystray.MenuItem("Bhai Irrfan v1.0", lambda *_: None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Show Window", on_show),
                pystray.MenuItem("Restart Voice", on_restart_tts),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", on_quit),
            )
        ).run()
    except Exception as e:
        print(f"⚠  Tray unavailable: {e}")


def main() -> None:
    env = _load_env()

    # Start frontend server first (serves index.html)
    print("Starting frontend server (port 8002)...")
    frontend_thread = threading.Thread(target=start_frontend_server, daemon=True)
    frontend_thread.start()
    
    # Give frontend server a moment to start
    time.sleep(1)

    # Start backend servers
    print("Starting main backend (port 8000)...")
    main_proc = start_backend(env)

    print("Starting TTS server (port 8001)...")
    tts_proc = start_tts(env)

    # Wait for main backend (required before API calls work)
    if not wait_for("http://127.0.0.1:8000/health", timeout=20):
        print("⚠  Main backend didn't start in time")
    else:
        print("✅ Backend ready")

    print("⏳ TTS voice loading in background (30-60s on CPU)...")
    print(f"🌐 Opening UI from {FRONTEND_URL}")

    # System tray (handles both processes on quit)
    procs = [p for p in [main_proc, tts_proc] if p]
    threading.Thread(target=start_tray, args=(procs,), daemon=True).start()

    # Open PyWebView with transparent background
    try:
        import webview
        
        # Check if frontend is ready
        if not wait_for(FRONTEND_URL, timeout=5):
            print("⚠  Frontend server not ready, using fallback URL")
            fallback_url = "http://127.0.0.1:8000"
        else:
            fallback_url = FRONTEND_URL
        
        try:
            window = webview.create_window(
                "Bhai Irrfan",
                fallback_url,
                width=420,
                height=600,
                resizable=False,
                frameless=True,
                #background_color="#000000",
                transparent=True
            )
        except TypeError:
            # Fallback for older webview versions
            window = webview.create_window(
                "Bhai Irrfan",
                fallback_url,
                width=420,
                height=600,
                resizable=False,
                frameless=True
            )
        
        # Start webview with window reference for tray
        webview.start(debug=False, private_mode=False)
        
    except ImportError:
        import webbrowser
        print("⚠  PyWebView not installed, opening in browser")
        webbrowser.open(FRONTEND_URL)

    # Cleanup on window close
    print("🔄 Shutting down...")
    for p in procs:
        if p and p.poll() is None:
            p.terminate()
            p.wait(timeout=2)


if __name__ == "__main__":
    main()