@echo off
cd /d "%~dp0"
echo Vietnamese TTS Annotation (trusted local network)
echo Share http://YOUR-PC-LAN-IP:8765 with other annotators.
echo Do not use on public internet without HTTPS and security review.
python server.py --host 0.0.0.0 --port 8765
pause
