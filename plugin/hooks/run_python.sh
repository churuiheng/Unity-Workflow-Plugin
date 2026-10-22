#!/usr/bin/env sh
# Runs a Python script with whichever interpreter works here: python3 on macOS/Linux, python on Windows
# (where "python3" can be the Microsoft Store stub, which fails). stdin is passed through untouched.
if python3 -c "" >/dev/null 2>&1; then exec python3 "$@"; fi
if python -c "" >/dev/null 2>&1; then exec python "$@"; fi
if py -3 -c "" >/dev/null 2>&1; then exec py -3 "$@"; fi
exit 0   # no Python: the guard rails are skipped rather than blocking every edit
