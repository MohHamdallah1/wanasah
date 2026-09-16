from __future__ import annotations
import subprocess
from pathlib import Path

ROOT = Path.cwd()
EXPECTED_HEAD = "e7115af398478e6bc3fc639ec958f0fa276fe458"
FILES = {
    "stage4_batch": ROOT / "wa_backend/scripts/gate_stage4_batch_expiry.py",
    "stage4_final": ROOT / "wa_backend/scripts/gate_stage4_final.py",
    "stage73": ROOT / "wa_backend/scripts/gate_stage73_product_ux_i18n_network.py",
}

OLD_MAKE_VARIANT = "async def make_variant(conn, company_id: int, product_id: int, min_shelf_life: int = 0) -> int:\n    sku = f\"SKU-{uuid4().hex[:6]}\"\n    row = (await conn.execute(text(\n        \"INSERT INTO product_variants \"\n        \"(company_id, product_id, sku, name, base_uom_id, quantity_scale, quantity_step, \"\n        \" lot_control_mode, expiry_control_mode, lifecycle_status, operational_hold, lifecycle_revision, version, created_at, updated_at, min_shelf_life_days) \"\n        \"VALUES (:c, :p, :sku, 'SKU', 1, 0, '1', 'NONE', 'NONE', 'DRAFT', 'NONE', 1, 1, NOW(), NOW(), :msl) RETURNING id\"\n    ), {\"c\": company_id, \"p\": product_id, \"sku\": sku, \"msl\": min_shelf_life})).fetchone()\n    return row[0]\n"
NEW_MAKE_VARIANT = "async def make_variant(conn, company_id: int, product_id: int) -> int:\n    sku = f\"SKU-{uuid4().hex[:6]}\"\n    row = (await conn.execute(text(\n        \"INSERT INTO product_variants \"\n        \"(company_id, product_id, sku, name, base_uom_id, quantity_scale, quantity_step, \"\n        \" lot_control_mode, expiry_control_mode, lifecycle_status, operational_hold, \"\n        \"lifecycle_revision, version, published_at, created_at, updated_at) \"\n        \"VALUES (:c, :p, :sku, 'SKU', 1, 0, '1', 'REQUIRED', 'REQUIRED', \"\n        \"'ACTIVE', 'NONE', 1, 1, NOW(), NOW(), NOW()) RETURNING id\"\n    ), {\"c\": company_id, \"p\": product_id, \"sku\": sku})).fetchone()\n    return row[0]\n\n\nasync def make_stock_policy(\n    conn,\n    company_id: int,\n    location_id: int,\n    variant_id: int,\n    min_shelf_life: int,\n) -> None:\n    await conn.execute(\n        text(\n            \"INSERT INTO inventory_stock_policies \"\n            \"(company_id, location_id, product_variant_id, minimum_quantity, \"\n            \"target_quantity, minimum_remaining_shelf_life_days, is_active, \"\n            \"created_at, updated_at) \"\n            \"VALUES (:c, :l, :v, 0, NULL, :days, true, NOW(), NOW())\"\n        ),\n        {\n            \"c\": company_id,\n            \"l\": location_id,\n            \"v\": variant_id,\n            \"days\": min_shelf_life,\n        },\n    )\n"
OLD_VALID_TRANSFER = "                    \"(company_id, reference_number, source_location_id, destination_location_id, \"\n                    \"workflow_type, status, transfer_purpose, dispatched_by, created_at, posted_at, updated_at) \"\n                    \"VALUES (:c, 'REF1', :l1, :l2, 'DIRECT', 'POSTED', 'QUARANTINE', :d, NOW(), NOW(), NOW())\"\n"
NEW_VALID_TRANSFER = "                    \"(company_id, reference_number, source_location_id, destination_location_id, \"\n                    \"workflow_type, status, transfer_purpose, commercial_context, dispatched_by, \"\n                    \"created_at, posted_at, updated_at) \"\n                    \"VALUES (:c, 'REF1', :l1, :l2, 'DIRECT', 'POSTED', 'REPLENISHMENT', \"\n                    \"CAST('{}' AS jsonb), :d, NOW(), NOW(), NOW())\"\n"
OLD_INVALID_TRANSFER = "                    \"(company_id, reference_number, source_location_id, destination_location_id, \"\n                    \"workflow_type, status, transfer_purpose, dispatched_by, created_at, posted_at) \"\n                    \"VALUES (:c, 'REF2', :l1, :l2, 'DIRECT', 'POSTED', 'INVALID_PURPOSE', :d, NOW(), NOW())\"\n"
NEW_INVALID_TRANSFER = "                    \"(company_id, reference_number, source_location_id, destination_location_id, \"\n                    \"workflow_type, status, transfer_purpose, commercial_context, dispatched_by, \"\n                    \"created_at, posted_at) \"\n                    \"VALUES (:c, 'REF2', :l1, :l2, 'DIRECT', 'POSTED', 'INVALID_PURPOSE', \"\n                    \"CAST('{}' AS jsonb), :d, NOW(), NOW())\"\n"
OLD_POLICY_FIXTURE = (
    "            # Variant requires 10 days shelf life minimum\n"
    "            var = await make_variant(su, co, prd, min_shelf_life=10)\n"
)
NEW_POLICY_FIXTURE = (
    "            # Shelf-life is a location/product inventory policy, not ProductVariant master data.\n"
    "            var = await make_variant(su, co, prd)\n"
    "            await make_stock_policy(\n"
    "                su,\n"
    "                company_id=co,\n"
    "                location_id=loc,\n"
    "                variant_id=var,\n"
    "                min_shelf_life=10,\n"
    "            )\n"
)
OLD_STAGE4_HEAD = "        record(\n            \"Alembic is at Stage4 expected head\",\n            head == EXPECTED_ALEMBIC_HEAD,\n            f\"head={head}\",\n        )\n"
NEW_STAGE4_HEAD = "        lineage_cp = subprocess.run(\n            [\n                sys.executable,\n                \"-m\",\n                \"alembic\",\n                \"history\",\n                \"-r\",\n                f\"base:{head}\",\n            ],\n            cwd=_backend_dir,\n            text=True,\n            encoding=\"utf-8\",\n            errors=\"replace\",\n            capture_output=True,\n        )\n        record(\n            \"Stage4 migration remains in current Alembic lineage\",\n            lineage_cp.returncode == 0\n            and EXPECTED_ALEMBIC_HEAD in lineage_cp.stdout,\n            f\"head={head}\",\n        )\n"
OLD_STAGE73_HEAD = "    check(\n        heads_cp.returncode == 0\n        and cli_heads == {\"f9d2b4c6a8e1\"},\n        \"Stage 7.3 migration is the single Alembic head\",\n    )\n"
NEW_STAGE73_HEAD = "    current_head = next(iter(cli_heads)) if len(cli_heads) == 1 else \"\"\n    lineage_cp = (\n        subprocess.run(\n            [\n                sys.executable,\n                \"-m\",\n                \"alembic\",\n                \"history\",\n                \"-r\",\n                f\"base:{current_head}\",\n            ],\n            cwd=BACKEND,\n            text=True,\n            encoding=\"utf-8\",\n            errors=\"replace\",\n            capture_output=True,\n        )\n        if current_head\n        else None\n    )\n    check(\n        heads_cp.returncode == 0\n        and len(cli_heads) == 1\n        and lineage_cp is not None\n        and lineage_cp.returncode == 0\n        and \"f9d2b4c6a8e1\" in lineage_cp.stdout,\n        \"Stage 7.3 migration remains in current Alembic lineage\",\n    )\n"
OLD_STAGE73_DB_LABEL = "            \"Database is upgraded to the exact Stage 7.3 head\",\n"
NEW_STAGE73_DB_LABEL = "            \"Database is upgraded to the exact current Alembic head\",\n"


