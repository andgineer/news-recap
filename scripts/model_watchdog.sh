#!/usr/bin/env bash
set -euo pipefail

# LLM model watchdog:
# - runs smoke matrix for codex/claude/gemini x fast/quality;
# - detects model-drift and recurring failures;
# - optionally runs automated model-refresh prompt through a selected agent.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

NEWS_RECAP_BIN="${NEWS_RECAP_BIN:-./.venv/bin/news-recap}"
if [[ ! -x "${NEWS_RECAP_BIN}" ]]; then
  NEWS_RECAP_BIN="${NEWS_RECAP_BIN_FALLBACK:-news-recap}"
fi

REPORT_DIR="${NEWS_RECAP_MODEL_REPORT_DIR:-agent_checks}"
STATE_FILE="${NEWS_RECAP_MODEL_WATCHDOG_STATE:-.news_recap_workdir/model_watchdog.state}"
SMOKE_TIMEOUT="${NEWS_RECAP_MODEL_WATCHDOG_TIMEOUT_SECONDS:-30}"
REFRESH_AGENT="${NEWS_RECAP_MODEL_REFRESH_AGENT:-codex}"
RUN_REFRESH=0

usage() {
  cat <<'EOF'
Usage: scripts/model_watchdog.sh [options]

Options:
  --run-refresh           Run automated refresh prompt if triggers are detected.
  --refresh-agent AGENT   Agent for refresh run: codex|claude|gemini. Default: codex.
  --timeout-seconds N     Smoke timeout per check. Default: 30.
  --help                  Show this help.

Env overrides:
  NEWS_RECAP_BIN
  NEWS_RECAP_MODEL_REPORT_DIR
  NEWS_RECAP_MODEL_WATCHDOG_STATE
  NEWS_RECAP_MODEL_WATCHDOG_TIMEOUT_SECONDS
  NEWS_RECAP_MODEL_REFRESH_AGENT
EOF
}

while (($# > 0)); do
  case "$1" in
    --run-refresh)
      RUN_REFRESH=1
      shift
      ;;
    --refresh-agent)
      REFRESH_AGENT="${2:-}"
      shift 2
      ;;
    --timeout-seconds)
      SMOKE_TIMEOUT="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

mkdir -p "${REPORT_DIR}" "$(dirname "${STATE_FILE}")"
touch "${STATE_FILE}"

get_state() {
  local key="$1"
  local default_value="$2"
  local value
  value="$(grep -E "^${key}=" "${STATE_FILE}" | tail -n 1 | cut -d'=' -f2- || true)"
  if [[ -z "${value}" ]]; then
    echo "${default_value}"
  else
    echo "${value}"
  fi
}

set_state() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"
  grep -E -v "^${key}=" "${STATE_FILE}" > "${tmp}" || true
  printf '%s=%s\n' "${key}" "${value}" >> "${tmp}"
  mv "${tmp}" "${STATE_FILE}"
}

classify_failure() {
  local log_file="$1"
  local lower
  lower="$(tr '[:upper:]' '[:lower:]' < "${log_file}")"

  if echo "${lower}" | grep -E -q \
    "(model_not_available|model.*not found|unsupported.*model|deprecated.*model|unknown model|does not exist)"; then
    echo "model_not_available"
    return
  fi
  if echo "${lower}" | grep -E -q "(probe timed out|synthetic task timed out)"; then
    echo "timeout_or_probe"
    return
  fi
  if echo "${lower}" | grep -E -q \
    "(gemini_api_key|api key|authentication|unauthorized|forbidden|access denied|login required|permission denied)"; then
    echo "access_or_auth"
    return
  fi
  if echo "${lower}" | grep -E -q \
    "(billing|quota|rate limit|too many requests|insufficient_quota|insufficient quota|\\b429\\b)"; then
    echo "billing_or_quota"
    return
  fi
  echo "other_failure"
}

get_agent_version() {
  local agent="$1"
  python3 - "$agent" <<'PY'
import subprocess
import sys

agent = sys.argv[1]
probe_variants = (
    [agent, "--version"],
    [agent, "-v"],
    [agent, "version"],
)
for argv in probe_variants:
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception:
        continue
    text = (completed.stdout or completed.stderr or "").strip()
    if not text:
        continue
    first_line = text.splitlines()[0].strip()
    if first_line:
        print(first_line)
        raise SystemExit(0)
print("unavailable")
PY
}

refresh_prompt_file() {
  local target="$1"
  cat > "${target}" <<'EOF'
You are the LLM model-maintenance agent for this repo.

Goal:
Validate current model routing for codex/claude/gemini and update model mappings only if needed.

Rules:
1) Work only in this repo.
2) Run smoke matrix for agents x profiles (fast, quality).
3) Treat auth/quota failures as non-model issues; do NOT change model mapping for them.
4) Change mapping only when failure indicates model drift (not found/deprecated/unsupported).
5) After each candidate change, re-run smoke for that exact agent/profile.
6) Keep edits minimal and deterministic.

