from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

EXPECTED_HEAD = "e7115af398478e6bc3fc639ec958f0fa276fe458"
PATCHER = Path("apply_stage74_inventory_costing.py")

PAIR_RE = re.compile(
    r'(?P<q1>["\'])(?P<path>[^"\'\r\n]+)(?P=q1)'
    r'(?P<between>\s*[:,]\s*)'
    r'(?P<q2>["\'])(?P<sha>[0-9a-f]{40})(?P=q2)'
)


def run_bytes(*args: str) -> bytes:
    proc = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(args)}\n"
            + proc.stderr.decode("utf-8", errors="replace")
        )
    return proc.stdout


def run_text(*args: str) -> str:
    return run_bytes(*args).decode(
        "utf-8",
        errors="replace",
    ).strip()


def is_tracked_at_head(path: str) -> bool:
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"HEAD:{path}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.returncode == 0


def require_clean(path: str) -> None:
    for args, label in (
        (["git", "diff", "--quiet", "--", path], "unstaged"),
        (["git", "diff", "--cached", "--quiet", "--", path], "staged"),
    ):
        proc = subprocess.run(args)
        if proc.returncode != 0:
            raise SystemExit(
                f"ERROR: {path} has {label} changes. "
                "The Stage 7.4 baseline fixer will not bless modified project files."
            )


def main() -> None:
    if not PATCHER.is_file():
        raise SystemExit(
            f"ERROR: {PATCHER} was not found in the repository root."
        )

    head = run_text("git", "rev-parse", "HEAD")
    if head != EXPECTED_HEAD:
        raise SystemExit(
            "ERROR: expected exact Stage 7.3 baseline "
            f"{EXPECTED_HEAD}, got {head}. No files were modified."
        )

    source = PATCHER.read_text(encoding="utf-8")
    replacements: dict[str, tuple[str, str]] = {}

    for match in PAIR_RE.finditer(source):
        path = match.group("path")
        old_sha = match.group("sha")

        if not is_tracked_at_head(path):
            continue

        file_path = Path(path)
        if not file_path.is_file():
            raise SystemExit(
                f"ERROR: baseline file {path} is missing locally."
            )

        require_clean(path)

        # The broken patcher stored Git blob SHA-1 values (40 chars)
        # but compared them to SHA-256 of working-tree bytes (64 chars).
        # Because git confirms the file is clean against Stage 7.3,
        # using the working-tree SHA-256 is safe and EOL-aware.
        new_sha = hashlib.sha256(
            file_path.read_bytes()
        ).hexdigest()

        replacements[path] = (old_sha, new_sha)

    if not replacements:
        raise SystemExit(
            "ERROR: no Git-blob baseline entries were detected. "
            "The patcher shape is not the expected one; nothing was changed."
        )

    updated = source
    changed = 0
    for path, (old_sha, new_sha) in replacements.items():
        # Replace only path-associated pairs, not arbitrary 40-char strings.
        pattern = re.compile(
            r'(?P<q1>["\'])'
            + re.escape(path)
            + r'(?P=q1)'
            r'(?P<between>\s*[:,]\s*)'
            r'(?P<q2>["\'])'
            + re.escape(old_sha)
            + r'(?P=q2)'
        )

        def repl(match: re.Match[str]) -> str:
            nonlocal changed
            changed += 1
            return (
                f"{match.group('q1')}{path}{match.group('q1')}"
                f"{match.group('between')}"
                f"{match.group('q2')}{new_sha}{match.group('q2')}"
            )

        updated, count = pattern.subn(repl, updated)
        if count == 0:
            raise SystemExit(
                f"ERROR: could not surgically update baseline for {path}."
            )

    compile(updated, str(PATCHER), "exec")

    tmp = PATCHER.with_suffix(
        PATCHER.suffix + ".baseline-fix.tmp"
    )
    try:
        tmp.write_text(
            updated,
            encoding="utf-8",
        )
        tmp.replace(PATCHER)
    finally:
        if tmp.exists():
            tmp.unlink()

    print("STAGE74_PATCHER_BASELINES_FIXED_OK")
    print(f"HEAD={EXPECTED_HEAD}")
    print(f"BASELINES_FIXED={len(replacements)}")
    print(f"LITERALS_UPDATED={changed}")


if __name__ == "__main__":
    main()
