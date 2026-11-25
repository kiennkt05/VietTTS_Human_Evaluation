@echo off
cd /d "%~dp0"
echo Vietnamese TTS Annotation - local mode
echo Open http://localhost:8765 after first-run startup.
echo To share over the LAN use start_windows_lan.bat instead.
python server.py --host 127.0.0.1 --port 8765
pause