def run(*args: str) -> str:
    proc = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            "ERROR running: " + " ".join(args) + "\n" + proc.stderr
        )
    return proc.stdout.strip()


def require_file(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"ERROR: missing {path}. No files were modified.")


def require_unmodified_since_stage73(path: Path) -> None:
    rel = path.relative_to(ROOT).as_posix()

    for args, label in (
        (("git", "diff", "--quiet", "--", rel), "unstaged"),
        (("git", "diff", "--cached", "--quiet", "--", rel), "staged"),
    ):
        proc = subprocess.run(args, cwd=ROOT)
        if proc.returncode != 0:
            raise SystemExit(
                f"ERROR: {rel} has {label} changes. "
                "Refusing to patch a locally modified legacy gate."
            )

    committed_blob = run("git", "rev-parse", f"HEAD:{rel}")
    stage73_blob = run("git", "rev-parse", f"{EXPECTED_HEAD}:{rel}")
    if committed_blob != stage73_blob:
        raise SystemExit(
            f"ERROR: {rel} committed baseline differs from Stage 7.3. "
            "No files were modified."
        )


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"ERROR: {label}: expected exactly one anchor, found {count}. "
            "No files were modified."
        )
    return text.replace(old, new, 1)


def patch_stage4_batch(text: str) -> str:
    text = replace_once(
        text,
        OLD_MAKE_VARIANT,
        NEW_MAKE_VARIANT,
        "stage4 batch: move shelf-life policy out of ProductVariant",
    )
    text = replace_once(
        text,
        OLD_VALID_TRANSFER,
        NEW_VALID_TRANSFER,
        "stage4 batch: valid transfer commercial_context",
    )
    text = replace_once(
        text,
        OLD_INVALID_TRANSFER,
        NEW_INVALID_TRANSFER,
        "stage4 batch: invalid transfer commercial_context",
    )
    text = replace_once(
        text,
        OLD_POLICY_FIXTURE,
        NEW_POLICY_FIXTURE,
        "stage4 batch: modern shelf-life policy fixture",
    )
    return text


