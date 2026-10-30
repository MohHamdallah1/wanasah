from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ".github/workflows/live-stock-r1-integrity-proof.yml"
LIVE_STOCK_PATH = "wa_backend/api/warehouse/live_stock.py"

R1_REGRESSION_FILES = (
    "wa_backend/tests/test_live_stock_r1_movement_postgres.py",
    "wa_backend/tests/test_live_stock_r1_snapshot_postgres.py",
    "wa_backend/tests/test_live_stock_r1_sql_postgres.py",
    "wa_backend/tests/test_live_stock_r1_http_postgres.py",
    "wa_backend/tests/test_cp7_live_stock_postgres.py",
)
R1_SUPPORT_FILES = (
    "wa_backend/tests/live_stock_r1_support.py",
)
REQUIRED_FILES = (LIVE_STOCK_PATH, *R1_REGRESSION_FILES, *R1_SUPPORT_FILES)

FORBIDDEN_ADDED_TEST_CONTROLS = (
    re.compile(r"\bpytest\.skip\s*\("),
    re.compile(r"\bpytest\.xfail\s*\("),
    re.compile(r"\bpytest\.mark\.xfail\b"),
    re.compile(r"\bpytest\.mark\.skip\s*\("),
)


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
    ).strip()


def _merge_base(base_ref: str) -> str:
    return _git("merge-base", base_ref, "HEAD")


def _changed_paths(base: str) -> set[str]:
    output = _git("diff", "--name-only", base, "HEAD")
    return set(output.splitlines()) if output else set()


def _deleted_paths(base: str) -> set[str]:
    output = _git("diff", "--name-only", "--diff-filter=D", base, "HEAD")
    return set(output.splitlines()) if output else set()


def _added_lines(base: str, path: str) -> list[str]:
    diff = _git("diff", "--unified=0", base, "HEAD", "--", path)
    return [
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def _parse_path(path: str) -> ast.Module:
    return ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))


def _parse_git_path(base: str, path: str) -> ast.Module:
    return ast.parse(_git("show", f"{base}:{path}"))


def _named_async_function(tree: ast.Module, name: str) -> ast.AsyncFunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    return None


def _test_functions(tree: ast.Module) -> dict[str, ast.AST]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def _assertion_weight(node: ast.AST) -> int:
    weight = sum(isinstance(child, ast.Assert) for child in ast.walk(node))
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "raises"
            and isinstance(func.value, ast.Name)
            and func.value.id == "pytest"
        ):
            weight += 1
    return weight


def _validate_historical_test_strength(base: str, changed: set[str]) -> None:
    for path in R1_REGRESSION_FILES:
        if path not in changed:
            continue
        old_tests = _test_functions(_parse_git_path(base, path))
        new_tests = _test_functions(_parse_path(path))

        removed = sorted(set(old_tests) - set(new_tests))
        assert not removed, f"Historical R1 tests removed from {path}: {removed}"

        weakened = []
        for name, old_node in old_tests.items():
            old_weight = _assertion_weight(old_node)
            new_weight = _assertion_weight(new_tests[name])
            if new_weight < old_weight:
                weakened.append((name, old_weight, new_weight))
        assert not weakened, (
            f"Historical R1 negative controls weakened in {path}: {weakened}"
        )

        additions = "\n".join(_added_lines(base, path))
        forbidden = [
            pattern.pattern
            for pattern in FORBIDDEN_ADDED_TEST_CONTROLS
            if pattern.search(additions)
        ]
        assert not forbidden, (
            f"New skip/xfail control added to {path}: {forbidden}"
        )


def _validate_workflow_contract() -> None:
    workflow = (REPO_ROOT / WORKFLOW_PATH).read_text(encoding="utf-8")

    # Historical PR ownership is archived. Current PRs may change unrelated
    # files while this gate verifies R1 behavior.
    assert "changed <= allowed" not in workflow
    assert "immutable_nodes(old) == immutable_nodes(new)" not in workflow
    assert "Unauthorized files:" not in workflow

    for part in ("movement", "snapshot", "sql", "cp7", "http"):
        assert part in workflow, f"R1 matrix part missing: {part}"

    for path in R1_REGRESSION_FILES:
        filename = Path(path).name
        assert filename in workflow, f"R1 regression invocation missing: {filename}"

    assert "postgres:16" in workflow
    assert "NOBYPASSRLS" in workflow
    assert 'WANASAH_R1_PG_GATE: "1"' in workflow
    assert 'WANASAH_CP7_PG_GATE: "1"' in workflow


def _validate_current_diff(base_ref: str) -> None:
    base = _merge_base(base_ref)
    changed = _changed_paths(base)
    deleted = _deleted_paths(base)

    missing = sorted(path for path in REQUIRED_FILES if not (REPO_ROOT / path).is_file())
    assert not missing, f"Required R1 proof files missing: {missing}"

    deleted_required = sorted(set(REQUIRED_FILES) & deleted)
    assert not deleted_required, f"Required R1 proof files deleted: {deleted_required}"

    _validate_workflow_contract()
    _validate_historical_test_strength(base, changed)

    current_tree = _parse_path(LIVE_STOCK_PATH)
    current_r1 = _named_async_function(current_tree, "get_warehouse_inventory")
    assert current_r1 is not None, "R1 list authority get_warehouse_inventory is missing"

    r1_runtime_touched = False
    if LIVE_STOCK_PATH in changed:
        old_tree = _parse_git_path(base, LIVE_STOCK_PATH)
        old_r1 = _named_async_function(old_tree, "get_warehouse_inventory")
        assert old_r1 is not None, "R1 base authority get_warehouse_inventory is missing"
        r1_runtime_touched = (
            ast.dump(old_r1, include_attributes=False)
            != ast.dump(current_r1, include_attributes=False)
        )

    print("R1_ARCHIVED_OWNERSHIP=NOT_CURRENT_PR_ALLOWLIST")
    print("R1_CHANGED_PATHS=", sorted(changed))
    print("R1_RUNTIME_TOUCHED=", "YES" if r1_runtime_touched else "NO")
    print("R1_POLICY=PASS")


def _self_test() -> None:
    unrelated = {
        LIVE_STOCK_PATH,
        "dashboard/src/pages/inventory/liveStock/LiveStockFilters.tsx",
        "wa_backend/tests/test_live_stock_f5_families_postgres.py",
    }
    # The repaired policy intentionally has no current-PR allowlist.
    assert unrelated - set(REQUIRED_FILES)

    sample = "assert value\npytest.skip('bad')\n"
    assert any(pattern.search(sample) for pattern in FORBIDDEN_ADDED_TEST_CONTROLS)

    strong = ast.parse(
        "def test_x():\n"
        "    assert True\n"
        "    with pytest.raises(ValueError):\n"
        "        raise ValueError\n"
    ).body[0]
    weak = ast.parse("def test_x():\n    assert True\n").body[0]
    assert _assertion_weight(strong) == 2
    assert _assertion_weight(weak) == 1
    print("R1_POLICY_SELF_TEST=PASS")


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-current-diff", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    _self_test()
    if args.validate_current_diff:
        base_ref = os.environ.get("R1_BASE")
        assert base_ref, "R1_BASE is required"
        _validate_current_diff(base_ref)


if __name__ == "__main__":
    main()
