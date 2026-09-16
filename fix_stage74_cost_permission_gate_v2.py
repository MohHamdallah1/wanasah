from __future__ import annotations

from pathlib import Path

PATH = Path("wa_backend/scripts/gate_stage74_inventory_costing.py")

OLD = """check('"inventory.costing.manage"' in access, "cost method permission")"""
NEW = """check("inventory.costing.manage" in access, "cost method permission")"""


def main() -> None:
    if not PATH.is_file():
        raise SystemExit(
            f"ERROR: missing {PATH}. No files were modified."
        )

    source = PATH.read_text(encoding="utf-8")

    count = source.count(OLD)
    if count != 1:
        raise SystemExit(
            "ERROR: expected exactly one known Stage 7.4 permission-gate bug; "
            f"found {count}. No files were modified."
        )

    updated = source.replace(OLD, NEW, 1)

    # Fail closed: the broken form must be gone and the corrected form unique.
    if OLD in updated or updated.count(NEW) != 1:
        raise SystemExit(
            "ERROR: post-replacement validation failed. No files were modified."
        )

    compile(updated, str(PATH), "exec")

    tmp = PATH.with_suffix(PATH.suffix + ".stage74-permission.tmp")
    try:
        tmp.write_text(updated, encoding="utf-8")
        tmp.replace(PATH)
    finally:
        if tmp.exists():
            tmp.unlink()

    print("STAGE74_COST_PERMISSION_GATE_FIXED_OK")


if __name__ == "__main__":
    main()
