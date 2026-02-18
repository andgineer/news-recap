#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(pwd)"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="agent_checks/research_${RUN_ID}"

mkdir -p "${OUT_DIR}/tasks" "${OUT_DIR}/results" "${OUT_DIR}/logs" "${OUT_DIR}/meta"

if [[ -f "agent_checks/shared_task_input.txt" ]]; then
  cp "agent_checks/shared_task_input.txt" "${OUT_DIR}/shared_task_input.txt"
else
  cat > "${OUT_DIR}/shared_task_input.txt" <<'EOF'
News Recap agent validation input.
This file must be read by the agent.
Token: 00000000-0000-0000-0000-000000000000
EOF
fi

echo -e "case_id\tagent\tmode\titeration\ttask_path\tresult_path" > "${OUT_DIR}/meta/cases.tsv"

run_case() {
  local case_id="$1"
  local timeout_s="$2"
  shift 2

  local stdout_path="${OUT_DIR}/logs/${case_id}.out"
  local stderr_path="${OUT_DIR}/logs/${case_id}.err"
  local exit_path="${OUT_DIR}/meta/${case_id}.exit"

  echo "[run] ${case_id}"
  if perl -e 'alarm shift @ARGV; exec @ARGV' "${timeout_s}" "$@" > "${stdout_path}" 2> "${stderr_path}"; then
    echo "0" > "${exit_path}"
  else
    echo "$?" > "${exit_path}"
  fi
}

write_task() {
  local agent="$1"
  local token="$2"
  local result_rel="$3"
  local task_path="$4"

  cat > "${task_path}" <<EOF
Read this task file and execute it.

1) Read file: ${OUT_DIR}/shared_task_input.txt
2) Fetch URL exactly:
https://httpbin.org/get?token=${token}
3) Create file: ${result_rel}
with exact format:
AGENT: ${agent}
URL: <url>
ORIGIN: <origin>
DONE: yes

If URL is unreachable, write EXACTLY:
AGENT: ${agent}
URL: unreachable
ORIGIN: unreachable
DONE: no

Return one line: CREATED ${result_rel}
EOF
}

prompt_for_task() {
  local task_path="$1"
  printf 'Read and execute instructions from file %s. Work with files in the current directory and create the required output file.' "${task_path}"
}

run_claude_matrix() {
  local -a modes=("default" "acceptEdits" "dontAsk" "bypassPermissions")
  local mode
  local i
  for mode in "${modes[@]}"; do
    for i in 1 2 3 4 5; do
      local case_id="claude_${mode}_${i}"
      local token
      token="$(uuidgen | tr '[:upper:]' '[:lower:]')"
      local task_rel="${OUT_DIR}/tasks/${case_id}.txt"
      local result_rel="${OUT_DIR}/results/${case_id}.txt"
      local prompt

      write_task "claude" "${token}" "${result_rel}" "${task_rel}"
      prompt="$(prompt_for_task "${task_rel}")"
      echo -e "${case_id}\tclaude\t${mode}\t${i}\t${task_rel}\t${result_rel}" >> "${OUT_DIR}/meta/cases.tsv"

      case "${mode}" in
        default)
          run_case "${case_id}" 150 claude -p --permission-mode default "${prompt}"
          ;;
        acceptEdits)
          run_case "${case_id}" 150 claude -p --permission-mode acceptEdits "${prompt}"
          ;;
        dontAsk)
          run_case "${case_id}" 150 claude -p --permission-mode dontAsk \
            --allowed-tools "Read,Write,Edit,WebFetch,Bash(curl:*),Bash(cat:*),Bash(shasum:*),Bash(pwd:*),Bash(ls:*)" \
            -- "${prompt}"
          ;;
        bypassPermissions)
          run_case "${case_id}" 150 claude -p --permission-mode bypassPermissions "${prompt}"
          ;;
      esac
    done
  done
}

run_codex_matrix() {
  local -a modes=("default" "workspace_write" "danger_full_access" "bypass_all")
  local mode
  local i
  for mode in "${modes[@]}"; do
    for i in 1 2 3; do
      local case_id="codex_${mode}_${i}"
      local token
      token="$(uuidgen | tr '[:upper:]' '[:lower:]')"
      local task_rel="${OUT_DIR}/tasks/${case_id}.txt"
      local result_rel="${OUT_DIR}/results/${case_id}.txt"
      local prompt

      write_task "codex" "${token}" "${result_rel}" "${task_rel}"
      prompt="$(prompt_for_task "${task_rel}")"
      echo -e "${case_id}\tcodex\t${mode}\t${i}\t${task_rel}\t${result_rel}" >> "${OUT_DIR}/meta/cases.tsv"

      case "${mode}" in
        default)
          run_case "${case_id}" 180 codex exec "${prompt}"
          ;;
        workspace_write)
          run_case "${case_id}" 180 codex exec --sandbox workspace-write "${prompt}"
          ;;
        danger_full_access)
          run_case "${case_id}" 180 codex exec --sandbox danger-full-access "${prompt}"
          ;;
        bypass_all)
          run_case "${case_id}" 180 codex exec --dangerously-bypass-approvals-and-sandbox "${prompt}"
          ;;
      esac
    done
  done
}

