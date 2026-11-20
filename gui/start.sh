#!/usr/bin/env bash
# Start the fr-methylclass GUI and open it in the browser.
#
#   gui/start.sh               from a terminal: runs in the foreground (Ctrl+C stops it)
#   double-click the icon      runs in the background; stop it with the Quit button
#
# Needs only python3 (3.7+); everything else is checked inside the GUI (Check setup).
# Port: FR_METHYLCLASS_GUI_PORT (default 8780).
set -uo pipefail
GUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${FR_METHYLCLASS_GUI_PORT:-8780}"
URL="http://127.0.0.1:${PORT}/"
export FR_METHYLCLASS_GUI_PORT="$PORT"

say() {  # message box when started without a terminal, else stderr
    echo "$1" >&2
    if [ ! -t 1 ]; then
        if command -v zenity >/dev/null 2>&1; then zenity --error --title="fr-methylclass" --text="$1" 2>/dev/null
        elif command -v kdialog >/dev/null 2>&1; then kdialog --error "$1" 2>/dev/null
        elif command -v osascript >/dev/null 2>&1; then osascript -e "display alert \"fr-methylclass\" message \"$1\"" >/dev/null
        elif command -v notify-send >/dev/null 2>&1; then notify-send "fr-methylclass" "$1"
        fi
    fi
}

open_url() {
    if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 &
    elif command -v open >/dev/null 2>&1; then open "$URL"
    else echo "Open $URL in your browser."; fi
}

# Desktop launchers often start with a minimal PATH: add the usual places for
# nextflow / java / conda python.
for d in "$HOME/.local/bin" "$HOME/bin" "$HOME/.sdkman/candidates/java/current/bin" \
         "$HOME/miniconda3/bin" "$HOME/anaconda3/bin" "$HOME/miniforge3/bin" /usr/local/bin /opt/homebrew/bin; do
    [ -d "$d" ] && case ":$PATH:" in *":$d:"*) ;; *) PATH="$PATH:$d" ;; esac
done
export PATH

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
    for c in python3 python; do
        if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 7))' 2>/dev/null; then
            PY="$c"; break
        fi
    done
fi
[ -n "$PY" ] || { say "Python 3.7 or newer is needed to run the fr-methylclass GUI. Install python3 and try again."; exit 1; }

# Already running? Just open it.
if "$PY" - "$URL" <<'PYEOF' 2>/dev/null
import sys, urllib.request
urllib.request.urlopen(sys.argv[1] + "api/settings", timeout=2)
PYEOF
then
    open_url
    exit 0
fi

# First start on this computer: put an icon on the desktop and in the app menu.
if [ "$(uname -s)" = Linux ] && [ ! -e "$GUI/.launcher-installed" ]; then
    bash "$GUI/install-launcher.sh" --quiet && touch "$GUI/.launcher-installed"
fi

if [ -t 1 ]; then
    exec "$PY" "$GUI/server.py" --port "$PORT" "$@"
fi

mkdir -p "$GUI/logs"
nohup "$PY" "$GUI/server.py" --port "$PORT" "$@" >>"$GUI/logs/server.log" 2>&1 &
pid=$!
for _ in $(seq 1 40); do
    sleep 0.25
    kill -0 "$pid" 2>/dev/null || { say "The GUI did not start. See $GUI/logs/server.log"; exit 1; }
    "$PY" - "$URL" <<'PYEOF' 2>/dev/null && exit 0
import sys, urllib.request
urllib.request.urlopen(sys.argv[1] + "api/settings", timeout=1)
PYEOF
done
say "The GUI is slow to start. Open $URL in your browser, or see $GUI/logs/server.log"
