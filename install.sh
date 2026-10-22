#!/usr/bin/env bash
# install.sh - put the desktop pet on this machine as a first-class app.
#
#   ./install.sh                 install deps + menu entry
#   ./install.sh --autostart     also start the pet at login
#   ./install.sh --uninstall     remove the entries (pet files are left alone)
#
# The script never touches your config: companion_config.json, .env and the
# state files are yours. It only writes desktop-entry files and, with
# --autostart, one autostart entry pointing at this checkout.

set -u

APP_ID="desktop-pet"
APP_NAME="Desktop Pet"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTRY_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
ENTRY_PATH="$ENTRY_DIR/$APP_ID.desktop"
AUTOSTART_PATH="$AUTOSTART_DIR/$APP_ID.desktop"

PYTHON="${PYTHON:-python3}"

usage() {
    sed -n '2,9p' "$0"
    exit 0
}

write_desktop_file() {
    local path="$1"
    mkdir -p "$(dirname "$path")"
    cat > "$path" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=Pixel-art desktop buddy with optional AI dialogue
Exec=$PYTHON $SCRIPT_DIR/pet.py
Path=$SCRIPT_DIR
Terminal=false
Categories=Utility;Amusement;
Keywords=pet;companion;desktop;
EOF
    chmod 644 "$path"
}

uninstall() {
    local removed=0
    for path in "$ENTRY_PATH" "$AUTOSTART_PATH"; do
        if [ -e "$path" ]; then
            rm -f "$path"
            echo "Removed $path"
            removed=1
        fi
    done
    [ "$removed" -eq 1 ] || echo "Nothing to remove (no install entries found)."
    echo "State and config under this checkout were left alone."
}

check_deps() {
    if [ ! -f "$SCRIPT_DIR/requirements.txt" ]; then
        echo "note: no requirements.txt found; skipping pip install"
        return 0
    fi
    echo "-> installing python dependencies ($SCRIPT_DIR/requirements.txt)"
    "$PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt" \
        || { echo "pip install failed; install them by hand and re-run"; exit 1; }

    if ! command -v tesseract >/dev/null 2>&1; then
        echo "note: tesseract is not installed."
        echo "      The OCR content filter needs it (apt install"
        echo "      tesseract-ocr / pacman -S tesseract / brew install"
        echo "      tesseract). Without it, captures are refused rather"
        echo "      than sent unfiltered."
    fi
}

main() {
    case "${1:-install}" in
        -h|--help) usage ;;
        --uninstall|-u) uninstall; exit 0 ;;
        --autostart|-a) ;;
        install|"") ;;
        *) usage ;;
    esac

    command -v "$PYTHON" >/dev/null 2>&1 \
        || { echo "$PYTHON not found; set PYTHON=/path/to/python"; exit 1; }

    check_deps

    echo "-> writing menu entry: $ENTRY_PATH"
    write_desktop_file "$ENTRY_PATH"
    update-desktop-database "$ENTRY_DIR" 2>/dev/null || true

    if [ "${1:-install}" = "--autostart" ] || [ "${1:-}" = "-a" ]; then
        echo "-> writing autostart entry: $AUTOSTART_PATH"
        write_desktop_file "$AUTOSTART_PATH"
    fi

    echo "done. Launch '$APP_NAME' from your menu, or run:"
    echo "  $PYTHON $SCRIPT_DIR/pet.py"
}

main "$@"
