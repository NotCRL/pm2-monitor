#!/bin/sh
# Double-click (Linux file managers: "Run" / "Run in terminal") to start pm2 monitor and open it in your browser.
# Needs Python 3.8 or newer. Also works from a terminal: ./start-pm2-monitor.sh
cd "$(dirname "$0")" || exit 1
for python in python3 python; do
  if command -v "$python" >/dev/null 2>&1; then
    exec "$python" launch.py "$@"
  fi
done
echo "Python 3.8 or newer is needed to run pm2 monitor, and it was not found."
echo "Install it from https://www.python.org/downloads/ (or with your package manager), then run this file again."
if command -v xdg-open >/dev/null 2>&1; then xdg-open "https://www.python.org/downloads/" >/dev/null 2>&1; fi
if [ -t 0 ]; then printf "Press Enter to close. "; read -r _; fi
exit 1
