"""
Bhai Irrfan — Silent Windows Launcher
Run this with pythonw to get ZERO console window.
Just the HUD floating on your desktop.

Usage: double-click  launch_silent.pyw
       (requires GEMINI_API_KEY in system environment variables)
"""
import subprocess, sys, os
from pathlib import Path

# Set your key here if you don't want to use env vars:
# os.environ["GEMINI_API_KEY"] = "your-key-here"

os.chdir(Path(__file__).parent)

# Activate venv if present
venv_python = Path(".venv/Scripts/pythonw.exe")  # Windows
if not venv_python.exists():
    venv_python = Path(".venv/bin/python3")       # Mac/Linux

if venv_python.exists():
    subprocess.Popen([str(venv_python), "app.py"])
else:
    subprocess.Popen([sys.executable, "app.py"])