def patch_stage4_final(text: str) -> str:
    return replace_once(
        text,
        OLD_STAGE4_HEAD,
        NEW_STAGE4_HEAD,
        "stage4 final: old exact-head assertion",
    )


def patch_stage73(text: str) -> str:
    text = replace_once(
        text,
        OLD_STAGE73_HEAD,
        NEW_STAGE73_HEAD,
        "stage73: old exact-head assertion",
    )
    text = replace_once(
        text,
        OLD_STAGE73_DB_LABEL,
        NEW_STAGE73_DB_LABEL,
        "stage73: current-head label",
    )
    return text


def main() -> None:
    head = run("git", "rev-parse", "HEAD")
    if head != EXPECTED_HEAD:
        raise SystemExit(
            "ERROR: this fixer expects the committed Stage 7.3 baseline "
            f"{EXPECTED_HEAD}, got {head}. "
            "Stage 7.4 should still be uncommitted at this point."
        )

    for path in FILES.values():
        require_file(path)
        require_unmodified_since_stage73(path)

    originals = {
        name: path.read_text(encoding="utf-8")
        for name, path in FILES.items()
    }

    updated = {
        "stage4_batch": patch_stage4_batch(originals["stage4_batch"]),
        "stage4_final": patch_stage4_final(originals["stage4_final"]),
        "stage73": patch_stage73(originals["stage73"]),
    }

    for name, source in updated.items():
        compile(source, str(FILES[name]), "exec")

    temp_paths = {}
    try:
        for name, path in FILES.items():
            tmp = path.with_suffix(path.suffix + ".legacy-gate-fix.tmp")
            tmp.write_text(updated[name], encoding="utf-8")
            temp_paths[name] = tmp

        for name, path in FILES.items():
            temp_paths[name].replace(path)
    finally:
        for tmp in temp_paths.values():
            if tmp.exists():
                tmp.unlink()

    print("STAGE74_LEGACY_GATES_V2_FIXED_OK")
    print("Changed gates:")
    for path in FILES.values():
        print(f"  {path.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
