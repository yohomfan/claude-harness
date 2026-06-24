#!/usr/bin/env bash
#
# stop.sh — Operator control for the combined harness
#
# Usage:
#   ./stop.sh <project-dir> [action]
#
# Actions:
#   pause   — Create AGENT_STOP; agent halts at next tool call, resumes when released (default)
#   resume  — Remove AGENT_STOP; agent continues
#   quit    — Create AGENT_QUIT; agent exits after current iteration
#   status  — Show current control state
#
# Examples:
#   ./stop.sh ./generations/my_app pause
#   ./stop.sh ./generations/my_app resume
#   ./stop.sh ./generations/my_app quit
#   ./stop.sh ./generations/my_app status

set -euo pipefail

usage() {
  echo "Usage: $0 <project-dir> [pause|resume|quit|status]"
  echo ""
  echo "Actions:"
  echo "  pause   Create AGENT_STOP — agent halts at next poll (default)"
  echo "  resume  Remove AGENT_STOP — agent continues"
  echo "  quit    Create AGENT_QUIT — agent exits after current iteration"
  echo "  status  Show current control state"
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

PROJECT_DIR="$1"
ACTION="${2:-pause}"

if [ ! -d "$PROJECT_DIR" ]; then
  echo "Error: directory '$PROJECT_DIR' does not exist."
  exit 1
fi

STOP_FILE="$PROJECT_DIR/AGENT_STOP"
QUIT_FILE="$PROJECT_DIR/AGENT_QUIT"
STEER_FILE="$PROJECT_DIR/STEER.md"

case "$ACTION" in
  pause)
    touch "$STOP_FILE"
    echo "Paused. Agent will halt at next poll (up to 60s)."
    echo "Run '$0 $PROJECT_DIR resume' to continue."
    ;;
  resume)
    if [ -f "$STOP_FILE" ]; then
      rm "$STOP_FILE"
      echo "Resumed. Agent will continue at next poll."
    else
      echo "Not paused (AGENT_STOP does not exist)."
    fi
    ;;
  quit)
    touch "$QUIT_FILE"
    echo "Quit signal sent. Agent will exit after current iteration."
    ;;
  status)
    echo "Project: $PROJECT_DIR"
    echo ""
    if [ -f "$STOP_FILE" ]; then
      echo "  AGENT_STOP:  ACTIVE (paused)"
    else
      echo "  AGENT_STOP:  not set"
    fi
    if [ -f "$QUIT_FILE" ]; then
      echo "  AGENT_QUIT:  ACTIVE (will exit after current iteration)"
    else
      echo "  AGENT_QUIT:  not set"
    fi
    if [ -s "$STEER_FILE" ]; then
      echo "  STEER.md:    has content (pending injection)"
    else
      echo "  STEER.md:    empty or absent"
    fi
    echo ""
    if [ -f "$PROJECT_DIR/feature_list.json" ]; then
      python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
p = sum(1 for t in d if t.get('passes'))
print(f'  Progress:    {p}/{len(d)} tests passing ({100*p/len(d):.1f}%)')
" "$PROJECT_DIR/feature_list.json" 2>/dev/null || true
    fi
    ;;
  *)
    echo "Unknown action: $ACTION"
    usage
    ;;
esac
