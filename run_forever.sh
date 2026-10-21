#!/usr/bin/env bash
# local watchdog — the deterministic loop on this machine.
# the LLM agent is the chat session; loop.yml is the external heartbeat.
# controls: touch state/STOP  -> halt
#           touch state/PAUSE -> idle (60s poll)
cd "$(dirname "$0")"
while [ ! -f state/STOP ]; do
  if [ -f state/PAUSE ]; then
    echo "[watchdog] paused"
    sleep 60
    continue
  fi
  if ! python3 scripts/backlog.py --check-lock; then
    sleep 30
    continue
  fi
  python3 scripts/backlog.py --one || true
  python3 scripts/brain.py || true
  sleep 5
done
echo "[watchdog] stopped (state/STOP present)"
