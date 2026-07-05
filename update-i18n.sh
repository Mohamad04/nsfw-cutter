#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
I18N_DIR="$ROOT_DIR/resources/i18n"
SOURCE_DIR="$ROOT_DIR/vue/qml/WindowsApplication"
SOURCE_LABEL="${SOURCE_DIR#"$ROOT_DIR"/}"

resolve_lupdate() {
    if command -v pylupdate6 >/dev/null 2>&1; then
        printf '%s\n' "pylupdate6"
        return 0
    fi

    if command -v pyside6-lupdate >/dev/null 2>&1; then
        printf '%s\n' "pyside6-lupdate"
        return 0
    fi

    local candidates=(
        "$ROOT_DIR/.venv/bin/pylupdate6"
        "$ROOT_DIR/.venv/bin/pyside6-lupdate"
        "$ROOT_DIR/.venv/Scripts/pylupdate6.exe"
        "$ROOT_DIR/.venv/Scripts/pyside6-lupdate.exe"
    )

    local candidate
    for candidate in "${candidates[@]}"; do
        if [[ -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    return 1
}

if [[ ! -d "$SOURCE_DIR" ]]; then
    echo "Missing QML source directory: $SOURCE_DIR" >&2
    exit 1
fi

if [[ ! -d "$I18N_DIR" ]]; then
    echo "Missing i18n directory: $I18N_DIR" >&2
    exit 1
fi

LUPDATE="$(resolve_lupdate)" || {
    echo "Could not find pylupdate6 or pyside6-lupdate." >&2
    echo "Install PyQt6/PySide6 or create the project virtualenv first." >&2
    exit 1
}

shopt -s nullglob
ts_files=("$I18N_DIR"/*.ts)

if (( ${#ts_files[@]} == 0 )); then
    echo "No .ts translation files found in $I18N_DIR" >&2
    exit 1
fi

echo "Updating ${#ts_files[@]} i18n source file(s) from $SOURCE_LABEL"
"$LUPDATE" "$SOURCE_DIR" -ts "${ts_files[@]}"

echo "Updated ${#ts_files[@]} i18n source file(s)."
