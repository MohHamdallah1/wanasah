from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 anchor, found {count}")
    return text.replace(old, new, 1)


def replace_between(
    text: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
    label: str,
) -> str:
    if text.count(start_marker) != 1:
        raise RuntimeError(
            f"{label}: expected exactly 1 start marker, found {text.count(start_marker)}"
        )
    start = text.index(start_marker)
    end = text.find(end_marker, start + len(start_marker))
    if end < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return text[:start] + replacement + text[end:]


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def patch(repo: Path, *, dry_run: bool = False) -> list[str]:
    targets = {
        "warehouse": repo / "wa_backend/api/warehouse.py",
        "schemas": repo / "wa_backend/schemas.py",
        "inbound_contracts": repo / "dashboard/src/pages/inventory/inbound/contracts.ts",
        "inbound": repo / "dashboard/src/pages/inventory/Tab2Inbound.tsx",
        "live_contracts": repo / "dashboard/src/pages/inventory/liveStock/contracts.ts",
        "quantity": repo / "dashboard/src/pages/inventory/quantity.ts",
        "live": repo / "dashboard/src/pages/inventory/Tab1LiveStock.tsx",
        "ledger_contracts": repo / "dashboard/src/pages/inventory/ledger/contracts.ts",
        "ledger": repo / "dashboard/src/pages/inventory/Tab4Ledger.tsx",
        "operations_data": repo / "dashboard/src/data/operations-data.ts",
        "operations": repo / "dashboard/src/pages/OperationsDashboard.tsx",
        "resources": repo / "dashboard/src/i18n/resources.ts",
        "gate": repo / "wa_backend/scripts/gate_stage76_inventory_ux_cost_visibility.py",
    }
    for key, path in targets.items():
        if key != "gate" and not path.exists():
            raise RuntimeError(f"missing target: {path}")

    original = {key: path.read_text(encoding="utf-8") for key, path in targets.items() if key != "gate"}
    updated = dict(original)

    # Operations dashboard runtime validation.
    t = updated["operations_data"]
    anchor = '''export interface DriverData {
  session: Session;
  settlement: SettlementReport;
  avatar?: string; // اختياري لأنه لا يأتي من الخادم حالياً
}
'''
    insert = anchor + '''
const driverDataSchema = z.object({
  session: z.object({
    session_id: z.number().int().positive(),
    driver_name: z.string(),
    start_time: z.string().nullable(),
    is_authorized_to_sell: z.boolean(),
    is_on_break: z.boolean(),
    vehicle_label: z.string().nullable(),
  }),
  settlement: z.object({
    driver_name: z.string(),
    status: z.string(),
    financials: z.object({
      expected_cash_in_hand: z.string(),
      cash_from_sales: z.string(),
      cash_from_debts: z.string(),
      inventory_shortage_cash: z.string(),
    }),
    visits: z.object({
      completed_total: z.number().int().nonnegative(),
      successful_sales: z.number().int().nonnegative(),
      pending_remaining: z.number().int().nonnegative(),
    }),
    inventory: z.array(inventoryItemSchema),
  }),
  avatar: z.string().optional(),
});

export function parseDriverDataList(raw: unknown): DriverData[] {
  const result = z.array(driverDataSchema).safeParse(raw);
  if (!result.success) {
    const error = new Error("OPERATIONS_RESPONSE_INVALID") as Error & { code: string };
    error.code = "OPERATIONS_RESPONSE_INVALID";
    throw error;
  }
  return result.data as DriverData[];
}
'''
    updated["operations_data"] = replace_once(t, anchor, insert, "operations-data parser")

    t = updated["operations"]
    t = replace_once(
        t,
        '''  getFleetStats,
  parseSessionSettlementReport,
} from "@/data/operations-data";''',
        '''  getFleetStats,
  parseDriverDataList,
  parseSessionSettlementReport,
} from "@/data/operations-data";''',
        "operations import parser",
    )
    t = replace_once(t, "        setDrivers(data);", "        setDrivers(parseDriverDataList(data));", "operations setDrivers")
    updated["operations"] = t

    # Inbound UX: one document-level default batch number, per-line override,
    # and multiple purchasing UOMs for the same product+batch when each UOM appears once.
    t = updated["inbound_contracts"]
    t = replace_once(
        t,
        '''export type InboundDraftMap = Record<string, InboundBatchDraft[]>;\n\nexport interface InboundUomOption {''',
        '''export type InboundDraftMap = Record<string, InboundBatchDraft[]>;\n\nexport interface InboundDocumentDefaults {\n  batch_number: string;\n}\n\nexport interface InboundUomOption {''',
        "inbound document defaults interface",
    )
    t = replace_once(
        t,
        '''    fingerprint: `${prefix}:fingerprint`,\n  } as const;''',
        '''    fingerprint: `${prefix}:fingerprint`,\n    batchDefault: `${prefix}:batch-default`,\n  } as const;''',
        "inbound batch-default storage key",
    )
    t = replace_once(
        t,
        '''export const buildInboundItems = (\n  drafts: InboundDraftMap,\n  variants: Map<string, CatalogVariant>,\n  options: Map<number, InboundVariantOptions>\n): InboundItemPayload[] => {\n  const items: InboundItemPayload[] = [];\n  const seen = new Set<string>();''',
        '''export const buildInboundItems = (\n  drafts: InboundDraftMap,\n  variants: Map<string, CatalogVariant>,\n  options: Map<number, InboundVariantOptions>,\n  defaults: InboundDocumentDefaults = { batch_number: "" }\n): InboundItemPayload[] => {\n  const items: InboundItemPayload[] = [];\n  const seenBatchMetadata = new Map<string, string>();\n  const seenBatchUoms = new Set<string>();''',
        "inbound builder mixed-uom prelude",
    )
    t = replace_once(
        t,
        '''      const unitCost = validMoney(row.unit_cost);\n      const batch = row.batch_number.trim();\n      if (!batch || batch.length > 100) {\n        throw codedError("INBOUND_BATCH_INVALID");\n      }\n      if (\n        !isoDate(row.production_date, true) ||\n        !isoDate(row.expiry_date, true) ||\n        (row.production_date && row.expiry_date && row.production_date > row.expiry_date)\n      ) {\n        throw codedError("INBOUND_BATCH_DATES_INVALID");\n      }\n      if (variant.expiry_control_mode === "REQUIRED" && !row.expiry_date) {\n        throw codedError("INBOUND_EXPIRY_REQUIRED");\n      }\n      if (variant.expiry_control_mode === "NONE" && row.expiry_date) {\n        throw codedError("INBOUND_EXPIRY_NOT_ALLOWED");\n      }\n\n      const key = `${variant.id}|${batch}`;\n      if (seen.has(key)) throw codedError("INBOUND_DUPLICATE_BATCH_LINE");\n      seen.add(key);''',
        '''      const unitCost = validMoney(row.unit_cost);\n      const batch = row.batch_number.trim() || defaults.batch_number.trim();\n      if (!batch || batch.length > 100) {\n        throw codedError("INBOUND_BATCH_INVALID");\n      }\n      if (\n        !isoDate(row.production_date, true) ||\n        !isoDate(row.expiry_date, true) ||\n        (row.production_date && row.expiry_date && row.production_date > row.expiry_date)\n      ) {\n        throw codedError("INBOUND_BATCH_DATES_INVALID");\n      }\n      if (variant.expiry_control_mode === "REQUIRED" && !row.expiry_date) {\n        throw codedError("INBOUND_EXPIRY_REQUIRED");\n      }\n      if (variant.expiry_control_mode === "NONE" && row.expiry_date) {\n        throw codedError("INBOUND_EXPIRY_NOT_ALLOWED");\n      }\n\n      const batchKey = `${variant.id}|${batch}`;\n      const metadataKey = `${row.production_date}|${row.expiry_date}`;\n      const existingMetadata = seenBatchMetadata.get(batchKey);\n      if (existingMetadata !== undefined && existingMetadata !== metadataKey) {\n        throw codedError("INBOUND_BATCH_METADATA_CONFLICT");\n      }\n      seenBatchMetadata.set(batchKey, metadataKey);\n\n      const uomKey = `${batchKey}|${uomId}`;\n      if (seenBatchUoms.has(uomKey)) {\n        throw codedError("INBOUND_DUPLICATE_BATCH_UOM_LINE");\n      }\n      seenBatchUoms.add(uomKey);''',
        "inbound builder mixed-uom validation",
    )
    t = replace_once(
        t,
        '''      a.product_variant_id - b.product_variant_id ||\n      a.batch_number.localeCompare(b.batch_number)''',
        '''      a.product_variant_id - b.product_variant_id ||\n      a.batch_number.localeCompare(b.batch_number) ||\n      a.uom_id - b.uom_id''',
        "inbound deterministic mixed-uom sort",
    )
    updated["inbound_contracts"] = t

    t = updated["inbound"]
    t = replace_once(
        t,
        '''  type CostPolicy,\n  type InboundBatchDraft,''',
        '''  type CostPolicy,\n  type InboundBatchDraft,\n  type InboundDocumentDefaults,''',
        "inbound import document defaults",
    )
    t = replace_once(
        t,
        '''  const [notes, setNotes] = useState(\n    () => localStorage.getItem(keys.notes) || ""\n  );\n  const request = useRef(0);''',
        '''  const [notes, setNotes] = useState(\n    () => localStorage.getItem(keys.notes) || ""\n  );\n  const [documentDefaults, setDocumentDefaults] =\n    useState<InboundDocumentDefaults>(() => ({\n      batch_number: localStorage.getItem(keys.batchDefault) || "",\n    }));\n  const request = useRef(0);''',
        "inbound document defaults state",
    )
    t = replace_once(
        t,
        '''  useEffect(() => {\n    localStorage.setItem(keys.notes, notes);\n  }, [notes, keys]);\n\n  useEffect(() => {''',
        '''  useEffect(() => {\n    localStorage.setItem(keys.notes, notes);\n  }, [notes, keys]);\n  useEffect(() => {\n    if (documentDefaults.batch_number) {\n      localStorage.setItem(keys.batchDefault, documentDefaults.batch_number);\n    } else {\n      localStorage.removeItem(keys.batchDefault);\n    }\n  }, [documentDefaults.batch_number, keys]);\n\n  useEffect(() => {''',
        "inbound document defaults persist",
    )
    t = replace_once(
        t,
        '''    localStorage.removeItem(keys.fingerprint);\n    setClearOpen(false);''',
        '''    localStorage.removeItem(keys.fingerprint);\n    localStorage.removeItem(keys.batchDefault);\n    setDocumentDefaults({ batch_number: "" });\n    setClearOpen(false);''',
        "inbound clear document defaults",
    )
    t = replace_once(
        t,
        '''        uomOptions\n      );''',
        '''        uomOptions,\n        documentDefaults\n      );''',
        "inbound builder document defaults call",
    )
    t = replace_once(
        t,
        '''        <div className="flex-1 min-h-0 overflow-auto mt-5">\n          <table className="w-full text-sm min-w-[1120px]">''',
        '''        <div className="mx-4 mt-6 rounded-2xl border border-emerald-100 bg-emerald-50/60 p-4">\n          <label className="block text-xs font-black text-slate-700">\n            {t("inventoryInbound.defaultBatchTitle")}\n            <input\n              value={documentDefaults.batch_number}\n              onChange={(event) =>\n                setDocumentDefaults({ batch_number: event.target.value })\n              }\n              placeholder={t("inventoryInbound.defaultBatchPlaceholder")}\n              className="mt-1.5 w-full max-w-md rounded-xl border bg-white p-2.5"\n            />\n          </label>\n          <p className="mt-2 text-xs font-semibold text-emerald-800/80">\n            {t("inventoryInbound.defaultBatchHint")}\n          </p>\n        </div>\n\n        <div className="flex-1 min-h-0 overflow-auto mt-3">\n          <table className="w-full text-sm min-w-[1120px]">''',
        "inbound document batch input",
    )
    t = replace_once(
        t,
        '''                const defaultUom = String(\n                  option?.base_uom_id ?? variant.base_uom.id\n                );''',
        '''                const commercialUoms =\n                  option?.uoms.filter((uom) => uom.id !== option.base_uom_id) ?? [];\n                const defaultUom = String(\n                  commercialUoms.length === 1\n                    ? commercialUoms[0].id\n                    : option?.base_uom_id ?? variant.base_uom.id\n                );''',
        "inbound safe commercial default uom",
    )
    t = replace_once(
        t,
        '''                            placeholder={t("inventoryInbound.batchNumber")}\n                            className="rounded-lg border p-2"''',
        '''                            placeholder={\n                              documentDefaults.batch_number\n                                ? t("inventoryInbound.overrideBatchPlaceholder", {\n                                    batch: documentDefaults.batch_number,\n                                  })\n                                : t("inventoryInbound.batchNumber")\n                            }\n                            title={t("inventoryInbound.rowBatchOverrideHint")}\n                            className="rounded-lg border p-2"''',
        "inbound batch override hint",
    )
    t = replace_once(
        t,
        '''                          <span className="text-xs font-bold text-slate-500">\n                            {costPolicy?.currency_code ?? ""}\n                          </span>''',
        '''                          <span className="text-xs font-bold text-slate-500">\n                            {costPolicy?.currency_code ?? ""}\n                            {selectedOption\n                              ? ` / ${uomLabel(selectedOption.code, selectedOption.name)}`\n                              : ""}\n                          </span>''',
        "inbound cost uom label",
    )
    t = replace_once(
        t,
        '''                            title={t("inventoryInbound.addBatch")}''',
        '''                            title={t("inventoryInbound.addReceiptLine")}''',
        "inbound add-line title",
    )
    t = replace_once(
        t,
        '''  const uomLabel = (code: string, fallback: string) =>
    t(`uom.${code}`, { defaultValue: fallback });''',
        '''  const uomLabel = (code: string, _fallback: string) =>
    t(`uom.${code}`, { defaultValue: t("inventoryCommon.unit") });''',
        "inbound locale-pure uom fallback",
    )
    updated["inbound"] = t


    # Backend: mixed-UOM supplier receipt, localized display metadata, true
    # product/location ledger balances, and immutable costing evidence visibility.
    t = updated["warehouse"]
    t = replace_once(
        t,
        '''InventoryLocation, TenantOperationalPolicy, InventoryStockPolicy, InventoryBalance, InventoryMovement, InventoryMovementImpact, ProductBatch,\nInventoryTransferHeader''',
        '''InventoryLocation, TenantOperationalPolicy, InventoryStockPolicy, InventoryBalance, InventoryMovement, InventoryMovementImpact, ProductBatch,\nInventoryCostEvent, InventoryCostState,\nInventoryTransferHeader''',
        "warehouse costing model imports",
    )

    display_helper_anchor = '''@router.post("/warehouse/inbound/options", status_code=200)\n'''
    display_helper = '''async def _load_inventory_display_uoms(\n    db: AsyncSession,\n    *,\n    company_id: int,\n    variant_ids: list[int] | set[int],\n) -> dict[int, dict]:\n    ids = sorted({int(value) for value in variant_ids})\n    if not ids:\n        return {}\n\n    rows = (\n        await db.execute(\n            select(ProductUomConversion, UOM)\n            .join(\n                ProductVariant,\n                and_(\n                    ProductVariant.company_id == ProductUomConversion.company_id,\n                    ProductVariant.id == ProductUomConversion.product_variant_id,\n                ),\n            )\n            .join(UOM, UOM.id == ProductUomConversion.from_uom_id)\n            .filter(\n                ProductUomConversion.company_id == int(company_id),\n                ProductUomConversion.product_variant_id.in_(ids),\n                ProductUomConversion.to_uom_id == ProductVariant.base_uom_id,\n            )\n            .order_by(\n                ProductUomConversion.product_variant_id.asc(),\n                ProductUomConversion.id.asc(),\n            )\n        )\n    ).all()\n\n    candidates: dict[int, list[dict]] = {}\n    for conversion, uom in rows:\n        numerator = Decimal(conversion.numerator)\n        denominator = Decimal(conversion.denominator)\n        if numerator <= 0 or denominator <= 0:\n            raise RuntimeError("Invalid product UOM conversion.")\n        factor = numerator / denominator\n        if factor <= 1:\n            continue\n        candidates.setdefault(int(conversion.product_variant_id), []).append({\n            "uom_id": int(uom.id),\n            "uom_code": str(uom.code),\n            "uom_name": str(uom.name),\n            "factor_to_base": factor,\n        })\n\n    # Never guess between multiple commercial units.  One exact direct conversion\n    # is safe to use as the default display; otherwise the caller falls back to base.\n    return {\n        variant_id: rows[0]\n        for variant_id, rows in candidates.items()\n        if len(rows) == 1\n    }\n\n\nasync def _ledger_product_location_snapshots(\n    db: AsyncSession,\n    *,\n    company_id: int,\n    location_id: int,\n    product_variant_ids: list[int] | set[int],\n    movement_ids: list[int],\n) -> dict[int, tuple[Decimal, Decimal]]:\n    variant_ids = sorted({int(value) for value in product_variant_ids})\n    page_movement_ids = sorted({int(value) for value in movement_ids})\n    if not variant_ids or not page_movement_ids:\n        return {}\n\n    movement_delta_subq = (\n        select(\n            InventoryMovement.id.label("movement_id"),\n            InventoryMovement.product_variant_id.label("product_variant_id"),\n            InventoryMovement.created_at.label("created_at"),\n            func.sum(\n                InventoryMovementImpact.on_hand_after\n                - InventoryMovementImpact.on_hand_before\n            ).label("location_delta"),\n        )\n        .join(\n            InventoryMovementImpact,\n            and_(\n                InventoryMovementImpact.company_id == InventoryMovement.company_id,\n                InventoryMovementImpact.movement_id == InventoryMovement.id,\n            ),\n        )\n        .join(\n            InventoryBalance,\n            and_(\n                InventoryBalance.company_id == InventoryMovementImpact.company_id,\n                InventoryBalance.id == InventoryMovementImpact.inventory_balance_id,\n            ),\n        )\n        .filter(\n            InventoryMovement.company_id == int(company_id),\n            InventoryMovement.product_variant_id.in_(variant_ids),\n            InventoryMovementImpact.company_id == int(company_id),\n            InventoryBalance.company_id == int(company_id),\n            InventoryBalance.location_id == int(location_id),\n        )\n        .group_by(\n            InventoryMovement.id,\n            InventoryMovement.product_variant_id,\n            InventoryMovement.created_at,\n        )\n        .subquery()\n    )\n\n    history_subq = (\n        select(\n            movement_delta_subq.c.movement_id,\n            movement_delta_subq.c.product_variant_id,\n            movement_delta_subq.c.location_delta,\n            func.sum(movement_delta_subq.c.location_delta)\n            .over(\n                partition_by=movement_delta_subq.c.product_variant_id,\n                order_by=(\n                    movement_delta_subq.c.created_at.asc(),\n                    movement_delta_subq.c.movement_id.asc(),\n                ),\n                rows=(None, 0),\n            )\n            .label("cumulative_delta"),\n            func.sum(movement_delta_subq.c.location_delta)\n            .over(partition_by=movement_delta_subq.c.product_variant_id)\n            .label("total_delta"),\n        )\n        .subquery()\n    )\n\n    current_balance_subq = (\n        select(\n            InventoryBalance.product_variant_id.label("product_variant_id"),\n            func.sum(InventoryBalance.on_hand_quantity).label("current_total"),\n        )\n        .filter(\n            InventoryBalance.company_id == int(company_id),\n            InventoryBalance.location_id == int(location_id),\n            InventoryBalance.product_variant_id.in_(variant_ids),\n        )\n        .group_by(InventoryBalance.product_variant_id)\n        .subquery()\n    )\n\n    snapshot_rows = (\n        await db.execute(\n            select(\n                history_subq.c.movement_id,\n                history_subq.c.location_delta,\n                history_subq.c.cumulative_delta,\n                history_subq.c.total_delta,\n                func.coalesce(current_balance_subq.c.current_total, 0).label(\n                    "current_total"\n                ),\n            )\n            .outerjoin(\n                current_balance_subq,\n                current_balance_subq.c.product_variant_id\n                == history_subq.c.product_variant_id,\n            )\n            .filter(history_subq.c.movement_id.in_(page_movement_ids))\n        )\n    ).all()\n\n    result: dict[int, tuple[Decimal, Decimal]] = {}\n    for row in snapshot_rows:\n        delta = Decimal(row.location_delta or 0)\n        cumulative = Decimal(row.cumulative_delta or 0)\n        total_delta = Decimal(row.total_delta or 0)\n        current_total = Decimal(row.current_total or 0)\n        opening_total = current_total - total_delta\n        after = opening_total + cumulative\n        before = after - delta\n        if before < 0 or after < 0:\n            raise RuntimeError(\n                "Ledger product/location balance reconstruction became negative."\n            )\n        result[int(row.movement_id)] = (before, after)\n    return result\n\n\n'''
    t = replace_once(
        t,
        display_helper_anchor,
        display_helper + display_helper_anchor,
        "warehouse display and ledger snapshot helpers",
    )

    t = replace_between(
        t,
        '''        requested_batches = {}\n        base_quantities: dict[tuple[int, str], Decimal] = {}\n        cost_inputs = {}\n''',
        '''        await db.execute(\n            pg_insert(ProductBatch).values([''',
        '''        requested_batches: dict[\n            tuple[int, str],\n            tuple[Optional[date], Optional[date]],\n        ] = {}\n        inbound_lines: list[dict] = []\n        seen_batch_uoms: set[tuple[int, str, int]] = set()\n\n        for item in payload.items:\n            batch_key = (int(item.product_variant_id), str(item.batch_number))\n            metadata = (item.production_date, item.expiry_date)\n            if batch_key in requested_batches and requested_batches[batch_key] != metadata:\n                raise HTTPException(\n                    status_code=422,\n                    detail=inventory_business_error(\n                        "INBOUND_BATCH_METADATA_CONFLICT",\n                        "The same product batch cannot carry conflicting dates in one receipt.",\n                        context={\n                            "product_variant_id": int(item.product_variant_id),\n                            "batch_number": str(item.batch_number),\n                        },\n                    ),\n                )\n\n            line_key = (\n                int(item.product_variant_id),\n                str(item.batch_number),\n                int(item.uom_id),\n            )\n            if line_key in seen_batch_uoms:\n                raise HTTPException(\n                    status_code=422,\n                    detail=inventory_business_error(\n                        "INBOUND_DUPLICATE_BATCH_UOM_LINE",\n                        "The same product, batch and purchasing unit may appear only once per receipt.",\n                        context={\n                            "product_variant_id": int(item.product_variant_id),\n                            "batch_number": str(item.batch_number),\n                            "uom_id": int(item.uom_id),\n                        },\n                    ),\n                )\n            seen_batch_uoms.add(line_key)\n\n            factor = uom_factors.get(\n                (int(item.product_variant_id), int(item.uom_id))\n            )\n            if factor is None:\n                raise HTTPException(\n                    status_code=422,\n                    detail=inventory_business_error(\n                        "INBOUND_UOM_UNSUPPORTED",\n                        "The selected purchasing unit has no direct exact conversion to the base unit.",\n                        context={\n                            "product_variant_id": int(item.product_variant_id),\n                            "uom_id": int(item.uom_id),\n                        },\n                    ),\n                )\n            raw_base_quantity = Decimal(item.quantity) * Decimal(factor)\n            try:\n                base_quantity = validate_variant_quantity(\n                    raw_base_quantity,\n                    quantity_scale=variant_rules[item.product_variant_id]["quantity_scale"],\n                    quantity_step=variant_rules[item.product_variant_id]["quantity_step"],\n                    field_name="quantity",\n                )\n            except QuantityError as exc:\n                raise HTTPException(\n                    status_code=422,\n                    detail=inventory_business_error(\n                        "INBOUND_QUANTITY_CONVERSION_INVALID",\n                        "The purchased quantity cannot be represented exactly in the product base unit.",\n                        context={"product_variant_id": int(item.product_variant_id)},\n                    ),\n                ) from exc\n\n            expiry_mode = variant_rules[item.product_variant_id]["expiry_control_mode"]\n            if expiry_mode == 'REQUIRED' and item.expiry_date is None:\n                raise HTTPException(\n                    status_code=422,\n                    detail=inventory_business_error(\n                        "INBOUND_EXPIRY_REQUIRED",\n                        "Expiry date is required for this product.",\n                        context={"product_variant_id": int(item.product_variant_id)},\n                    ),\n                )\n            if expiry_mode == 'NONE' and item.expiry_date is not None:\n                raise HTTPException(\n                    status_code=422,\n                    detail=inventory_business_error(\n                        "INBOUND_EXPIRY_NOT_ALLOWED",\n                        "This product does not use expiry tracking.",\n                        context={"product_variant_id": int(item.product_variant_id)},\n                    ),\n                )\n            if item.expiry_date is not None and item.expiry_date < as_of_date:\n                raise HTTPException(\n                    status_code=422,\n                    detail=inventory_business_error(\n                        "INBOUND_BATCH_EXPIRED",\n                        "Expired stock cannot be received as available inventory.",\n                        context={"batch_number": str(item.batch_number)},\n                    ),\n                )\n            if item.production_date is not None and item.production_date > as_of_date:\n                raise HTTPException(\n                    status_code=422,\n                    detail=inventory_business_error(\n                        "INBOUND_PRODUCTION_DATE_FUTURE",\n                        "Production date cannot be in the future.",\n                        context={"batch_number": str(item.batch_number)},\n                    ),\n                )\n            if (\n                item.production_date is not None\n                and item.expiry_date is not None\n                and item.production_date > item.expiry_date\n            ):\n                raise HTTPException(\n                    status_code=422,\n                    detail=inventory_business_error(\n                        "INBOUND_BATCH_DATES_INVALID",\n                        "Production date cannot be after expiry date.",\n                        context={"batch_number": str(item.batch_number)},\n                    ),\n                )\n\n            if batch_key not in requested_batches:\n                requested_batches[batch_key] = metadata\n            inbound_lines.append({\n                "batch_key": batch_key,\n                "uom_id": int(item.uom_id),\n                "base_quantity": base_quantity,\n                "cost_input": build_purchase_cost_input(\n                    input_uom_id=int(item.uom_id),\n                    input_quantity=Decimal(item.quantity),\n                    input_unit_cost=Decimal(item.unit_cost),\n                    base_quantity=base_quantity,\n                ),\n            })\n\n        await db.execute(\n            pg_insert(ProductBatch).values([''',
        "warehouse inbound mixed-uom lines",
    )

    t = replace_between(
        t,
        '''        movement_specs = []\n        for key in sorted(requested_batches):\n''',
        '''        await apply_inventory_movements_batch(''',
        '''        movement_specs = []\n        for line in sorted(\n            inbound_lines,\n            key=lambda value: (\n                value["batch_key"][0],\n                value["batch_key"][1],\n                value["uom_id"],\n            ),\n        ):\n            batch_key = line["batch_key"]\n            product_variant_id, batch_number = batch_key\n            batch = batch_map[batch_key]\n            movement_raw_key = (\n                f"{company_id}|{normalized_ref}|{main_loc.id}|"\n                f"{product_variant_id}|{batch.id}|{line['uom_id']}"\n            )\n            movement_specs.append({\n                "product_variant_id": product_variant_id,\n                "batch_id": int(batch.id),\n                "quantity": line["base_quantity"],\n                "movement_kind": 'PHYSICAL',\n                "reference_type": 'INBOUND_SUPPLIER',\n                "reference_id": reference_id,\n                "idempotency_key": (\n                    "INB-"\n                    + hashlib.sha256(movement_raw_key.encode("utf-8")).hexdigest()\n                ),\n                "source_location_id": None,\n                "destination_location_id": main_loc.id,\n                "source_stock_status": None,\n                "destination_stock_status": 'AVAILABLE',\n                "inventory_cost_input": line["cost_input"],\n                "notes": payload.notes,\n            })\n\n        await apply_inventory_movements_batch(''',
        "warehouse inbound mixed-uom movements",
    )

    # Live stock: attach one unambiguous commercial display unit and current\n    # company-wide average cost without changing the base-unit stock authority.
    t = replace_once(
        t,
        '''        rows = (await db.execute(stmt)).all()\n\n        result = []\n        for (\n            variant,''',
        '''        rows = (await db.execute(stmt)).all()\n\n        display_uoms = await _load_inventory_display_uoms(\n            db,\n            company_id=company_id,\n            variant_ids=page_variant_ids,\n        )\n        cost_state_rows = list(\n            (\n                await db.scalars(\n                    select(InventoryCostState).filter(\n                        InventoryCostState.company_id == company_id,\n                        InventoryCostState.product_variant_id.in_(page_variant_ids),\n                    )\n                )\n            ).all()\n        )\n        cost_state_by_variant = {\n            int(row.product_variant_id): row for row in cost_state_rows\n        }\n        currency_code = await db.scalar(\n            select(Company.currency_code).where(Company.id == company_id)\n        )\n        if not currency_code:\n            raise RuntimeError("Company currency is unavailable.")\n\n        result = []\n        for (\n            variant,''',
        "live display and cost preload",
    )
    t = replace_once(
        t,
        '''            total_physical_available = on_hand + explicit_blocked + vehicle_total\n\n            result.append({''',
        '''            total_physical_available = on_hand + explicit_blocked + vehicle_total\n\n            display = display_uoms.get(int(variant.id))\n            if display is None:\n                display_uom_id = int(base_uom.id)\n                display_uom_code = str(base_uom.code)\n                display_uom_name = str(base_uom.name)\n                display_factor = Decimal("1")\n            else:\n                display_uom_id = int(display["uom_id"])\n                display_uom_code = str(display["uom_code"])\n                display_uom_name = str(display["uom_name"])\n                display_factor = Decimal(display["factor_to_base"])\n\n            cost_state = cost_state_by_variant.get(int(variant.id))\n            average_cost_display = None\n            if cost_state is not None:\n                average_cost_display = (\n                    Decimal(cost_state.average_unit_cost) * display_factor\n                ).quantize(Decimal("0.000001"))\n\n            result.append({''',
        "live display and cost calculation",
    )
    t = replace_once(
        t,
        '''                "base_uom_name": base_uom.name,\n                "quantity_scale": variant.quantity_scale,''',
        '''                "base_uom_name": base_uom.name,\n                "display_uom_id": display_uom_id,\n                "display_uom_code": display_uom_code,\n                "display_uom_name": display_uom_name,\n                "display_factor_to_base": canonical_quantity(display_factor),\n                "currency_code": str(currency_code).upper(),\n                "average_cost_display": (\n                    format(average_cost_display, "f")\n                    if average_cost_display is not None\n                    else None\n                ),\n                "quantity_scale": variant.quantity_scale,''',
        "live display and cost response fields",
    )

    # Ledger: reconstruct the real total product balance at the selected\n    # warehouse, and expose original purchase-cost evidence for each movement.
    t = replace_once(
        t,
        '''        movement_ids = [row[0].id for row in rows]\n\n        stmt_impacts = select(''',
        '''        movement_ids = [row[0].id for row in rows]\n        page_variant_ids = sorted({int(row[0].product_variant_id) for row in rows})\n\n        aggregate_snapshots = (\n            await _ledger_product_location_snapshots(\n                db,\n                company_id=company_id,\n                location_id=location_id,\n                product_variant_ids=page_variant_ids,\n                movement_ids=movement_ids,\n            )\n            if location_id is not None\n            else {}\n        )\n        display_uoms = await _load_inventory_display_uoms(\n            db,\n            company_id=company_id,\n            variant_ids=page_variant_ids,\n        )\n\n        batch_ids = sorted({\n            int(row[0].batch_id)\n            for row in rows\n            if row[0].batch_id is not None\n        })\n        batch_number_by_id: dict[int, str] = {}\n        if batch_ids:\n            batch_number_by_id = {\n                int(batch_id): str(batch_number)\n                for batch_id, batch_number in (\n                    await db.execute(\n                        select(ProductBatch.id, ProductBatch.batch_number).filter(\n                            ProductBatch.company_id == company_id,\n                            ProductBatch.id.in_(batch_ids),\n                        )\n                    )\n                ).all()\n            }\n\n        cost_events = list(\n            (\n                await db.scalars(\n                    select(InventoryCostEvent).filter(\n                        InventoryCostEvent.company_id == company_id,\n                        InventoryCostEvent.inventory_movement_id.in_(movement_ids),\n                    )\n                )\n            ).all()\n        )\n        cost_event_by_movement = {\n            int(event.inventory_movement_id): event for event in cost_events\n        }\n        cost_uom_ids = sorted({\n            int(event.input_uom_id)\n            for event in cost_events\n            if event.input_uom_id is not None\n        })\n        cost_uom_by_id: dict[int, UOM] = {}\n        if cost_uom_ids:\n            cost_uom_by_id = {\n                int(row.id): row\n                for row in (\n                    await db.scalars(select(UOM).where(UOM.id.in_(cost_uom_ids)))\n                ).all()\n            }\n        ledger_currency_code = await db.scalar(\n            select(Company.currency_code).where(Company.id == company_id)\n        )\n        if not ledger_currency_code:\n            raise RuntimeError("Company currency is unavailable.")\n\n        stmt_impacts = select(''',
        "ledger aggregate/cost preload",
    )
    t = replace_once(
        t,
        '''            result.append({\n                "id": movement.id,''',
        '''            aggregate_snapshot = aggregate_snapshots.get(int(movement.id))\n            total_balance_before = (\n                aggregate_snapshot[0] if aggregate_snapshot is not None else None\n            )\n            total_balance_after = (\n                aggregate_snapshot[1] if aggregate_snapshot is not None else None\n            )\n\n            display = display_uoms.get(int(movement.product_variant_id))\n            if display is None:\n                display_uom_id = int(base_uom.id)\n                display_uom_code = str(base_uom.code)\n                display_uom_name = str(base_uom.name)\n                display_factor = Decimal("1")\n            else:\n                display_uom_id = int(display["uom_id"])\n                display_uom_code = str(display["uom_code"])\n                display_uom_name = str(display["uom_name"])\n                display_factor = Decimal(display["factor_to_base"])\n\n            cost_event = cost_event_by_movement.get(int(movement.id))\n            input_uom = (\n                cost_uom_by_id.get(int(cost_event.input_uom_id))\n                if cost_event is not None and cost_event.input_uom_id is not None\n                else None\n            )\n            average_cost_after = None\n            average_cost_uom_code = None\n            average_cost_uom_name = None\n            if cost_event is not None:\n                cost_quantity_after = Decimal(cost_event.quantity_after)\n                cost_value_after = Decimal(cost_event.value_after)\n                average_base_after = (\n                    Decimal("0")\n                    if cost_quantity_after == 0\n                    else cost_value_after / cost_quantity_after\n                )\n                if (\n                    cost_event.input_quantity is not None\n                    and Decimal(cost_event.input_quantity) > 0\n                    and input_uom is not None\n                ):\n                    event_factor = (\n                        Decimal(movement.quantity)\n                        / Decimal(cost_event.input_quantity)\n                    )\n                    average_cost_after = average_base_after * event_factor\n                    average_cost_uom_code = str(input_uom.code)\n                    average_cost_uom_name = str(input_uom.name)\n                else:\n                    average_cost_after = average_base_after * display_factor\n                    average_cost_uom_code = display_uom_code\n                    average_cost_uom_name = display_uom_name\n                average_cost_after = average_cost_after.quantize(\n                    Decimal("0.000001")\n                )\n\n            result.append({\n                "id": movement.id,''',
        "ledger aggregate/cost calculation",
    )
    t = replace_once(
        t,
        '''                "type": movement.reference_type,\n                "quantity": canonical_quantity(quantity_packs),\n                "balance_before": balance_before,\n                "balance_after": balance_after,\n                "admin_name": admin_name or "غير معروف",''',
        '''                "type": movement.reference_type,\n                "quantity": canonical_quantity(quantity_packs),\n                "balance_before": total_balance_before,\n                "balance_after": total_balance_after,\n                "balance_scope": (\n                    "PRODUCT_LOCATION"\n                    if aggregate_snapshot is not None\n                    else None\n                ),\n                "batch_number": (\n                    batch_number_by_id.get(int(movement.batch_id))\n                    if movement.batch_id is not None\n                    else None\n                ),\n                "display_uom_id": display_uom_id,\n                "display_uom_code": display_uom_code,\n                "display_uom_name": display_uom_name,\n                "display_factor_to_base": canonical_quantity(display_factor),\n                "currency_code": str(ledger_currency_code).upper(),\n                "cost_method": (\n                    str(cost_event.method) if cost_event is not None else None\n                ),\n                "input_quantity": (\n                    canonical_quantity(cost_event.input_quantity)\n                    if cost_event is not None\n                    and cost_event.input_quantity is not None\n                    else None\n                ),\n                "input_uom_code": (\n                    str(input_uom.code) if input_uom is not None else None\n                ),\n                "input_uom_name": (\n                    str(input_uom.name) if input_uom is not None else None\n                ),\n                "input_unit_cost": (\n                    format(\n                        Decimal(cost_event.input_unit_cost).quantize(\n                            Decimal("0.000001")\n                        ),\n                        "f",\n                    )\n                    if cost_event is not None\n                    and cost_event.input_unit_cost is not None\n                    else None\n                ),\n                "total_cost": (\n                    format(\n                        Decimal(cost_event.total_cost).quantize(\n                            Decimal("0.000001")\n                        ),\n                        "f",\n                    )\n                    if cost_event is not None\n                    else None\n                ),\n                "average_cost_after": (\n                    format(average_cost_after, "f")\n                    if average_cost_after is not None\n                    else None\n                ),\n                "average_cost_uom_code": average_cost_uom_code,\n                "average_cost_uom_name": average_cost_uom_name,\n                "admin_name": admin_name or "غير معروف",''',
        "ledger aggregate/cost response fields",
    )
    updated["warehouse"] = t


    # API response contracts and mixed-UOM request validation.
    t = updated["schemas"]
    t = replace_once(
        t,
        '''    base_uom_id: PositiveDbInt\n    base_uom_code: str\n    base_uom_name: str\n    quantity_scale: int = Field(..., ge=0, le=6)''',
        '''    base_uom_id: PositiveDbInt\n    base_uom_code: str\n    base_uom_name: str\n    display_uom_id: PositiveDbInt\n    display_uom_code: str = Field(..., min_length=1, max_length=20)\n    display_uom_name: str = Field(..., min_length=1, max_length=50)\n    display_factor_to_base: PositiveQuantity\n    currency_code: str = Field(..., min_length=1, max_length=10)\n    average_cost_display: Optional[InventoryCostMoneyInput] = None\n    quantity_scale: int = Field(..., ge=0, le=6)''',
        "inventory response commercial display fields",
    )
    t = replace_once(
        t,
        '''    balance_before: Optional[NonNegativeQuantity] = None\n    balance_after: Optional[NonNegativeQuantity] = None\n    admin_name: str = Field(..., min_length=1, max_length=120)''',
        '''    balance_before: Optional[NonNegativeQuantity] = None\n    balance_after: Optional[NonNegativeQuantity] = None\n    balance_scope: Optional[Literal["PRODUCT_LOCATION"]] = None\n    batch_number: Optional[str] = Field(None, max_length=100)\n    display_uom_id: PositiveDbInt\n    display_uom_code: str = Field(..., min_length=1, max_length=20)\n    display_uom_name: str = Field(..., min_length=1, max_length=50)\n    display_factor_to_base: PositiveQuantity\n    currency_code: str = Field(..., min_length=1, max_length=10)\n    cost_method: Optional[Literal["MOVING_AVERAGE", "FIFO"]] = None\n    input_quantity: Optional[PositiveQuantity] = None\n    input_uom_code: Optional[str] = Field(None, max_length=20)\n    input_uom_name: Optional[str] = Field(None, max_length=50)\n    input_unit_cost: Optional[InventoryCostMoneyInput] = None\n    total_cost: Optional[InventoryCostMoneyInput] = None\n    average_cost_after: Optional[InventoryCostMoneyInput] = None\n    average_cost_uom_code: Optional[str] = Field(None, max_length=20)\n    average_cost_uom_name: Optional[str] = Field(None, max_length=50)\n    admin_name: str = Field(..., min_length=1, max_length=120)''',
        "ledger response total-balance and cost fields",
    )
    t = replace_between(
        t,
        '''    @model_validator(mode="after")\n    def validate_duplicate_batch_metadata(self) -> "UpgradedInboundRequest":\n''',
        '''\n\n\n# PATCH: STAGE4D_BATCH_DISPOSITION_PORTION_STATUS''',
        '''    @model_validator(mode="after")\n    def validate_duplicate_batch_metadata(self) -> "UpgradedInboundRequest":\n        seen_batches: Dict[\n            tuple[int, str],\n            tuple[Optional[date], Optional[date]],\n        ] = {}\n        seen_batch_uoms: set[tuple[int, str, int]] = set()\n        for item in self.items:\n            batch_key = (item.product_variant_id, item.batch_number)\n            metadata = (item.production_date, item.expiry_date)\n            if batch_key in seen_batches and seen_batches[batch_key] != metadata:\n                raise ValueError(\n                    "The same product batch cannot carry conflicting dates."\n                )\n            seen_batches[batch_key] = metadata\n\n            line_key = (\n                item.product_variant_id,\n                item.batch_number,\n                item.uom_id,\n            )\n            if line_key in seen_batch_uoms:\n                raise ValueError(\n                    "The same product, batch and purchasing unit may appear only once."\n                )\n            seen_batch_uoms.add(line_key)\n        return self\n\n\n\n# PATCH: STAGE4D_BATCH_DISPOSITION_PORTION_STATUS''',
        "mixed-uom inbound schema validator",
    )
    updated["schemas"] = t


    # Live stock contract: commercial display metadata + current average cost.
    t = updated["live_contracts"]
    t = replace_once(
        t,
        '''  base_uom_id: number; base_uom_code: string; base_uom_name: string;\n  quantity_scale: number; quantity_step: Quantity;''',
        '''  base_uom_id: number; base_uom_code: string; base_uom_name: string;\n  display_uom_id:number; display_uom_code:string; display_uom_name:string;\n  display_factor_to_base:Quantity; currency_code:string; average_cost_display:string|null;\n  quantity_scale: number; quantity_step: Quantity;''',
        "live-stock commercial response type",
    )
    t = replace_once(
        t,
        '''const optional = (value: unknown): string|null => value===null ? null : str(value,"sku",100);''',
        '''const optional = (value: unknown): string|null => value===null ? null : str(value,"sku",100);\nconst moneyOrNull=(value:unknown,field:string):string|null=>{if(value===null)return null;const text=str(value,field,64);if(!/^\\d+(?:\\.\\d{1,6})?$/.test(text))throw new Error(`حقل ${field} غير صالح.`);return text;};''',
        "live-stock money parser",
    )
    t = replace_once(
        t,
        '''    id,name:str(row.name,"name"),sku:optional(row.sku),base_uom_id:int(row.base_uom_id,"base_uom_id",1),base_uom_code:str(row.base_uom_code,"base_uom_code",20),base_uom_name:str(row.base_uom_name,"base_uom_name",50),quantity_scale:scale,quantity_step:parseQuantity(row.quantity_step,"quantity_step"),available_quantity:parseQuantity(row.available_quantity,"available_quantity",{allowZero:true}),reserved_quantity:parseQuantity(row.reserved_quantity,"reserved_quantity",{allowZero:true}),blocked_quantity:parseQuantity(row.blocked_quantity,"blocked_quantity",{allowZero:true}),total_quantity:parseQuantity(row.total_quantity,"total_quantity",{allowZero:true}),damaged_quantity:parseQuantity(row.damaged_quantity,"damaged_quantity",{allowZero:true}),minimum_quantity:parseQuantity(row.minimum_quantity,"minimum_quantity",{allowZero:true}),''',
        '''    id,name:str(row.name,"name"),sku:optional(row.sku),base_uom_id:int(row.base_uom_id,"base_uom_id",1),base_uom_code:str(row.base_uom_code,"base_uom_code",20),base_uom_name:str(row.base_uom_name,"base_uom_name",50),display_uom_id:int(row.display_uom_id,"display_uom_id",1),display_uom_code:str(row.display_uom_code,"display_uom_code",20),display_uom_name:str(row.display_uom_name,"display_uom_name",50),display_factor_to_base:parseQuantity(row.display_factor_to_base,"display_factor_to_base"),currency_code:str(row.currency_code,"currency_code",10),average_cost_display:moneyOrNull(row.average_cost_display,"average_cost_display"),quantity_scale:scale,quantity_step:parseQuantity(row.quantity_step,"quantity_step"),available_quantity:parseQuantity(row.available_quantity,"available_quantity",{allowZero:true}),reserved_quantity:parseQuantity(row.reserved_quantity,"reserved_quantity",{allowZero:true}),blocked_quantity:parseQuantity(row.blocked_quantity,"blocked_quantity",{allowZero:true}),total_quantity:parseQuantity(row.total_quantity,"total_quantity",{allowZero:true}),damaged_quantity:parseQuantity(row.damaged_quantity,"damaged_quantity",{allowZero:true}),minimum_quantity:parseQuantity(row.minimum_quantity,"minimum_quantity",{allowZero:true}),''',
        "live-stock commercial response parser",
    )
    updated["live_contracts"] = t


    # Exact commercial quantity formatter. Internal quantities remain base-UOM;
    # only the presentation is converted, and ambiguous/non-integer factors fall back safely.
    t = updated["quantity"]
    anchor = '''export const formatQuantity = (value: Quantity, uomName: string): string =>\n  `${canonicalFromScaled(scaled(value))} ${uomName}`;\n'''
    updated["quantity"] = replace_once(
        t,
        anchor,
        anchor + '''\nexport function formatCommercialQuantity(\n  value: Quantity,\n  displayUomName: string,\n  baseUomName: string,\n  factorToBase: Quantity,\n): { primary: string; secondary: string | null } {\n  const valueScaled = scaled(value);\n  const factorScaled = scaled(factorToBase);\n\n  if (\n    factorScaled <= 1_000_000n ||\n    factorScaled % 1_000_000n !== 0n\n  ) {\n    return { primary: formatQuantity(value, baseUomName), secondary: null };\n  }\n\n  if (valueScaled < factorScaled) {\n    return { primary: formatQuantity(value, baseUomName), secondary: null };\n  }\n\n  const whole = valueScaled / factorScaled;\n  const remainder = valueScaled % factorScaled;\n  const primary =\n    remainder === 0n\n      ? `${whole.toString()} ${displayUomName}`\n      : `${whole.toString()} ${displayUomName} + ${canonicalFromScaled(remainder)} ${baseUomName}`;\n\n  return {\n    primary,\n    secondary: `${canonicalFromScaled(valueScaled)} ${baseUomName}`,\n  };\n}\n''',
        "quantity commercial formatter",
    )

    # Live stock UI: no raw UOM codes in the active locale; commercial unit is primary.
    t = updated["live"]
    t = replace_once(
        t,
        '''import { compareQuantity, formatQuantity } from "./quantity";''',
        '''import { compareQuantity, formatCommercialQuantity } from "./quantity";\nimport { useTranslation } from "react-i18next";''',
        "live localized commercial imports",
    )
    t = replace_once(
        t,
        '''}: Props) {\n  const [searchInput, setSearchInput] = useState("");''',
        '''}: Props) {\n  const { t, i18n } = useTranslation();\n  const [searchInput, setSearchInput] = useState("");\n\n  const formatMoney = (value: string, currency: string) => {\n    const numeric = Number(value);\n    if (!Number.isFinite(numeric)) return value;\n    try {\n      return new Intl.NumberFormat(\n        i18n.language.startsWith("ar") ? "ar-JO" : "en-US",\n        {\n          style: "currency",\n          currency,\n          minimumFractionDigits: 3,\n          maximumFractionDigits: 6,\n        },\n      ).format(numeric);\n    } catch {\n      return value;\n    }\n  };''',
        "live localized money formatter",
    )
    t = replace_once(
        t,
        '''                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">في المستودع</th>''',
        '''                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">{t("inventoryLive.inWarehouse")}</th>''',
        "live localized warehouse header",
    )
    t = replace_once(
        t,
        '''                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">\n                  <div className="relative group flex items-center gap-1 border-b border-dashed border-slate-400 w-max cursor-help">\n                    التوالف بالفرع''',
        '''                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">\n                  <div className="relative group flex items-center gap-1 border-b border-dashed border-slate-400 w-max cursor-help">\n                    {t("inventoryLive.averageCost")} <Info className="w-3 h-3" />\n                    <div className="absolute top-full right-1/2 translate-x-1/2 mt-2 w-max max-w-[240px] text-center bg-slate-800 text-white text-[10px] px-2 py-1.5 rounded-lg hidden group-hover:block z-50 whitespace-normal shadow-xl">\n                      {t("inventoryLive.averageCostHint")}\n                    </div>\n                  </div>\n                </th>\n                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">\n                  <div className="relative group flex items-center gap-1 border-b border-dashed border-slate-400 w-max cursor-help">\n                    التوالف بالفرع''',
        "live average cost header",
    )
    t = replace_once(
        t,
        '''              {products.map((p) => {\n                const isAlert = compareQuantity(p.minimum_quantity, "0") > 0 && compareQuantity(p.available_quantity, p.minimum_quantity) <= 0;\n                return (''',
        '''              {products.map((p) => {\n                const isAlert = compareQuantity(p.minimum_quantity, "0") > 0 && compareQuantity(p.available_quantity, p.minimum_quantity) <= 0;\n                const displayName = t(`uom.${p.display_uom_code}`, {\n                  defaultValue: p.display_uom_name,\n                });\n                const baseName = t(`uom.${p.base_uom_code}`, {\n                  defaultValue: p.base_uom_name,\n                });\n                const renderQuantity = (value: typeof p.available_quantity) =>\n                  formatCommercialQuantity(\n                    value,\n                    displayName,\n                    baseName,\n                    p.display_factor_to_base,\n                  );\n                return (''',
        "live localized quantity renderer",
    )
    t = replace_once(
        t,
        '''                    <td className="px-4 py-3 text-emerald-700 font-semibold">\n                      {formatQuantity(p.available_quantity, p.base_uom_name)}\n                      {compareQuantity(p.blocked_quantity, "0") > 0 && (\n                        <div className="text-[10px] font-bold text-amber-600 mt-0.5">\n                          محجوب عن الصرف: {formatQuantity(p.blocked_quantity, p.base_uom_name)}\n                        </div>\n                      )}\n                    </td>\n                    <td className="px-4 py-3 text-violet-600 font-semibold">\n                      {formatQuantity(p.reserved_quantity, p.base_uom_name)}\n                    </td>\n                    <td className="px-4 py-3 text-slate-700 font-bold border-l border-slate-100">\n                      {formatQuantity(p.total_quantity, p.base_uom_name)}\n                    </td>\n                    <td className="px-4 py-3 text-red-600 font-bold bg-red-50/30">\n                      {formatQuantity(p.damaged_quantity, p.base_uom_name)}\n                    </td>''',
        '''                    <td className="px-4 py-3 text-emerald-700 font-semibold">\n                      <div>{renderQuantity(p.available_quantity).primary}</div>\n                      {renderQuantity(p.available_quantity).secondary && (\n                        <div className="mt-0.5 text-[10px] text-slate-400">\n                          {renderQuantity(p.available_quantity).secondary}\n                        </div>\n                      )}\n                      {compareQuantity(p.blocked_quantity, "0") > 0 && (\n                        <div className="text-[10px] font-bold text-amber-600 mt-0.5">\n                          {t("inventoryLive.blocked")}: {renderQuantity(p.blocked_quantity).primary}\n                        </div>\n                      )}\n                    </td>\n                    <td className="px-4 py-3 text-violet-600 font-semibold">\n                      {renderQuantity(p.reserved_quantity).primary}\n                    </td>\n                    <td className="px-4 py-3 text-slate-700 font-bold border-l border-slate-100">\n                      {renderQuantity(p.total_quantity).primary}\n                    </td>\n                    <td className="px-4 py-3 text-slate-700 font-black tabular-nums">\n                      {p.average_cost_display\n                        ? `${formatMoney(p.average_cost_display, p.currency_code)} / ${displayName}`\n                        : "—"}\n                    </td>\n                    <td className="px-4 py-3 text-red-600 font-bold bg-red-50/30">\n                      {renderQuantity(p.damaged_quantity).primary}\n                    </td>''',
        "live commercial quantities and average cost",
    )
    t = replace_once(t, 'colSpan={6}', 'colSpan={7}', "live empty-state colspan")
    updated["live"] = t


    # Ledger contract: total product/location balances + localized UOM/cost evidence.
    t = updated["ledger_contracts"]
    t = replace_once(
        t,
        '''  balance_before:Quantity|null; balance_after:Quantity|null; admin_name:string;\n  reference:string|null; notes:string|null; date:string;''',
        '''  balance_before:Quantity|null; balance_after:Quantity|null; balance_scope:"PRODUCT_LOCATION"|null;\n  batch_number:string|null; display_uom_id:number; display_uom_code:string; display_uom_name:string;\n  display_factor_to_base:Quantity; currency_code:string; cost_method:"MOVING_AVERAGE"|"FIFO"|null;\n  input_quantity:Quantity|null; input_uom_code:string|null; input_uom_name:string|null;\n  input_unit_cost:string|null; total_cost:string|null; average_cost_after:string|null;\n  average_cost_uom_code:string|null; average_cost_uom_name:string|null;\n  admin_name:string; reference:string|null; notes:string|null; date:string;''',
        "ledger expanded response type",
    )
    t = replace_once(
        t,
        '''const optional=(value:unknown,field:string):string|null=>value===null?null:str(value,field);''',
        '''const optional=(value:unknown,field:string):string|null=>value===null?null:str(value,field);\nconst moneyOrNull=(value:unknown,field:string):string|null=>{if(value===null)return null;const text=str(value,field,64);if(!/^\\d+(?:\\.\\d{1,6})?$/.test(text))throw new Error(`حقل ${field} غير صالح.`);return text;};''',
        "ledger money parser",
    )
    t = replace_once(
        t,
        '''if(before!==null&&after!==null&&compareQuantity(subtractQuantity(after,before),quantity)!==0)throw new Error("كمية الحركة لا تطابق لقطة الرصيد.");''',
        '''if(before!==null&&after!==null&&(compareQuantity(before,"0")<0||compareQuantity(after,"0")<0))throw new Error("لقطة الرصيد غير صالحة.");''',
        "ledger total-balance parser invariant",
    )
    t = replace_once(
        t,
        '''return{id,product_variant_id:int(row.product_variant_id,"product_variant_id",1),product_name:str(row.product_name,"product_name",200),base_uom_id:int(row.base_uom_id,"base_uom_id",1),base_uom_code:str(row.base_uom_code,"base_uom_code",20),quantity_scale:scale,quantity_step:parseQuantity(row.quantity_step,"quantity_step"),type:str(row.type,"type",50),quantity,balance_before:before,balance_after:after,admin_name:str(row.admin_name,"admin_name",120),reference:optional(row.reference,"reference"),notes:optional(row.notes,"notes"),date};''',
        '''return{id,product_variant_id:int(row.product_variant_id,"product_variant_id",1),product_name:str(row.product_name,"product_name",200),base_uom_id:int(row.base_uom_id,"base_uom_id",1),base_uom_code:str(row.base_uom_code,"base_uom_code",20),quantity_scale:scale,quantity_step:parseQuantity(row.quantity_step,"quantity_step"),type:str(row.type,"type",50),quantity,balance_before:before,balance_after:after,balance_scope:row.balance_scope===null?null:(row.balance_scope==="PRODUCT_LOCATION"?"PRODUCT_LOCATION":(()=>{throw new Error("نطاق الرصيد غير صالح.")})()),batch_number:optional(row.batch_number,"batch_number"),display_uom_id:int(row.display_uom_id,"display_uom_id",1),display_uom_code:str(row.display_uom_code,"display_uom_code",20),display_uom_name:str(row.display_uom_name,"display_uom_name",50),display_factor_to_base:parseQuantity(row.display_factor_to_base,"display_factor_to_base"),currency_code:str(row.currency_code,"currency_code",10),cost_method:row.cost_method===null?null:(row.cost_method==="MOVING_AVERAGE"||row.cost_method==="FIFO"?row.cost_method:(()=>{throw new Error("طريقة التكلفة غير صالحة.")})()),input_quantity:row.input_quantity===null?null:parseQuantity(row.input_quantity,"input_quantity"),input_uom_code:optional(row.input_uom_code,"input_uom_code"),input_uom_name:optional(row.input_uom_name,"input_uom_name"),input_unit_cost:moneyOrNull(row.input_unit_cost,"input_unit_cost"),total_cost:moneyOrNull(row.total_cost,"total_cost"),average_cost_after:moneyOrNull(row.average_cost_after,"average_cost_after"),average_cost_uom_code:optional(row.average_cost_uom_code,"average_cost_uom_code"),average_cost_uom_name:optional(row.average_cost_uom_name,"average_cost_uom_name"),admin_name:str(row.admin_name,"admin_name",120),reference:optional(row.reference,"reference"),notes:optional(row.notes,"notes"),date};''',
        "ledger expanded response parser",
    )
    updated["ledger_contracts"] = t

    # Ledger UI: translated units only, real product/location before/after balances,
    # original purchasing cost, and average inventory cost after the movement.
    t = updated["ledger"]
    t = replace_once(
        t,
        '''import { useState, useEffect, useCallback, useRef } from "react";''',
        '''import { useState, useEffect, useCallback, useRef } from "react";\nimport { useTranslation } from "react-i18next";''',
        "ledger i18n import",
    )
    t = replace_once(
        t,
        '''import { absoluteQuantity, addQuantity, compareQuantity, formatQuantity } from "./quantity";''',
        '''import { absoluteQuantity, addQuantity, compareQuantity, formatCommercialQuantity, formatQuantity } from "./quantity";''',
        "ledger commercial quantity import",
    )
    t = replace_once(
        t,
        '''  const authenticatedFetch = useAuthFetch();\n  const access = useInventoryAccess(locationId);''',
        '''  const authenticatedFetch = useAuthFetch();\n  const { t, i18n } = useTranslation();\n  const access = useInventoryAccess(locationId);\n\n  const uomLabel = (code: string | null) =>\n    code\n      ? t(`uom.${code}`, { defaultValue: t("inventoryCommon.unit") })\n      : t("inventoryCommon.unit");\n\n  const formatMoney = (value: string, currency: string) => {\n    const numeric = Number(value);\n    if (!Number.isFinite(numeric)) return value;\n    try {\n      return new Intl.NumberFormat(\n        i18n.language.startsWith("ar") ? "ar-JO" : "en-US",\n        {\n          style: "currency",\n          currency,\n          minimumFractionDigits: 3,\n          maximumFractionDigits: 6,\n        },\n      ).format(numeric);\n    } catch {\n      return value;\n    }\n  };''',
        "ledger localized formatters",
    )
    t = replace_once(
        t,
        '''                <th className="px-4 py-3 text-xs font-bold text-slate-500">الرصيد قبل</th>\n                <th className="px-4 py-3 text-xs font-bold text-slate-500">الكمية</th>\n                <th className="px-4 py-3 text-xs font-bold text-slate-500">الرصيد بعد</th>\n                <th className="px-4 py-3 text-xs font-bold text-slate-500">المشرف</th>''',
        '''                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.batch")}</th>\n                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.balanceBefore")}</th>\n                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.quantity")}</th>\n                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.balanceAfter")}</th>\n                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.purchaseCost")}</th>\n                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.averageAfter")}</th>\n                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.supervisor")}</th>''',
        "ledger total-balance/cost headers",
    )
    t = replace_once(t, 'colSpan={9}', 'colSpan={12}', "ledger empty-state colspan")
    t = replace_once(
        t,
        '''              {!loading && entries.map((entry) => {\n                const badge = getLedgerBadge(entry.type);\n                const isNeg = compareQuantity(entry.quantity, "0") < 0;\n                const reference = entry.reference || "";\n\n                return (''',
        '''              {!loading && entries.map((entry) => {\n                const badge = getLedgerBadge(entry.type);\n                const isNeg = compareQuantity(entry.quantity, "0") < 0;\n                const reference = entry.reference || "";\n                const displayName = uomLabel(entry.display_uom_code);\n                const baseName = uomLabel(entry.base_uom_code);\n                const renderBaseQuantity = (value: typeof entry.quantity) =>\n                  formatCommercialQuantity(\n                    value,\n                    displayName,\n                    baseName,\n                    entry.display_factor_to_base,\n                  ).primary;\n                const movementQuantity =\n                  entry.input_quantity && entry.input_uom_code\n                    ? formatQuantity(\n                        entry.input_quantity,\n                        uomLabel(entry.input_uom_code),\n                      )\n                    : renderBaseQuantity(absoluteQuantity(entry.quantity));\n\n                return (''',
        "ledger localized quantity row helpers",
    )
    t = replace_once(
        t,
        '''                    <td className="px-4 py-3 font-bold text-slate-800">{entry.product_name}</td>\n                    <td className="px-4 py-3 text-slate-500 font-semibold text-xs">{entry.balance_before === null ? "—" : formatQuantity(entry.balance_before, entry.base_uom_code)}</td>\n                    <td className={`px-4 py-3 font-bold text-xs ${isNeg ? "text-red-600" : "text-emerald-600"}`}>{isNeg ? "-" : "+"}{formatQuantity(absoluteQuantity(entry.quantity), entry.base_uom_code)}</td>''',
        '''                    <td className="px-4 py-3 font-bold text-slate-800">{entry.product_name}</td>\n                    <td className="px-4 py-3 text-xs font-black text-slate-600">{entry.batch_number || "—"}</td>\n                    <td className="px-4 py-3 text-slate-500 font-semibold text-xs">\n                      {entry.balance_before === null\n                        ? "—"\n                        : renderBaseQuantity(entry.balance_before)}\n                    </td>\n                    <td className={`px-4 py-3 font-bold text-xs ${isNeg ? "text-red-600" : "text-emerald-600"}`}>\n                      {isNeg ? "-" : "+"}{movementQuantity}\n                    </td>''',
        "ledger batch and real balance cells",
    )
    t = replace_once(
        t,
        '''{entry.balance_after === null ? "—" : formatQuantity(entry.balance_after, entry.base_uom_code)}</td>\n                    <td className="px-4 py-3 text-slate-600 font-semibold text-xs">{entry.admin_name}</td>''',
        '''{entry.balance_after === null ? "—" : renderBaseQuantity(entry.balance_after)}</td>\n                    <td className="px-4 py-3 text-slate-700 font-black text-xs">\n                      {entry.input_unit_cost && entry.input_uom_code ? (\n                        <>\n                          <div>\n                            {formatMoney(entry.input_unit_cost, entry.currency_code)} / {uomLabel(entry.input_uom_code)}\n                          </div>\n                          {entry.total_cost ? (\n                            <div className="mt-0.5 text-[10px] font-semibold text-slate-400">\n                              {t("inventoryLedger.totalCost")}: {formatMoney(entry.total_cost, entry.currency_code)}\n                            </div>\n                          ) : null}\n                        </>\n                      ) : "—"}\n                    </td>\n                    <td className="px-4 py-3 text-slate-700 font-black text-xs">\n                      {entry.average_cost_after && entry.average_cost_uom_code\n                        ? `${formatMoney(entry.average_cost_after, entry.currency_code)} / ${uomLabel(entry.average_cost_uom_code)}`\n                        : "—"}\n                    </td>\n                    <td className="px-4 py-3 text-slate-600 font-semibold text-xs">{entry.admin_name}</td>''',
        "ledger cost and average cells",
    )
    updated["ledger"] = t


    # i18n.
    t = updated["resources"]
    t = replace_once(
        t,
        '''        clearBody: "سيتم مسح مسودة التوريد المحلية الحالية فقط.",
        policySaved: "تم حفظ طريقة احتساب التكلفة.",''',
        '''        clearBody: "سيتم مسح مسودة التوريد المحلية الحالية فقط.",
        defaultBatchTitle: "بيانات دفعة افتراضية للسند",
        defaultBatchHint:
          "أدخلها مرة واحدة لتُطبّق على كل الأصناف التي لم تضع لها بيانات دفعة خاصة. يمكنك تجاوزها لأي صنف عند الحاجة.",
        defaultBatchPlaceholder: "مثال: LOT-2026-09",
        overrideBatchPlaceholder: "الافتراضي: {{batch}}",
        rowBatchOverrideHint:
          "اترك الحقل فارغاً لاستخدام دفعة السند الافتراضية، أو أدخل دفعة مختلفة لهذا الصنف فقط.",
        addReceiptLine: "إضافة كمية/وحدة أخرى لنفس المنتج",
        policySaved: "تم حفظ طريقة احتساب التكلفة.",''',
        "ar inbound defaults i18n",
    )
    t = replace_once(
        t,
        '''        clearBody: "Only the current local inbound draft will be cleared.",
        policySaved: "The inventory costing method was saved.",''',
        '''        clearBody: "Only the current local inbound draft will be cleared.",
        defaultBatchTitle: "Default batch details for this receipt",
        defaultBatchHint:
          "Enter them once and they will apply to every item without its own batch override. Override any item when needed.",
        defaultBatchPlaceholder: "Example: LOT-2026-09",
        overrideBatchPlaceholder: "Default: {{batch}}",
        rowBatchOverrideHint:
          "Leave this empty to use the receipt default, or enter a different batch for this item only.",
        addReceiptLine: "Add another quantity/unit for this product",
        policySaved: "The inventory costing method was saved.",''',
        "en inbound defaults i18n",
    )
    t = replace_once(
        t,
        '''      uom: {
        CARTON: "كرتونة",''',
        '''      inventoryCommon: {
        unit: "وحدة",
      },
      inventoryLive: {
        inWarehouse: "في المستودع",
        averageCost: "متوسط التكلفة",
        averageCostHint:
          "متوسط تكلفة الشركة الحالي لهذا المنتج، معروض بوحدة العرض التجارية عند توفر تحويل واحد واضح.",
        blocked: "محجوب عن الصرف",
      },
      inventoryLedger: {
        batch: "الدفعة",
        balanceBefore: "الرصيد قبل",
        quantity: "الكمية",
        balanceAfter: "الرصيد بعد",
        purchaseCost: "تكلفة الشراء",
        averageAfter: "متوسط التكلفة بعد الحركة",
        supervisor: "المشرف",
        totalCost: "إجمالي التكلفة",
      },
      uom: {
        CARTON: "كرتونة",''',
        "ar inventory i18n",
    )
    t = replace_once(
        t,
        '''      uom: {
        CARTON: "Carton",''',
        '''      inventoryCommon: {
        unit: "Unit",
      },
      inventoryLive: {
        inWarehouse: "In warehouse",
        averageCost: "Average cost",
        averageCostHint:
          "The company's current average cost for this product, shown in the commercial display unit when one unambiguous conversion is configured.",
        blocked: "Blocked from issue",
      },
      inventoryLedger: {
        batch: "Batch",
        balanceBefore: "Balance before",
        quantity: "Quantity",
        balanceAfter: "Balance after",
        purchaseCost: "Purchase cost",
        averageAfter: "Average cost after movement",
        supervisor: "Supervisor",
        totalCost: "Total cost",
      },
      uom: {
        CARTON: "Carton",''',
        "en inventory i18n",
    )
    t = replace_once(
        t,
        '''          VALIDATION_ERROR: "بيانات الطلب غير صالحة. راجع الحقول المدخلة.",''',
        '''          OPERATIONS_RESPONSE_INVALID: "استجابة غرفة العمليات غير صالحة أو غير مكتملة.",
          INBOUND_DUPLICATE_BATCH_UOM_LINE: "لا تكرر نفس المنتج ونفس الدفعة ونفس وحدة الشراء في أكثر من سطر. استخدم سطراً إضافياً فقط لوحدة شراء مختلفة.",
          VALIDATION_ERROR: "بيانات الطلب غير صالحة. راجع الحقول المدخلة.",''',
        "ar operations error",
    )
    t = replace_once(
        t,
        '''          VALIDATION_ERROR: "The request data is invalid. Review the entered fields.",''',
        '''          OPERATIONS_RESPONSE_INVALID: "The operations response is invalid or incomplete.",
          INBOUND_DUPLICATE_BATCH_UOM_LINE: "Do not repeat the same product, batch, and purchasing unit on multiple lines. Add another line only for a different purchasing unit.",
          VALIDATION_ERROR: "The request data is invalid. Review the entered fields.",''',
        "en operations error",
    )
    updated["resources"] = t

    gate = '''from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
checks = []

def check(condition: bool, label: str) -> None:
    checks.append((bool(condition), label))

warehouse = (ROOT / "wa_backend/api/warehouse.py").read_text(encoding="utf-8")
schemas = (ROOT / "wa_backend/schemas.py").read_text(encoding="utf-8")
inbound = (ROOT / "dashboard/src/pages/inventory/Tab2Inbound.tsx").read_text(encoding="utf-8")
contracts = (ROOT / "dashboard/src/pages/inventory/inbound/contracts.ts").read_text(encoding="utf-8")
live = (ROOT / "dashboard/src/pages/inventory/Tab1LiveStock.tsx").read_text(encoding="utf-8")
ledger = (ROOT / "dashboard/src/pages/inventory/Tab4Ledger.tsx").read_text(encoding="utf-8")
operations = (ROOT / "dashboard/src/pages/OperationsDashboard.tsx").read_text(encoding="utf-8")
resources = (ROOT / "dashboard/src/i18n/resources.ts").read_text(encoding="utf-8")

check("documentDefaults" in inbound and "defaultBatchTitle" in inbound, "document batch default UI")
check("defaults.batch_number" in contracts, "batch default resolved in payload builder")
check("seenBatchUoms" in contracts and "INBOUND_DUPLICATE_BATCH_UOM_LINE" in contracts, "same batch supports distinct UOM lines")
check('"balance_scope": "PRODUCT_LOCATION"' in warehouse, "ledger balance is product/location scoped")
check("_ledger_product_location_snapshots" in warehouse, "ledger reconstructs product/location totals")
check("InventoryCostEvent" in warehouse and "InventoryCostState" in warehouse, "cost evidence and current state sources")
check("display_uom_code" in schemas and "display_factor_to_base" in schemas, "commercial display UOM contract")
check("formatCommercialQuantity" in live, "commercial quantity display")
check("inventoryLedger.balanceBefore" in ledger and "inventoryLedger.balanceAfter" in ledger, "ledger labels total product balance")
check("parseDriverDataList(data)" in operations, "operations response validated before setState")
check(resources.count("OPERATIONS_RESPONSE_INVALID") >= 2, "operations error translated ar/en")
check(resources.count("defaultBatchTitle") >= 2, "batch-default UI translated ar/en")
check(resources.count("averageCostHint") >= 2, "cost visibility translated ar/en")
check(resources.count("inventoryCommon") >= 2 and resources.count('unit: "') >= 2, "generic unit fallback translated ar/en")
check(resources.count("addReceiptLine") >= 2, "mixed-UOM add-line action translated ar/en")
check(resources.count("INBOUND_DUPLICATE_BATCH_UOM_LINE") >= 2, "mixed-UOM duplicate error translated ar/en")

failures = [label for ok, label in checks if not ok]
print(f"CHECKS={len(checks)}")
print(f"FAILURES={len(failures)}")
for label in failures:
    print(f"FAIL: {label}")
if failures:
    print("STAGE76_INVENTORY_UX_COST_VISIBILITY_GATE=FAIL")
    raise SystemExit(1)
print("STAGE76_INVENTORY_UX_COST_VISIBILITY_GATE=PASS")
'''
    updated["gate"] = gate

    planned = [str(path.relative_to(repo)) for path in targets.values()]
    if dry_run:
        return planned

    backups: dict[Path, str] = {}
    written: list[Path] = []
    try:
        for key, path in targets.items():
            content = updated[key]
            if path.exists():
                backups[path] = path.read_text(encoding="utf-8")
            write_atomic(path, content)
            written.append(path)
    except Exception:
        for path in reversed(written):
            if path in backups:
                write_atomic(path, backups[path])
            else:
                try:
                    path.unlink()
                except OSError:
                    pass
        raise

    return [str(path.relative_to(repo)) for path in written]


def self_test() -> None:
    sample = "a"
    assert replace_once(sample, "a", "b", "test") == "b"
    print("SELF_TEST=PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.repo_root:
        raise SystemExit("--repo-root is required unless --self-test is used")
    repo = Path(args.repo_root).resolve()
    changed = patch(repo, dry_run=args.check_only)
    if args.check_only:
        print("STAGE76_INVENTORY_UX_COST_VISIBILITY_V3_PREFLIGHT=PASS")
        print("PLANNED_FILES=")
    else:
        print("STAGE76_INVENTORY_UX_COST_VISIBILITY_V3_PATCH_APPLIED_OK")
        print("CHANGED_FILES=")
    for item in changed:
        print(f"  {item}")


if __name__ == "__main__":
    main()
