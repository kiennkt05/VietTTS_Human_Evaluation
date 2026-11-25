@echo off
setlocal
cd /d "%~dp0" || exit /b 1
echo Vietnamese TTS Annotation - local mode
echo Open the URL printed by the server after startup.
echo To share over the LAN use start_windows_lan.bat instead.
call "%~dp0start_windows_python.bat" --host 127.0.0.1 --port 8765 %*
set "status=%errorlevel%"
if not "%status%"=="0" pause
exit /b %status%
