#!/usr/bin/env bash
set -uo pipefail

export HOME="${HOME:-$(eval echo ~"$(whoami)")}"
export PATH="${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"

LOG_DIR="${HOME}/.local/state/news-recap"
LOG_FILE="${LOG_DIR}/news-recap-$(date +%Y-%m-%d).log"
mkdir -p "${LOG_DIR}"

find "${LOG_DIR}" -name 'news-recap-*.log' -mtime +30 -delete 2>/dev/null || true

{
  echo "$(date '+%Y-%m-%d %H:%M:%S') ===== news-recap"
  echo "USER=${USER:-} HOME=${HOME}"
  command -v news-recap || echo "news-recap: not in PATH"
  news-recap ingest {{RSS_ARGS}} && \
  news-recap recap {{AGENT_ARGS}}
  rc=$?
  if [ $rc -eq 0 ]; then
    echo "===== RESULT: OK"
  else
    echo "===== RESULT: FAILED (exit $rc)"
  fi
} >> "$LOG_FILE" 2>&1
