from __future__ import annotations

import ast
import subprocess
from pathlib import Path

EXPECTED_HEAD = "e7115af398478e6bc3fc639ec958f0fa276fe458"
PATCHER = Path("apply_stage74_inventory_costing.py")
DRIVER = Path("wa_backend/api/driver.py")
TARGET_LABEL = "driver sale/sample split"


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


def require_clean(path: Path) -> None:
    if subprocess.run(
        ["git", "diff", "--quiet", "--", str(path)]
    ).returncode != 0:
        raise SystemExit(
            f"ERROR: {path} has unstaged changes. "
            "No project files were modified."
        )
    if subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", str(path)]
    ).returncode != 0:
        raise SystemExit(
            f"ERROR: {path} has staged changes. "
            "No project files were modified."
        )


def call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def string_constants(node: ast.Call) -> list[ast.Constant]:
    values: list[ast.Constant] = []
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            values.append(arg)
    for kw in node.keywords:
        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            values.append(kw.value)
    return values


def node_offsets(source: str, node: ast.AST) -> tuple[int, int]:
    if not all(
        hasattr(node, name)
        for name in ("lineno", "col_offset", "end_lineno", "end_col_offset")
    ):
        raise SystemExit("ERROR: Python AST did not expose exact source offsets.")

    lines = source.splitlines(keepends=True)

    def char_col(line: str, byte_col: int) -> int:
        raw = line.encode("utf-8")
        try:
            return len(raw[:byte_col].decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise SystemExit(
                "ERROR: could not map UTF-8 AST offsets safely."
            ) from exc

    start_line = int(node.lineno) - 1
    end_line = int(node.end_lineno) - 1

    start = sum(len(line) for line in lines[:start_line])
    start += char_col(lines[start_line], int(node.col_offset))

    end = sum(len(line) for line in lines[:end_line])
    end += char_col(lines[end_line], int(node.end_col_offset))
    return start, end


def expand_same_start_unique(
    text: str,
    value: str,
    chosen_start: int,
    *,
    stop_before: int | None,
) -> str:
    """Append complete following lines; the anchor start position never moves."""
    if not text.startswith(value, chosen_start):
        raise SystemExit("ERROR: chosen anchor occurrence is inconsistent.")

    candidate = value
    cursor = chosen_start + len(value)

    # We only append context. This keeps the start offset identical, which is
    # safe for the patcher's range slicing semantics.
    while text.count(candidate) != 1:
        if stop_before is not None and cursor >= stop_before:
            raise SystemExit(
                "ERROR: could not make the range anchor unique without "
                "crossing the opposite anchor."
            )
        newline = text.find("\n", cursor)
        if newline < 0:
            newline = len(text)
        else:
            newline += 1
        if stop_before is not None and newline > stop_before:
            newline = stop_before
        if newline <= cursor:
            raise SystemExit("ERROR: anchor expansion made no progress.")
        candidate = text[chosen_start:newline]
        cursor = newline

    return candidate


def main() -> None:
    if not PATCHER.is_file():
        raise SystemExit(
            f"ERROR: missing {PATCHER}. No files were modified."
        )
    if not DRIVER.is_file():
        raise SystemExit(
            f"ERROR: missing {DRIVER}. No files were modified."
        )

    head = run("git", "rev-parse", "HEAD")
    if head != EXPECTED_HEAD:
        raise SystemExit(
            f"ERROR: expected Stage 7.3 HEAD {EXPECTED_HEAD}, got {head}. "
            "No files were modified."
        )

    # The failed Stage 7.4 precheck must not have changed the actual driver.
    require_clean(DRIVER)

    patcher_source = PATCHER.read_text(encoding="utf-8")
    driver_source = DRIVER.read_text(encoding="utf-8")

    tree = ast.parse(patcher_source, filename=str(PATCHER))

    target_calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        constants = string_constants(node)
        if any(value.value == TARGET_LABEL for value in constants):
            target_calls.append(node)

    if len(target_calls) != 1:
        raise SystemExit(
            "ERROR: expected exactly one Stage 7.4 call labelled "
            f"{TARGET_LABEL!r}, found {len(target_calls)}. "
            "The patcher was not modified."
        )

    call = target_calls[0]
    helper = call_name(call)
    if not helper:
        raise SystemExit(
            "ERROR: could not identify the range helper used by the patcher."
        )

    helper_defs = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == helper
    ]
    if len(helper_defs) != 1:
        raise SystemExit(
            f"ERROR: expected one helper definition for {helper!r}; "
            f"found {len(helper_defs)}."
        )

    helper_source = ast.get_source_segment(
        patcher_source,
        helper_defs[0],
    ) or ""

    # Safety invariant: only auto-fix a helper that slices replacement from
    # anchor start positions. If it consumes end-anchor length, expanding an
    # anchor could accidentally remove extra code.
    dangerous_tokens = (
        "len(end_anchor)",
        "len(end)",
        "len(stop)",
        "len(end_marker)",
    )
    if any(token in helper_source for token in dangerous_tokens):
        raise SystemExit(
            "ERROR: the Stage 7.4 range helper consumes end-anchor length. "
            "Automatic anchor widening was refused; no files were modified."
        )

    constants = [
        node
        for node in string_constants(call)
        if node.value != TARGET_LABEL
    ]

    # Anchor literals are the direct string arguments that already occur in
    # current driver.py. Replacement bodies normally do not occur verbatim.
    anchor_nodes = [
        node
        for node in constants
        if node.value and driver_source.count(node.value) > 0
    ]

    if len(anchor_nodes) != 2:
        details = [
            (str(node.value)[:120], driver_source.count(str(node.value)))
            for node in constants
        ]
        raise SystemExit(
            "ERROR: could not identify exactly two live driver range anchors. "
            f"Candidates={details!r}. No files were modified."
        )

    first, second = anchor_nodes
    start_value = str(first.value)
    end_value = str(second.value)

    start_positions: list[int] = []
    pos = driver_source.find(start_value)
    while pos >= 0:
        start_positions.append(pos)
        pos = driver_source.find(start_value, pos + 1)

    end_positions: list[int] = []
    pos = driver_source.find(end_value)
    while pos >= 0:
        end_positions.append(pos)
        pos = driver_source.find(end_value, pos + 1)

    valid_pairs = [
        (s, e)
        for s in start_positions
        for e in end_positions
        if e > s
    ]
    if not valid_pairs:
        raise SystemExit(
            "ERROR: Stage 7.4 driver anchors have no valid ordered range."
        )

    # The intended surgical range is the nearest ordered pair. This remains
    # fail-closed if two pairs have the same shortest span.
    min_span = min(e - s for s, e in valid_pairs)
    nearest = [
        (s, e)
        for s, e in valid_pairs
        if e - s == min_span
    ]
    if len(nearest) != 1:
        raise SystemExit(
            "ERROR: driver sale/sample split remains ambiguous even after "
            "relative ordering analysis. No files were modified."
        )
    chosen_start, chosen_end = nearest[0]

    new_start = start_value
    new_end = end_value

    if driver_source.count(start_value) != 1:
        new_start = expand_same_start_unique(
            driver_source,
            start_value,
            chosen_start,
            stop_before=chosen_end,
        )

    if driver_source.count(end_value) != 1:
        new_end = expand_same_start_unique(
            driver_source,
            end_value,
            chosen_end,
            stop_before=None,
        )

    if (
        driver_source.count(new_start) != 1
        or driver_source.count(new_end) != 1
    ):
        raise SystemExit(
            "ERROR: repaired anchors are still not unique. "
            "No files were modified."
        )

    replacements: list[tuple[int, int, str]] = []
    if new_start != start_value:
        start, end = node_offsets(patcher_source, first)
        replacements.append((start, end, repr(new_start)))
    if new_end != end_value:
        start, end = node_offsets(patcher_source, second)
        replacements.append((start, end, repr(new_end)))

    if not replacements:
        raise SystemExit(
            "ERROR: both driver anchors are already unique, so this is not "
            "the expected failure shape. No files were modified."
        )

    updated = patcher_source
    for start, end, literal in sorted(
        replacements,
        key=lambda item: item[0],
        reverse=True,
    ):
        updated = updated[:start] + literal + updated[end:]

    compile(updated, str(PATCHER), "exec")

    # Re-parse and re-identify the labelled call after the edit.
    updated_tree = ast.parse(updated, filename=str(PATCHER))
    updated_calls = []
    for node in ast.walk(updated_tree):
        if isinstance(node, ast.Call):
            values = string_constants(node)
            if any(value.value == TARGET_LABEL for value in values):
                updated_calls.append(node)
    if len(updated_calls) != 1:
        raise SystemExit(
            "ERROR: repaired patcher lost the unique labelled call. "
            "No files were modified."
        )

    temp = PATCHER.with_suffix(
        PATCHER.suffix + ".driver-anchor-fix.tmp"
    )
    try:
        temp.write_text(updated, encoding="utf-8")
        temp.replace(PATCHER)
    finally:
        if temp.exists():
            temp.unlink()

    print("STAGE74_DRIVER_SPLIT_ANCHORS_FIXED_OK")
    print(f"HELPER={helper}")
    print(f"START_COUNT_BEFORE={len(start_positions)}")
    print(f"END_COUNT_BEFORE={len(end_positions)}")
    print("START_COUNT_AFTER=1")
    print("END_COUNT_AFTER=1")


if __name__ == "__main__":
    main()
