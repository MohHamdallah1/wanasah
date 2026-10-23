#!/usr/bin/env python3
"""Repository-wide guard against legacy flag/persona authorization reintroduction.

This gate intentionally scans Runtime source, not immutable migration history,
historical tests, documentation, or archived performance evidence. Canonical
CompanyOwner and the separate PlatformAdmin security realm are explicitly not
generic persona flags and remain permitted.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Iterable


FORBIDDEN_IDENTIFIERS = frozenset({
    "is_admin",
    "isAdmin",
    "legacy_is_admin",
    "legacyIsAdmin",
    "is_superuser",
    "isSuperuser",
    "is_manager",
    "isManager",
    "is_supervisor",
    "isSupervisor",
    "is_owner",
    "isOwner",
    "is_company_admin",
    "isCompanyAdmin",
    "admin_override",
    "adminOverride",
    "allow_admin",
    "allowAdmin",
    "allow_override",
    "allowOverride",
    "admin_mode",
    "adminMode",
})

GENERIC_PERSONA_VALUES = frozenset({
    "admin",
    "administrator",
    "manager",
    "owner",
    "superuser",
    "supervisor",
})

BACKEND_EXTENSIONS = frozenset({".py"})
DASHBOARD_EXTENSIONS = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"})
FLUTTER_EXTENSIONS = frozenset({".dart"})

EXCLUSION_DESCRIPTIONS = {
    "alembic_history": "immutable Alembic migration history",
    "backend_tests": "Backend tests and historical sentinels",
    "archived_perf_evidence": "archived backend performance evidence",
    "dashboard_tests": "Dashboard tests/fixtures",
}


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    code: str
    detail: str


@dataclass(frozen=True)
class ScanReport:
    scanned: tuple[str, ...]
    excluded_by_reason: dict[str, tuple[str, ...]]
    violations: tuple[Violation, ...]

    @property
    def scanned_by_surface(self) -> Counter[str]:
        counts: Counter[str] = Counter()
        for path in self.scanned:
            if path.startswith("wa_backend/"):
                counts["backend_and_workers"] += 1
            elif path.startswith("dashboard/src/"):
                counts["dashboard"] += 1
            elif path.startswith("wanasah_frontend/lib/"):
                counts["flutter"] += 1
        return counts


def _runtime_candidate(rel: Path) -> bool:
    posix = rel.as_posix()
    suffix = rel.suffix.lower()
    if posix.startswith("wa_backend/"):
        return suffix in BACKEND_EXTENSIONS
    if posix.startswith("dashboard/src/"):
        return suffix in DASHBOARD_EXTENSIONS
    if posix.startswith("wanasah_frontend/lib/"):
        return suffix in FLUTTER_EXTENSIONS
    return False


def _exclusion_reason(rel: Path) -> str | None:
    parts = rel.parts
    posix = rel.as_posix()

    if posix.startswith("wa_backend/alembic/versions/"):
        return "alembic_history"
    if posix.startswith("wa_backend/tests/"):
        return "backend_tests"
    if posix.startswith("wa_backend/perf_reports/"):
        return "archived_perf_evidence"

    if posix.startswith("dashboard/src/"):
        if any(part in {"test", "tests", "__tests__"} for part in parts):
            return "dashboard_tests"
        lowered = rel.name.lower()
        if ".test." in lowered or ".spec." in lowered:
            return "dashboard_tests"

    return None


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _strip_c_style_comments(text: str) -> str:
    """Remove // and /* */ comments while preserving strings and line numbers."""
    out: list[str] = []
    i = 0
    state = "code"
    quote = ""
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if state == "code":
            if ch in {"'", '"', "`"}:
                state = "string"
                quote = ch
                out.append(ch)
                i += 1
                continue
            if ch == "/" and nxt == "/":
                state = "line_comment"
                out.extend("  ")
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block_comment"
                out.extend("  ")
                i += 2
                continue
            out.append(ch)
            i += 1
            continue

        if state == "string":
            out.append(ch)
            if ch == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                state = "code"
                quote = ""
            i += 1
            continue

        if state == "line_comment":
            if ch == "\n":
                out.append("\n")
                state = "code"
            else:
                out.append(" ")
            i += 1
            continue

        if state == "block_comment":
            if ch == "*" and nxt == "/":
                out.extend("  ")
                i += 2
                state = "code"
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue

    return "".join(out)


