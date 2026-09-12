from __future__ import annotations

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
EXPECTED_HEAD = "291f6740329f6cac81620751e5eb48e9e72fc740"

EXPECTED = {
    "dashboard/src/pages/inventory/TabTransfers.tsx": "M",
    "dashboard/src/pages/inventory/transfers/TransferCreateModal.tsx": "??",
    "dashboard/src/pages/inventory/transfers/FefoOverrideEditor.tsx": "??",
    "dashboard/src/pages/inventory/transfers/hooks/useTransferCreate.ts": "??",
}

SCOPE = [
    "dashboard/src/pages/inventory/TabTransfers.tsx",
    "dashboard/src/pages/inventory/transfers",
]


def run(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            "TRANSFER_B2_DIFF_GATE=FAIL\n"
            f"COMMAND_FAILED={' '.join(args)}\n"
            f"{result.stderr.strip()}"
        )
    return result.stdout


def fail(message: str) -> None:
    raise SystemExit(f"TRANSFER_B2_DIFF_GATE=FAIL\n{message}")


head = run("rev-parse", "HEAD").strip()
if head != EXPECTED_HEAD:
    fail(
        f"HEAD_MISMATCH expected={EXPECTED_HEAD} actual={head}. "
        "Do not review B2 against a different baseline."
    )
print("B2_BASELINE_HEAD=OK")

check = subprocess.run(
    ["git", "diff", "--check", "--", *SCOPE],
    cwd=ROOT,
    text=True,
    capture_output=True,
)
if check.returncode != 0:
    fail("GIT_DIFF_CHECK=FAIL\n" + check.stdout + check.stderr)
print("GIT_DIFF_CHECK=OK")

status_raw = run(
    "status",
    "--porcelain",
    "--untracked-files=all",
    "--",
    *SCOPE,
)

actual: dict[str, str] = {}
for raw_line in status_raw.splitlines():
    if not raw_line:
        continue
    code = raw_line[:2]
    path = raw_line[3:].replace("\\", "/")
    normalized_code = "??" if code == "??" else code.strip()
    actual[path] = normalized_code

if actual != EXPECTED:
    lines = [
        "CHANGED_FILE_SET=FAIL",
        "EXPECTED:",
        *[f"  {status} {path}" for path, status in sorted(EXPECTED.items())],
        "ACTUAL:",
        *[f"  {status} {path}" for path, status in sorted(actual.items())],
    ]
    fail("\n".join(lines))

print("B2_CHANGED_FILE_SET=OK")
print("B2_NO_FILE_DELETIONS=OK")
print("B2_EXISTING_B1_FILES_UNTOUCHED=OK")

tab = ROOT / "dashboard/src/pages/inventory/TabTransfers.tsx"
hook = ROOT / "dashboard/src/pages/inventory/transfers/hooks/useTransferCreate.ts"
modal = ROOT / "dashboard/src/pages/inventory/transfers/TransferCreateModal.tsx"
fefo = ROOT / "dashboard/src/pages/inventory/transfers/FefoOverrideEditor.tsx"

for path in (tab, hook, modal, fefo):
    if not path.exists():
        fail(f"MISSING={path.relative_to(ROOT)}")

tab_lines = len(tab.read_text(encoding="utf-8").splitlines())
if tab_lines >= 260:
    fail(f"TAB_ORCHESTRATOR_TOO_LARGE={tab_lines}")
print(f"TAB_ORCHESTRATOR_LINES={tab_lines}")

# Show the tracked diff stat for human review as well.
print("GIT_DIFF_STAT_BEGIN")
print(run("diff", "--stat", "--", *SCOPE).rstrip())
print("GIT_DIFF_STAT_END")

print("TRANSFER_B2_DIFF_GATE=PASS")
