from __future__ import annotations

import re
import subprocess
from pathlib import Path

EXPECTED_HEAD = "e7115af398478e6bc3fc639ec958f0fa276fe458"
PATCHER = Path("apply_stage74_inventory_costing.py")

PAIR_RE = re.compile(
    r'(?P<q1>["\'])(?P<path>[^"\'\r\n]+)(?P=q1)'
    r'(?P<between>\s*[:,]\s*)'
    r'(?P<q2>["\'])(?P<hash>[0-9a-f]{40}|[0-9a-f]{64})(?P=q2)'
)


def run(*args: str) -> str:
    proc = subprocess.run(
        args,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            "ERROR running: "
            + " ".join(args)
            + "\n"
            + proc.stderr
        )
    return proc.stdout.strip()


def tracked(path: str) -> bool:
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"HEAD:{path}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.returncode == 0


def require_clean(path: str) -> None:
    if subprocess.run(
        ["git", "diff", "--quiet", "--", path]
    ).returncode != 0:
        raise SystemExit(
            f"ERROR: {path} has unstaged changes. "
            "No files were modified."
        )
    if subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", path]
    ).returncode != 0:
        raise SystemExit(
            f"ERROR: {path} has staged changes. "
            "No files were modified."
        )


def raw_git_hash(path: str) -> str:
    # Match the Stage 7.4 patcher's current precheck exactly:
    # hash the working-tree bytes as Git would, including CRLF on Windows.
    return run("git", "hash-object", "--", path)


def main() -> None:
    if not PATCHER.is_file():
        raise SystemExit(
            f"ERROR: missing {PATCHER}. No files were modified."
        )

    head = run("git", "rev-parse", "HEAD")
    if head != EXPECTED_HEAD:
        raise SystemExit(
            f"ERROR: expected Stage 7.3 HEAD {EXPECTED_HEAD}, got {head}. "
            "No files were modified."
        )

    source = PATCHER.read_text(encoding="utf-8")

    path_hashes: dict[str, str] = {}
    for match in PAIR_RE.finditer(source):
        path = match.group("path")
        if not tracked(path):
            continue
        require_clean(path)
        path_hashes[path] = raw_git_hash(path)

    if not path_hashes:
        raise SystemExit(
            "ERROR: could not find tracked baseline path/hash pairs "
            "inside the Stage 7.4 patcher. No files were modified."
        )

    updated = source
    updated_count = 0

    for path, expected_hash in path_hashes.items():
        pattern = re.compile(
            r'(?P<q1>["\'])'
            + re.escape(path)
            + r'(?P=q1)'
            r'(?P<between>\s*[:,]\s*)'
            r'(?P<q2>["\'])'
            r'(?P<hash>[0-9a-f]{40}|[0-9a-f]{64})'
            r'(?P=q2)'
        )

        def repl(match: re.Match[str]) -> str:
            nonlocal updated_count
            updated_count += 1
            return (
                f"{match.group('q1')}{path}{match.group('q1')}"
                f"{match.group('between')}"
                f"{match.group('q2')}{expected_hash}{match.group('q2')}"
            )

        updated, count = pattern.subn(repl, updated)
        if count == 0:
            raise SystemExit(
                f"ERROR: failed to update baseline for {path}. "
                "No files were modified."
            )

    compile(updated, str(PATCHER), "exec")

    tmp = PATCHER.with_suffix(
        PATCHER.suffix + ".baseline-v2.tmp"
    )
    try:
        tmp.write_text(updated, encoding="utf-8")
        tmp.replace(PATCHER)
    finally:
        if tmp.exists():
            tmp.unlink()

    print("STAGE74_PATCHER_BASELINES_V2_FIXED_OK")
    print(f"HEAD={EXPECTED_HEAD}")
    print(f"BASELINES_FIXED={len(path_hashes)}")
    print(f"LITERALS_UPDATED={updated_count}")


if __name__ == "__main__":
    main()