def _role_like_expression(node: ast.AST) -> bool:
    try:
        rendered = ast.unparse(node).lower()
    except Exception:
        return False
    if "system_role" in rendered:
        return False
    return bool(
        re.search(
            r"(?:^|[^a-z0-9_])(?:role|user_role|actor_role|principal_role|persona)(?:[^a-z0-9_]|$)",
            rendered,
        )
    )


def _persona_literals(node: ast.AST) -> set[str]:
    values: set[str] = set()
    for part in ast.walk(node):
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            lowered = part.value.strip().lower()
            if lowered in GENERIC_PERSONA_VALUES:
                values.add(lowered)
    return values


def _python_violations(rel: Path, text: str) -> list[Violation]:
    path = rel.as_posix()
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as error:
        return [
            Violation(
                path,
                int(error.lineno or 1),
                "PYTHON_PARSE_ERROR",
                str(error.msg),
            )
        ]

    hits: set[tuple[int, str, str]] = set()

    def add(node: ast.AST, code: str, detail: str) -> None:
        hits.add((int(getattr(node, "lineno", 1)), code, detail))

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_IDENTIFIERS:
            add(node, "LEGACY_FLAG_IDENTIFIER", node.id)
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_IDENTIFIERS:
            add(node, "LEGACY_FLAG_ATTRIBUTE", node.attr)
        elif isinstance(node, ast.keyword) and node.arg in FORBIDDEN_IDENTIFIERS:
            add(node, "LEGACY_FLAG_KEYWORD", str(node.arg))
        elif isinstance(node, ast.Subscript):
            key = node.slice
            if isinstance(key, ast.Constant) and key.value in FORBIDDEN_IDENTIFIERS:
                add(node, "LEGACY_FLAG_KEY", str(key.value))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in FORBIDDEN_IDENTIFIERS:
                add(node, "LEGACY_FLAG_STRING_CONTRACT", node.value)
        elif isinstance(node, ast.Compare):
            expressions = [node.left, *node.comparators]
            role_side = any(_role_like_expression(expr) for expr in expressions)
            persona_values = set().union(*(_persona_literals(expr) for expr in expressions))
            if role_side and persona_values:
                add(
                    node,
                    "GENERIC_ROLE_PERSONA_AUTHORITY",
                    ",".join(sorted(persona_values)),
                )

    return [
        Violation(path, line, code, detail)
        for line, code, detail in sorted(hits)
    ]


_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])("
    + "|".join(re.escape(value) for value in sorted(FORBIDDEN_IDENTIFIERS, key=len, reverse=True))
    + r")(?![A-Za-z0-9_])"
)

_ROLE_COMPARE_PATTERNS = (
    re.compile(
        r"(?is)\b(?:role|userRole|user_role|actorRole|actor_role|principalRole|principal_role|persona)\b"
        r"[^\n;]{0,80}?(?:===|==|!==|!=)\s*['\"]"
        r"(admin|administrator|manager|owner|superuser|supervisor)['\"]"
    ),
    re.compile(
        r"(?is)['\"](admin|administrator|manager|owner|superuser|supervisor)['\"]"
        r"\s*(?:===|==|!==|!=)[^\n;]{0,80}?"
        r"\b(?:role|userRole|user_role|actorRole|actor_role|principalRole|principal_role|persona)\b"
    ),
)