Commands to use:
- news-recap llm smoke --agent codex --model-profile fast
- news-recap llm smoke --agent codex --model-profile quality
- news-recap llm smoke --agent claude --model-profile fast
- news-recap llm smoke --agent claude --model-profile quality
- news-recap llm smoke --agent gemini --model-profile fast
- news-recap llm smoke --agent gemini --model-profile quality

If a model drift is confirmed:
- Update env defaults/mapping in config.
- Update docs with new known-good defaults.
- Update tests that assert defaults.
- Run:
  - uv run pytest -q
  - source ./activate.sh && pre-commit run --verbose --all-files --

Output:
1) A short report with before/after matrix.
2) Exact files changed.
3) Unresolved blockers (if any).
EOF
}

run_refresh() {
  local agent="$1"
  local prompt_file="$2"
  local output_file="$3"
  local prompt
  local status
  prompt="$(cat "${prompt_file}")"

  case "${agent}" in
    codex)
      local model="${NEWS_RECAP_LLM_CODEX_MODEL_QUALITY:-gpt-5-codex}"
      set +e
      codex exec \
        --sandbox workspace-write \
        -c sandbox_workspace_write.network_access=true \
        -c model_reasoning_effort=high \
        --model "${model}" \
        "${prompt}" > "${output_file}" 2>&1
      status=$?
      set -e
      ;;
    claude)
      local model="${NEWS_RECAP_LLM_CLAUDE_MODEL_QUALITY:-opus}"
      set +e
      claude -p \
        --model "${model}" \
        --permission-mode dontAsk \
        --allowed-tools "Read,Write,Edit,WebFetch,Bash(curl:*),Bash(cat:*),Bash(shasum:*),Bash(pwd:*),Bash(ls:*)" \
        -- "${prompt}" > "${output_file}" 2>&1
      status=$?
      set -e
      ;;
    gemini)
      local model="${NEWS_RECAP_LLM_GEMINI_MODEL_QUALITY:-gemini-2.5-pro}"
      set +e
      gemini \
        --model "${model}" \
        --approval-mode auto_edit \
        --include-directories . \
        --allowed-tools read_file,write_file,replace,web_fetch,list_directory \
        --prompt "${prompt}" > "${output_file}" 2>&1
      status=$?
      set -e
      ;;
    *)
      echo "Unsupported refresh agent: ${agent}" > "${output_file}"
      return 2
      ;;
  esac

  return "${status}"
}

timestamp="$(date +%Y%m%d_%H%M%S)"
run_dir="${REPORT_DIR}/model_watchdog_${timestamp}"
mkdir -p "${run_dir}"

matrix_tsv="${run_dir}/matrix.tsv"
triggers_file="${run_dir}/triggers.txt"
versions_file="${run_dir}/versions.tsv"
touch "${matrix_tsv}" "${triggers_file}" "${versions_file}"

add_trigger() {
  local reason="$1"
  if ! grep -Fxq "${reason}" "${triggers_file}"; then
    echo "${reason}" >> "${triggers_file}"
  fi
}

# Version-change trigger
for agent in codex claude gemini; do
  current_version="$(get_agent_version "${agent}")"
  previous_version="$(get_state "version_${agent}" "")"
  printf '%s\t%s\n' "${agent}" "${current_version}" >> "${versions_file}"
  if [[ -n "${previous_version}" && "${current_version}" != "${previous_version}" ]]; then
    add_trigger "version_change:${agent}:${previous_version} -> ${current_version}"
  fi
  set_state "version_${agent}" "${current_version}"
done

# Weekly trigger baseline
now_epoch="$(date +%s)"
last_weekly_epoch="$(get_state "last_weekly_trigger_epoch" "0")"
if [[ "${last_weekly_epoch}" == "0" ]]; then
  set_state "last_weekly_trigger_epoch" "${now_epoch}"
elif (( now_epoch - last_weekly_epoch >= 604800 )); then
  add_trigger "weekly_schedule"
  set_state "last_weekly_trigger_epoch" "${now_epoch}"
fi

blocking_failures=0

pairs=(
  "codex fast"
  "codex quality"
  "claude fast"
  "claude quality"
  "gemini fast"
  "gemini quality"
)