run_gemini_matrix() {
  local -a modes=("default" "auto_edit" "yolo")
  local mode
  local i
  for mode in "${modes[@]}"; do
    for i in 1 2 3 4 5; do
      local case_id="gemini_${mode}_${i}"
      local token
      token="$(uuidgen | tr '[:upper:]' '[:lower:]')"
      local task_rel="${OUT_DIR}/tasks/${case_id}.txt"
      local result_rel="${OUT_DIR}/results/${case_id}.txt"
      local prompt

      write_task "gemini" "${token}" "${result_rel}" "${task_rel}"
      prompt="$(prompt_for_task "${task_rel}")"
      echo -e "${case_id}\tgemini\t${mode}\t${i}\t${task_rel}\t${result_rel}" >> "${OUT_DIR}/meta/cases.tsv"

      case "${mode}" in
        default)
          run_case "${case_id}" 150 gemini "${prompt}"
          ;;
        auto_edit)
          run_case "${case_id}" 150 gemini --approval-mode auto_edit "${prompt}"
          ;;
        yolo)
          run_case "${case_id}" 150 gemini --approval-mode yolo "${prompt}"
          ;;
      esac
    done
  done
}

summarize_results() {
  python - "${OUT_DIR}" <<'PY'
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

out_dir = Path(sys.argv[1])
cases_path = out_dir / "meta" / "cases.tsv"

cases: list[dict[str, str]] = []
with cases_path.open("r", encoding="utf-8") as handle:
    header = next(handle, "")
    for line in handle:
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 6:
            continue
        case_id, agent, mode, iteration, task_path, result_path = parts
        cases.append(
            {
                "case_id": case_id,
                "agent": agent,
                "mode": mode,
                "iteration": iteration,
                "task_path": task_path,
                "result_path": result_path,
            }
        )

def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.rstrip("\n") for line in path.read_text("utf-8", errors="replace").splitlines()]

def parse_result(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in read_lines(path):
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip().upper()] = value.strip()
    return data

rows: list[dict[str, object]] = []
aggregate: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"total": 0, "pass": 0})

for case in cases:
    case_id = case["case_id"]
    result_path = Path(case["result_path"])
    exit_path = out_dir / "meta" / f"{case_id}.exit"
    stdout_path = out_dir / "logs" / f"{case_id}.out"
    stderr_path = out_dir / "logs" / f"{case_id}.err"

    exit_code = None
    if exit_path.exists():
        try:
            exit_code = int(exit_path.read_text("utf-8").strip())
        except ValueError:
            exit_code = None

    parsed = parse_result(result_path)
    url = parsed.get("URL", "")
    origin = parsed.get("ORIGIN", "")
    done = parsed.get("DONE", "").lower()
    has_result = result_path.exists()
    pass_netproof = (
        has_result
        and url.startswith("https://httpbin.org/get?token=")
        and origin not in {"", "unreachable"}
        and done == "yes"
    )

    key = (case["agent"], case["mode"])
    aggregate[key]["total"] += 1
    if pass_netproof:
        aggregate[key]["pass"] += 1

    stderr_preview = read_lines(stderr_path)[:1]
    stdout_preview = read_lines(stdout_path)[:1]
    rows.append(
        {
            **case,
            "exit_code": exit_code,
            "has_result_file": has_result,
            "result_url": url,
            "result_origin": origin,
            "result_done": done,
            "pass_netproof": pass_netproof,
            "stdout_first_line": stdout_preview[0] if stdout_preview else "",
            "stderr_first_line": stderr_preview[0] if stderr_preview else "",
        }
    )

summary_json = out_dir / "meta" / "summary.json"
summary_json.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2), "utf-8")

summary_md = out_dir / "summary.md"
lines = [
    "# Agent Execution Research Summary",
    "",
    f"Run directory: `{out_dir}`",
    "",
    "## Aggregated Pass Rate (netproof)",
    "",
    "| Agent | Mode | Pass | Total |",
    "|---|---|---:|---:|",
]
for (agent, mode), stats in sorted(aggregate.items()):
    lines.append(f"| {agent} | {mode} | {stats['pass']} | {stats['total']} |")

lines.extend(
    [
        "",
        "## Notes",
        "",
        "- `pass_netproof=true` means output file exists and contains valid URL/origin from live response.",
        "- Inspect per-case logs under `logs/*.out` and `logs/*.err`.",
    ]
)

summary_md.write_text("\n".join(lines) + "\n", "utf-8")
print(summary_md)
PY
}

run_claude_matrix
run_codex_matrix
run_gemini_matrix
summary_path="$(summarize_results)"

echo ""
echo "Research run completed."
echo "OUT_DIR=${OUT_DIR}"
echo "SUMMARY=${summary_path}"