def _c_style_violations(rel: Path, text: str) -> list[Violation]:
    path = rel.as_posix()
    source = _strip_c_style_comments(text)
    hits: set[tuple[int, str, str]] = set()

    for match in _IDENTIFIER_PATTERN.finditer(source):
        hits.add(
            (
                _line(source, match.start()),
                "LEGACY_FLAG_IDENTIFIER",
                match.group(1),
            )
        )

    for pattern in _ROLE_COMPARE_PATTERNS:
        for match in pattern.finditer(source):
            persona = match.group(1).lower()
            hits.add(
                (
                    _line(source, match.start()),
                    "GENERIC_ROLE_PERSONA_AUTHORITY",
                    persona,
                )
            )

    return [
        Violation(path, line, code, detail)
        for line, code, detail in sorted(hits)
    ]


def _retired_admin_dependency_violation(root: Path) -> list[Violation]:
    """If the legacy dependency tombstone exists, it must remain fail-closed."""
    path = root / "wa_backend" / "api" / "dependencies.py"
    if not path.is_file():
        return []

    text = path.read_text(encoding="utf-8-sig")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as error:
        return [
            Violation(
                "wa_backend/api/dependencies.py",
                int(error.lineno or 1),
                "PYTHON_PARSE_ERROR",
                str(error.msg),
            )
        ]

    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_current_admin"
        ),
        None,
    )
    if target is None:
        return []

    body = list(target.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]

    valid = (
        len(body) == 1
        and isinstance(body[0], ast.Raise)
        and isinstance(body[0].exc, ast.Call)
        and isinstance(body[0].exc.func, ast.Name)
        and body[0].exc.func.id == "_retired_dependency"
        and not body[0].exc.args
        and not body[0].exc.keywords
    )
    if valid:
        return []

    return [
        Violation(
            "wa_backend/api/dependencies.py",
            int(target.lineno),
            "RETIRED_ADMIN_DEPENDENCY_REACTIVATED",
            "get_current_admin must remain a fail-closed tombstone or be removed",
        )
    ]


def scan_repository(root: Path) -> ScanReport:
    root = root.resolve()
    scanned: list[str] = []
    excluded: dict[str, list[str]] = {key: [] for key in EXCLUSION_DESCRIPTIONS}
    violations: list[Violation] = []

    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        if not _runtime_candidate(rel):
            continue

        reason = _exclusion_reason(rel)
        if reason is not None:
            excluded[reason].append(rel.as_posix())
            continue

        text = path.read_text(encoding="utf-8-sig")
        scanned.append(rel.as_posix())
        if rel.suffix.lower() == ".py":
            violations.extend(_python_violations(rel, text))
        else:
            violations.extend(_c_style_violations(rel, text))

    violations.extend(_retired_admin_dependency_violation(root))
    unique = {
        (item.path, item.line, item.code, item.detail): item
        for item in violations
    }

    return ScanReport(
        scanned=tuple(scanned),
        excluded_by_reason={
            key: tuple(values) for key, values in excluded.items()
        },
        violations=tuple(
            unique[key]
            for key in sorted(unique)
        ),
    )


def _print_report(report: ScanReport) -> None:
    counts = report.scanned_by_surface
    print("LEGACY_ADMIN_RUNTIME_SCAN=COMPLETE")
    print(f"RUNTIME_FILES_SCANNED={len(report.scanned)}")
    print(f"BACKEND_AND_WORKER_FILES_SCANNED={counts['backend_and_workers']}")
    print(f"DASHBOARD_FILES_SCANNED={counts['dashboard']}")
    print(f"FLUTTER_FILES_SCANNED={counts['flutter']}")

    for reason, description in EXCLUSION_DESCRIPTIONS.items():
        paths = report.excluded_by_reason.get(reason, ())
        print(f"EXCLUDED_{reason.upper()}={len(paths)} # {description}")

    if report.violations:
        print(f"LEGACY_ADMIN_RUNTIME_AUTHORITY=FAIL ({len(report.violations)} violation(s))")
        for item in report.violations:
            print(f"{item.path}:{item.line}: {item.code}: {item.detail}")
        return

    print("LEGACY_ADMIN_RUNTIME_AUTHORITY=PASS")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root (defaults to the guard script's repository).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = scan_repository(args.root)
    _print_report(report)
    return 1 if report.violations else 0


if __name__ == "__main__":
    sys.exit(main())
