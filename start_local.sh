#!/bin/sh
set -eu
cd "$(CDPATH= cd "$(dirname "$0")" && pwd)"

if ! command -v python3 >/dev/null 2>&1 ||
   ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
    printf '%s\n' 'Python 3.10 or newer is required (python3).' >&2
    exit 1
fi

printf '%s\n' 'Vietnamese TTS Annotation (this computer only)'
printf '%s\n' 'Open the URL printed by the server after startup.'
exec python3 server.py --host 127.0.0.1 --port 8765 "$@"
