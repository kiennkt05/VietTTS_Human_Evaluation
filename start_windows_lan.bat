@echo off
setlocal
cd /d "%~dp0" || exit /b 1
echo Vietnamese TTS Annotation (trusted local network)
echo Share the host LAN IP and printed port with other annotators.
echo Do not use on public internet without HTTPS and security review.
call "%~dp0start_windows_python.bat" --host 0.0.0.0 --port 8765 %*
set "status=%errorlevel%"
if not "%status%"=="0" pause
exit /b %status%
