#!/bin/sh
set -eu
cd "$(CDPATH= cd "$(dirname "$0")" && pwd)"

if ! command -v python3 >/dev/null 2>&1 ||
   ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
    printf '%s\n' 'Python 3.10 or newer is required (python3).' >&2
    exit 1
fi

printf '%s\n' 'Vietnamese TTS Annotation (trusted local network)'
printf '%s\n' 'Share the host LAN IP and printed port with other annotators.'
printf '%s\n' 'Do not use on the public internet without HTTPS and a security review.'
exec python3 server.py --host 0.0.0.0 --port 8765 "$@"
