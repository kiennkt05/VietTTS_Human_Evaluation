@echo off
cd /d "%~dp0"
echo Vietnamese TTS Annotation (this computer only)
python server.py --host 127.0.0.1 --port 8765
pause
