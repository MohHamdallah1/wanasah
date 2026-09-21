from __future__ import annotations

import ast
import hashlib
import subprocess
from pathlib import Path

BASELINE_COMMIT = "6f437e7606210bb6328dc97da7f275ee52f5146a"
WAREHOUSE_REPO_PATH = "wa_backend/api/warehouse.py"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
MONOLITH = BACKEND_ROOT / "api" / "warehouse.py"
PACKAGE_DIR = BACKEND_ROOT / "api" / "warehouse"

_STRUCTURAL_ASSIGNMENTS = {"router", "logger"}


def _fail(message: str) -> None:
    print(f"WAREHOUSE_SPLIT_INTEGRITY=FAIL: {message}")
    raise SystemExit(1)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git_show_text(commit: str, repo_path: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "show", f"{commit}:{repo_path}"],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        _fail(f"could not read baseline {commit}:{repo_path}: {exc}")


def _source_block(source: str, node: ast.AST) -> str:
    lines = source.splitlines(keepends=True)
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", None)
    if not isinstance(start, int) or not isinstance(end, int):
        _fail("AST node is missing source positions")

    decorators = getattr(node, "decorator_list", None)
    if decorators:
        decorator_lines = [
            getattr(item, "lineno", start)
            for item in decorators
            if isinstance(getattr(item, "lineno", None), int)
        ]
        if decorator_lines:
            start = min([start, *decorator_lines])

    return "".join(lines[start - 1 : end])


def _assignment_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Assign):
        names: list[str] = []
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
        return names
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def _protected_symbols(source: str) -> dict[str, str]:
    tree = ast.parse(source)
    result: dict[str, str] = {}

    for node in tree.body:
        keys: list[str] = []

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            keys = [f"function:{node.name}"]
        elif isinstance(node, ast.ClassDef):
            keys = [f"class:{node.name}"]
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            keys = [
                f"assignment:{name}"
                for name in _assignment_names(node)
                if name not in _STRUCTURAL_ASSIGNMENTS
            ]

        if not keys:
            continue

        block_hash = _sha256(_source_block(source, node))
        for key in keys:
            if key in result:
                _fail(f"duplicate protected symbol in one source: {key}")
            result[key] = block_hash

    return result


def _collect_staged_symbols() -> dict[str, str]:
    if not PACKAGE_DIR.exists():
        return {}

    result: dict[str, str] = {}
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue

        source = path.read_text(encoding="utf-8")
        for key, digest in _protected_symbols(source).items():
            if key in result:
                _fail(f"duplicate staged protected symbol: {key}")
            result[key] = digest

    return result


def main() -> None:
    baseline_source = _git_show_text(BASELINE_COMMIT, WAREHOUSE_REPO_PATH)
    baseline_symbols = _protected_symbols(baseline_source)

    if MONOLITH.exists():
        current_source = MONOLITH.read_text(encoding="utf-8")
        if _sha256(current_source) != _sha256(baseline_source):
            _fail(
                "wa_backend/api/warehouse.py changed from the approved stable baseline"
            )

        staged_symbols = _collect_staged_symbols()
        unknown = sorted(set(staged_symbols) - set(baseline_symbols))
        if unknown:
            _fail(
                "staged modules introduced protected symbols not present in the baseline: "
                + ", ".join(unknown)
            )

        changed = sorted(
            key
            for key, digest in staged_symbols.items()
            if baseline_symbols.get(key) != digest
        )
        if changed:
            _fail(
                "staged protected symbols differ from the baseline: "
                + ", ".join(changed)
            )

        print(
            "WAREHOUSE_SPLIT_INTEGRITY=PASS "
            f"(staging mode; baseline locked; staged={len(staged_symbols)}/"
            f"{len(baseline_symbols)})"
        )
        return

    if not PACKAGE_DIR.is_dir():
        _fail("neither warehouse.py nor warehouse package exists")

    package_init = PACKAGE_DIR / "__init__.py"
    if not package_init.is_file():
        _fail("final package mode requires wa_backend/api/warehouse/__init__.py")

    split_symbols = _collect_staged_symbols()

    missing = sorted(set(baseline_symbols) - set(split_symbols))
    unknown = sorted(set(split_symbols) - set(baseline_symbols))
    changed = sorted(
        key
        for key, digest in split_symbols.items()
        if baseline_symbols.get(key) != digest
    )

    if missing:
        _fail("missing protected symbols after split: " + ", ".join(missing))
    if unknown:
        _fail(
            "new protected symbols appeared during structure-only split: "
            + ", ".join(unknown)
        )
    if changed:
        _fail(
            "protected symbols changed during structure-only split: "
            + ", ".join(changed)
        )

    print(
        "WAREHOUSE_SPLIT_INTEGRITY=PASS "
        f"(final package mode; protected={len(split_symbols)})"
    )


if __name__ == "__main__":
    main()
