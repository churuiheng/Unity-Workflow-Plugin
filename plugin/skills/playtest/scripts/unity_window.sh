#!/usr/bin/env sh
# Unity editor window helpers for play-testing. The editor barely ticks while it is in the background, so play
# steps, compiles and MCP calls stall or time out until it is in front.
#
#   sh unity_window.sh focus [project-name]                 bring the editor to the front
#   sh unity_window.sh keep <minutes> [project-name]        keep it in front (run in the background during long runs)
#   sh unity_window.sh dismiss-save-dialog [seconds]        press Cancel on "Scene(s) Have Been Modified" (keeps the
#                                                           user's unsaved scene edits; play still starts)
# project-name narrows to the editor whose window title contains it (when several projects are open).
here=$(cd "$(dirname "$0")" && pwd)
cmd=${1:-focus}
os=$(uname -s 2>/dev/null || echo unknown)

win_ps() {  # run a PowerShell helper on Windows
  script=$1; shift
  if command -v cygpath >/dev/null 2>&1; then script=$(cygpath -w "$here/win/$script"); else script="$here/win/$script"; fi
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$script" "$@"
}

case "$os" in
  MINGW*|MSYS*|CYGWIN*|Windows_NT)
    case "$cmd" in
      focus) win_ps focus_unity.ps1 "${2:-}" ;;
      keep) win_ps keep_focused.ps1 "${2:-5}" "${3:-}" ;;
      dismiss-save-dialog) win_ps dismiss_save_dialog.ps1 "${2:-40}" ;;
      *) echo "unknown command: $cmd"; exit 2 ;;
    esac ;;
  Darwin)
    focus_mac() {
      if [ -n "$1" ]; then
        osascript -e "tell application \"System Events\" to tell (first process whose name is \"Unity\") to set frontmost to true" \
                  -e "tell application \"System Events\" to tell process \"Unity\" to perform action \"AXRaise\" of (first window whose name contains \"$1\")" >/dev/null 2>&1 \
          || osascript -e 'tell application "Unity" to activate' >/dev/null 2>&1
      else
        osascript -e 'tell application "Unity" to activate' >/dev/null 2>&1
      fi && echo "focused: Unity" || { echo "Unity is not running (or Automation permission was refused)"; exit 1; }
    }
    case "$cmd" in
      focus) focus_mac "${2:-}" ;;
      keep) end=$(( $(date +%s) + ${2:-5} * 60 )); while [ "$(date +%s)" -lt "$end" ]; do focus_mac "${3:-}" >/dev/null; sleep 20; done; echo "kept Unity focused for ${2:-5} min" ;;
      dismiss-save-dialog)
        secs=${2:-40}; i=0
        while [ $i -lt $((secs * 2)) ]; do
          if osascript -e 'tell application "System Events" to tell process "Unity" to click button "Cancel" of (first window whose name contains "Modified")' >/dev/null 2>&1; then
            echo "cancelled"; exit 0
          fi
          sleep 0.5; i=$((i + 1))
        done
        echo "no dialog (or macOS Accessibility permission is needed for the terminal: System Settings ▸ Privacy ▸ Accessibility)" ;;
      *) echo "unknown command: $cmd"; exit 2 ;;
    esac ;;
  Linux)
    focus_linux() {
      name=${1:-Unity}
      if command -v wmctrl >/dev/null 2>&1; then wmctrl -a "$name" && echo "focused: $name" && return 0; fi
      if command -v xdotool >/dev/null 2>&1; then xdotool search --name "$name" windowactivate >/dev/null 2>&1 && echo "focused: $name" && return 0; fi
      echo "install wmctrl or xdotool to focus windows"; return 1
    }
    case "$cmd" in
      focus) focus_linux "${2:-}" ;;
      keep) end=$(( $(date +%s) + ${2:-5} * 60 )); while [ "$(date +%s)" -lt "$end" ]; do focus_linux "${3:-}" >/dev/null; sleep 20; done; echo "kept Unity focused for ${2:-5} min" ;;
      dismiss-save-dialog)
        if command -v xdotool >/dev/null 2>&1; then
          secs=${2:-40}; i=0
          while [ $i -lt $((secs * 2)) ]; do
            w=$(xdotool search --name "Modified" 2>/dev/null | head -1)
            if [ -n "$w" ]; then xdotool windowactivate "$w" key Escape; echo "cancelled"; exit 0; fi
            sleep 0.5; i=$((i + 1))
          done
          echo "no dialog"
        else echo "install xdotool to dismiss dialogs"; fi ;;
      *) echo "unknown command: $cmd"; exit 2 ;;
    esac ;;
  *) echo "unsupported OS: $os"; exit 2 ;;
esac