for pair in "${pairs[@]}"; do
  # shellcheck disable=SC2086
  set -- ${pair}
  agent="$1"
  profile="$2"
  log_file="${run_dir}/${agent}_${profile}.log"

  set +e
  "${NEWS_RECAP_BIN}" llm smoke \
    --agent "${agent}" \
    --model-profile "${profile}" \
    --timeout-seconds "${SMOKE_TIMEOUT}" > "${log_file}" 2>&1
  smoke_status=$?
  set -e

  model_line="$(grep -E "agent=${agent} " "${log_file}" | head -n 1 || true)"
  model_value="$(echo "${model_line}" | sed -n 's/.*model=\([^ ]*\).*/\1/p')"
  if [[ -z "${model_value}" ]]; then
    model_value="-"
  fi

  state_key="fail_count_${agent}_${profile}"
  previous_fail_count="$(get_state "${state_key}" "0")"
  current_fail_count=0
  result="passed"
  failure_class="-"
  trigger_note="-"

  if (( smoke_status != 0 )); then
    result="failed"
    failure_class="$(classify_failure "${log_file}")"
    if [[ "${failure_class}" == "access_or_auth" || "${failure_class}" == "billing_or_quota" || "${failure_class}" == "timeout_or_probe" ]]; then
      # Non-model failures must not accumulate toward model-refresh decisions.
      set_state "${state_key}" "0"
      current_fail_count=0
      blocking_failures=$((blocking_failures + 1))
      trigger_note="blocked:${failure_class}"
    else
      current_fail_count=$((previous_fail_count + 1))
      set_state "${state_key}" "${current_fail_count}"
    fi

    if [[ "${failure_class}" == "model_not_available" ]]; then
      trigger_note="model_not_available"
      add_trigger "model_not_available:${agent}:${profile}"
    elif (( current_fail_count >= 2 )); then
      trigger_note="consecutive_failures"
      add_trigger "consecutive_failure:${agent}:${profile}:count=${current_fail_count}"
    fi
  else
    set_state "${state_key}" "0"
  fi

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "${agent}" \
    "${profile}" \
    "${model_value}" \
    "${result}" \
    "${failure_class}" \
    "${current_fail_count}" \
    "${trigger_note}" >> "${matrix_tsv}"
done

refresh_status=0
refresh_output_file="${run_dir}/refresh_agent_output.log"
prompt_file="${run_dir}/refresh_prompt.txt"

trigger_count="$(grep -c '.*' "${triggers_file}" || true)"
if (( trigger_count > 0 )) && (( RUN_REFRESH == 1 )); then
  refresh_prompt_file "${prompt_file}"
  if ! run_refresh "${REFRESH_AGENT}" "${prompt_file}" "${refresh_output_file}"; then
    refresh_status=$?
  fi
fi

report_file="${REPORT_DIR}/model_refresh_report_${timestamp}.md"
{
  echo "# Model Watchdog Report (${timestamp})"
  echo
  echo "- Repo: \`${REPO_ROOT}\`"
  echo "- Command: \`${NEWS_RECAP_BIN}\`"
  echo "- Smoke timeout: \`${SMOKE_TIMEOUT}\` sec"
  echo "- Run refresh: \`${RUN_REFRESH}\`"
  echo "- Refresh agent: \`${REFRESH_AGENT}\`"
  echo
  echo "## Triggers"
  if (( trigger_count == 0 )); then
    echo "- none"
  else
    while IFS= read -r line; do
      [[ -z "${line}" ]] && continue
      echo "- ${line}"
    done < "${triggers_file}"
  fi
  echo
  echo "## Blocking Failures"
  echo "- access/auth or billing/quota failures: \`${blocking_failures}\`"
  echo
  echo "## Smoke Matrix"
  echo
  echo "| Agent | Profile | Model | Result | Failure Class | Consecutive Failures | Trigger Note |"
  echo "| --- | --- | --- | --- | --- | --- | --- |"
  while IFS=$'\t' read -r a p m r fc cf tn; do
    echo "| ${a} | ${p} | ${m} | ${r} | ${fc} | ${cf} | ${tn} |"
  done < "${matrix_tsv}"
  echo
  echo "## Agent Versions"
  echo
  echo "| Agent | Version |"
  echo "| --- | --- |"
  while IFS=$'\t' read -r a v; do
    echo "| ${a} | ${v} |"
  done < "${versions_file}"
  echo
  echo "## Artifacts"
  echo "- Run directory: \`${run_dir}\`"
  echo "- Smoke logs: \`${run_dir}/*.log\`"
  if (( RUN_REFRESH == 1 )) && [[ -f "${prompt_file}" ]]; then
    echo "- Prompt file: \`${prompt_file}\`"
  fi
  if (( RUN_REFRESH == 1 )); then
    echo "- Refresh output: \`${refresh_output_file}\` (exit=\`${refresh_status}\`)"
  fi
} > "${report_file}"

echo "Model watchdog report: ${report_file}"

exit_code=0
if (( trigger_count > 0 )) && (( RUN_REFRESH == 0 )); then
  echo "Refresh recommended (run with --run-refresh)." >&2
  exit_code=10
fi
if (( RUN_REFRESH == 1 )) && (( refresh_status != 0 )); then
  echo "Refresh run failed (see ${refresh_output_file})." >&2
  exit_code=11
fi
if (( blocking_failures > 0 )) && (( exit_code == 0 )); then
  echo "Blocking auth/quota failures detected; refresh mapping skipped." >&2
  exit_code=12
fi

exit "${exit_code}"
