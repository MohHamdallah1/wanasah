from pathlib import Path

PATH = Path("wa_backend/scripts/gate_stage74_inventory_costing.py")

OLD = "check('\\\"inventory.costing.manage\\\"' in access, \"cost method permission\")\n"
NEW = "check(\"inventory.costing.manage\" in access, \"cost method permission\")\n"

def main():
    if not PATH.is_file():
        raise SystemExit(f"ERROR: missing {PATH}")

    text = PATH.read_text(encoding="utf-8")
    count = text.count(OLD)
    if count != 1:
        raise SystemExit(
            "ERROR: expected exactly one Stage 7.4 permission gate anchor; "
            f"found {count}. No files were modified."
        )

    updated = text.replace(OLD, NEW, 1)
    compile(updated, str(PATH), "exec")

    tmp = PATH.with_suffix(PATH.suffix + ".tmp")
    try:
        tmp.write_text(updated, encoding="utf-8")
        tmp.replace(PATH)
    finally:
        if tmp.exists():
            tmp.unlink()

    print("STAGE74_COST_PERMISSION_GATE_FIXED_OK")

if __name__ == "__main__":
    main()
