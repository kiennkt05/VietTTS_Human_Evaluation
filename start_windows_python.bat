@echo off
setlocal EnableDelayedExpansion
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 (
    python server.py %*
    exit /b !errorlevel!
)
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 (
    py -3 server.py %*
    exit /b !errorlevel!
)
echo Python 3.10 or newer is required. Install it and make python or py available. 1>&2
exit /b 1
