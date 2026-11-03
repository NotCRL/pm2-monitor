#!/bin/sh
# Double-click in Finder to start pm2 monitor and open it in your browser (macOS).
# If macOS says it cannot be opened: right-click the file > Open > Open (needed once, the file is not signed).
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  exec python3 launch.py "$@"
fi
echo "Python 3.8 or newer is needed to run pm2 monitor, and it was not found."
echo "Opening the download page: install Python, then double-click this file again."
open "https://www.python.org/downloads/"
printf "Press Enter to close. "; read -r _
exit 1
