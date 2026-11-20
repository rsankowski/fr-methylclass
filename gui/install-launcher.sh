#!/usr/bin/env bash
# Put a double-clickable "fr-methylclass" icon on the desktop and in the
# applications menu (Linux). .desktop files need absolute paths, so this stamps
# the current location of the repository into them. Run it again after moving
# the repository.   gui/install-launcher.sh [--quiet]
set -euo pipefail
GUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$GUI")"
QUIET="${1:-}"
chmod +x "$GUI/start.sh" "$REPO/fr-methylclass-gui.desktop" 2>/dev/null || true

ENTRY="[Desktop Entry]
Version=1.0
Type=Application
Name=fr-methylclass
GenericName=Methylation classification
Comment=Nanopore methylation tumour classification (Nextflow), research use only
Exec=\"$GUI/start.sh\"
Path=$REPO
Icon=$GUI/assets/icon.png
Terminal=false
Categories=Science;Biology;
StartupNotify=false"

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
printf '%s\n' "$ENTRY" > "$APPS/fr-methylclass-gui.desktop"
chmod +x "$APPS/fr-methylclass-gui.desktop"
update-desktop-database "$APPS" >/dev/null 2>&1 || true

DESK="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
[ -n "$DESK" ] && [ "$DESK" != "$HOME" ] || DESK="$HOME/Desktop"
if [ -d "$DESK" ]; then
    printf '%s\n' "$ENTRY" > "$DESK/fr-methylclass-gui.desktop"
    chmod +x "$DESK/fr-methylclass-gui.desktop"
    # GNOME only launches desktop icons that are marked trusted
    gio set "$DESK/fr-methylclass-gui.desktop" metadata::trusted true >/dev/null 2>&1 || true
fi

if [ "$QUIET" != "--quiet" ]; then
    echo "Installed the fr-methylclass launcher:"
    echo "  app menu: $APPS/fr-methylclass-gui.desktop"
    [ -d "$DESK" ] && echo "  desktop:  $DESK/fr-methylclass-gui.desktop  (GNOME: right-click > Allow Launching, if asked)"
fi
