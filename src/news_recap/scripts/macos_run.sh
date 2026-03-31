#!/usr/bin/env bash
set -uo pipefail

export USER="$(whoami)"
export HOME="${HOME:-$(eval echo ~"$(whoami)")}"
export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

LOG_DIR="${HOME}/Library/Logs/news-recap"
LOG_FILE="${LOG_DIR}/news-recap-$(date +%Y-%m-%d).log"
mkdir -p "${LOG_DIR}"

find "${LOG_DIR}" -name 'news-recap-*.log' -mtime +30 -delete 2>/dev/null || true

{
  echo "$(date '+%Y-%m-%d %H:%M:%S') ===== news-recap"
  echo "USER=${USER} HOME=${HOME}"
  command -v {{NEWS_RECAP_CMD}} || echo "{{NEWS_RECAP_CMD}}: not in PATH"
  {{NEWS_RECAP_CMD}} ingest {{RSS_ARGS}} && \
  {{NEWS_RECAP_CMD}} create {{AGENT_ARGS}}
  rc=$?
  if [ $rc -eq 0 ]; then
    echo "===== RESULT: OK"
  else
    echo "===== RESULT: FAILED (exit $rc)"
  fi
} >> "$LOG_FILE" 2>&1
