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


def patch(repo: Path) -> list[str]:
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
        "main_inventory": repo / "dashboard/src/pages/inventory/MainInventory.tsx",
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

    # Inbound document defaults.
    t = updated["inbound_contracts"]
    t = replace_once(
        t,
        '''export type InboundDraftMap = Record<string, InboundBatchDraft[]>;

export interface InboundUomOption {''',
        '''export type InboundDraftMap = Record<string, InboundBatchDraft[]>;

export interface InboundDocumentBatchDefaults {
  batch_number: string;
  production_date: string;
  expiry_date: string;
}

export interface InboundUomOption {''',
        "inbound defaults interface",
    )
    t = replace_once(
        t,
        '''    fingerprint: `${prefix}:fingerprint`,
  } as const;''',
        '''    fingerprint: `${prefix}:fingerprint`,
    batchDefaults: `${prefix}:batch-defaults`,
  } as const;''',
        "inbound defaults storage key",
    )
    t = replace_once(
        t,
        '''export const buildInboundItems = (
  drafts: InboundDraftMap,
  variants: Map<string, CatalogVariant>,
  options: Map<number, InboundVariantOptions>
): InboundItemPayload[] => {''',
        '''export const buildInboundItems = (
  drafts: InboundDraftMap,
  variants: Map<string, CatalogVariant>,
  options: Map<number, InboundVariantOptions>,
  defaults: InboundDocumentBatchDefaults = {
    batch_number: "",
    production_date: "",
    expiry_date: "",
  }
): InboundItemPayload[] => {''',
        "inbound builder defaults",
    )
    t = replace_once(
        t,
        '''      const unitCost = validMoney(row.unit_cost);
      const batch = row.batch_number.trim();
      if (!batch || batch.length > 100) {
        throw codedError("INBOUND_BATCH_INVALID");
      }
      if (
        !isoDate(row.production_date, true) ||
        !isoDate(row.expiry_date, true) ||
        (row.production_date && row.expiry_date && row.production_date > row.expiry_date)
      ) {
        throw codedError("INBOUND_BATCH_DATES_INVALID");
      }
      if (variant.expiry_control_mode === "REQUIRED" && !row.expiry_date) {
        throw codedError("INBOUND_EXPIRY_REQUIRED");
      }
      if (variant.expiry_control_mode === "NONE" && row.expiry_date) {
        throw codedError("INBOUND_EXPIRY_NOT_ALLOWED");
      }

      const key = `${variant.id}|${batch}`;''',
        '''      const unitCost = validMoney(row.unit_cost);
      const batch = row.batch_number.trim() || defaults.batch_number.trim();
      const productionDate = row.production_date || defaults.production_date;
      const expiryDate = row.expiry_date || defaults.expiry_date;
      if (!batch || batch.length > 100) {
        throw codedError("INBOUND_BATCH_INVALID");
      }
      if (
        !isoDate(productionDate, true) ||
        !isoDate(expiryDate, true) ||
        (productionDate && expiryDate && productionDate > expiryDate)
      ) {
        throw codedError("INBOUND_BATCH_DATES_INVALID");
      }
      if (variant.expiry_control_mode === "REQUIRED" && !expiryDate) {
        throw codedError("INBOUND_EXPIRY_REQUIRED");
      }
      if (variant.expiry_control_mode === "NONE" && expiryDate) {
        throw codedError("INBOUND_EXPIRY_NOT_ALLOWED");
      }

      const key = `${variant.id}|${batch}`;''',
        "inbound effective defaults",
    )
    t = replace_once(
        t,
        '''        batch_number: batch,
        production_date: row.production_date || null,
        expiry_date: row.expiry_date || null,''',
        '''        batch_number: batch,
        production_date: productionDate || null,
        expiry_date: expiryDate || null,''',
        "inbound payload dates",
    )
    updated["inbound_contracts"] = t

    t = updated["inbound"]
    t = replace_once(
        t,
        '''  type CostPolicy,
  type InboundBatchDraft,''',
        '''  type CostPolicy,
  type InboundBatchDraft,
  type InboundDocumentBatchDefaults,''',
        "inbound import default type",
    )
    t = replace_once(
        t,
        '''  const [notes, setNotes] = useState(
    () => localStorage.getItem(keys.notes) || ""
  );
  const request = useRef(0);''',
        '''  const [notes, setNotes] = useState(
    () => localStorage.getItem(keys.notes) || ""
  );
  const [batchDefaults, setBatchDefaults] =
    useState<InboundDocumentBatchDefaults>(() => {
      try {
        const raw = localStorage.getItem(keys.batchDefaults);
        if (!raw) {
          return { batch_number: "", production_date: "", expiry_date: "" };
        }
        const parsed = JSON.parse(raw) as Partial<InboundDocumentBatchDefaults>;
        return {
          batch_number:
            typeof parsed.batch_number === "string" ? parsed.batch_number : "",
          production_date:
            typeof parsed.production_date === "string" ? parsed.production_date : "",
          expiry_date:
            typeof parsed.expiry_date === "string" ? parsed.expiry_date : "",
        };
      } catch {
        return { batch_number: "", production_date: "", expiry_date: "" };
      }
    });
  const request = useRef(0);''',
        "inbound defaults state",
    )
    t = replace_once(
        t,
        '''  useEffect(() => {
    localStorage.setItem(keys.notes, notes);
  }, [notes, keys]);

  useEffect(() => {''',
        '''  useEffect(() => {
    localStorage.setItem(keys.notes, notes);
  }, [notes, keys]);
  useEffect(() => {
    localStorage.setItem(keys.batchDefaults, JSON.stringify(batchDefaults));
  }, [batchDefaults, keys]);

  useEffect(() => {''',
        "inbound defaults persist",
    )
    t = replace_once(
        t,
        '''    localStorage.removeItem(keys.fingerprint);
    setClearOpen(false);''',
        '''    localStorage.removeItem(keys.fingerprint);
    localStorage.removeItem(keys.batchDefaults);
    setBatchDefaults({
      batch_number: "",
      production_date: "",
      expiry_date: "",
    });
    setClearOpen(false);''',
        "inbound clear defaults",
    )
    t = replace_once(t, "        uomOptions\n      );", "        uomOptions,\n        batchDefaults\n      );", "inbound builder call")
    t = replace_once(
        t,
        '''        <div className="flex-1 min-h-0 overflow-auto mt-5">
          <table className="w-full text-sm min-w-[1120px]">''',
        '''        <div className="mx-4 mt-6 rounded-2xl border border-emerald-100 bg-emerald-50/60 p-4">
          <div className="mb-3">
            <p className="text-sm font-black text-emerald-950">
              {t("inventoryInbound.defaultBatchTitle")}
            </p>
            <p className="mt-1 text-xs font-semibold text-emerald-800/80">
              {t("inventoryInbound.defaultBatchHint")}
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <label className="text-xs font-black text-slate-600">
              {t("inventoryInbound.batchNumber")}
              <input
                value={batchDefaults.batch_number}
                onChange={(event) =>
                  setBatchDefaults((current) => ({
                    ...current,
                    batch_number: event.target.value,
                  }))
                }
                placeholder={t("inventoryInbound.defaultBatchPlaceholder")}
                className="mt-1.5 w-full rounded-lg border bg-white p-2"
              />
            </label>
            <label className="text-xs font-black text-slate-600">
              {t("inventoryInbound.productionDate")}
              <input
                type="date"
                value={batchDefaults.production_date}
                onChange={(event) =>
                  setBatchDefaults((current) => ({
                    ...current,
                    production_date: event.target.value,
                  }))
                }
                className="mt-1.5 w-full rounded-lg border bg-white p-2"
              />
            </label>
            <label className="text-xs font-black text-slate-600">
              {t("inventoryInbound.expiryDate")}
              <input
                type="date"
                value={batchDefaults.expiry_date}
                onChange={(event) =>
                  setBatchDefaults((current) => ({
                    ...current,
                    expiry_date: event.target.value,
                  }))
                }
                className="mt-1.5 w-full rounded-lg border bg-white p-2"
              />
            </label>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-auto mt-3">
          <table className="w-full text-sm min-w-[1120px]">''',
        "inbound default batch UI",
    )
    t = replace_once(
        t,
        '''                            placeholder={t("inventoryInbound.batchNumber")}
                            className="rounded-lg border p-2"''',
        '''                            placeholder={
                              batchDefaults.batch_number
                                ? t("inventoryInbound.overrideBatchPlaceholder", {
                                    batch: batchDefaults.batch_number,
                                  })
                                : t("inventoryInbound.batchNumber")
                            }
                            title={t("inventoryInbound.rowBatchOverrideHint")}
                            className="rounded-lg border p-2"''',
        "inbound override placeholder",
    )
    updated["inbound"] = t

    # Backend cost visibility.
    t = updated["warehouse"]
    t = replace_once(
        t,
        '''InventoryLocation, TenantOperationalPolicy, InventoryStockPolicy, InventoryBalance, InventoryMovement, InventoryMovementImpact, ProductBatch,
InventoryTransferHeader''',
        '''InventoryLocation, TenantOperationalPolicy, InventoryStockPolicy, InventoryBalance, InventoryMovement, InventoryMovementImpact, ProductBatch,
InventoryCostEvent, InventoryCostState,
InventoryTransferHeader''',
        "warehouse cost imports",
    )
    t = replace_once(
        t,
        '''        rows = (await db.execute(stmt)).all()

        result = []''',
        '''        rows = (await db.execute(stmt)).all()

        display_conversion_rows = (
            await db.execute(
                select(ProductUomConversion, UOM)
                .join(UOM, UOM.id == ProductUomConversion.from_uom_id)
                .filter(
                    ProductUomConversion.company_id == company_id,
                    ProductUomConversion.product_variant_id.in_(page_variant_ids),
                )
                .order_by(
                    ProductUomConversion.product_variant_id.asc(),
                    ProductUomConversion.id.asc(),
                )
            )
        ).all()
        display_candidates: dict[int, list[tuple[ProductUomConversion, UOM]]] = {}
        for conversion, display_uom in display_conversion_rows:
            display_candidates.setdefault(int(conversion.product_variant_id), []).append(
                (conversion, display_uom)
            )

        cost_state_rows = list(
            (
                await db.scalars(
                    select(InventoryCostState).filter(
                        InventoryCostState.company_id == company_id,
                        InventoryCostState.product_variant_id.in_(page_variant_ids),
                    )
                )
            ).all()
        )
        cost_state_by_variant = {
            int(row.product_variant_id): row for row in cost_state_rows
        }
        currency_code = await db.scalar(
            select(Company.currency_code).where(Company.id == company_id)
        )
        if not currency_code:
            raise RuntimeError("Company currency is unavailable.")

        result = []''',
        "live display/cost preload",
    )
    t = replace_once(
        t,
        '''            total_physical_available = on_hand + explicit_blocked + vehicle_total

            result.append({''',
        '''            total_physical_available = on_hand + explicit_blocked + vehicle_total

            direct_display = [
                (conversion, display_uom)
                for conversion, display_uom in display_candidates.get(int(variant.id), [])
                if int(conversion.to_uom_id) == int(variant.base_uom_id)
            ]
            if len(direct_display) == 1:
                display_conversion, display_uom = direct_display[0]
                display_numerator = Decimal(display_conversion.numerator)
                display_denominator = Decimal(display_conversion.denominator)
                if display_numerator <= 0 or display_denominator <= 0:
                    raise RuntimeError("Invalid display UOM conversion.")
            else:
                display_uom = base_uom
                display_numerator = Decimal("1")
                display_denominator = Decimal("1")

            cost_state = cost_state_by_variant.get(int(variant.id))
            average_unit_cost_base = (
                Decimal(cost_state.average_unit_cost)
                if cost_state is not None
                else Decimal("0")
            )
            inventory_value = (
                Decimal(cost_state.inventory_value)
                if cost_state is not None
                else Decimal("0")
            )
            average_unit_cost_display = (
                average_unit_cost_base * display_numerator / display_denominator
            )

            result.append({''',
        "live display/cost calc",
    )
    t = replace_once(
        t,
        '''                "base_uom_name": base_uom.name,
                "quantity_scale": variant.quantity_scale,''',
        '''                "base_uom_name": base_uom.name,
                "display_uom_id": int(display_uom.id),
                "display_uom_code": str(display_uom.code),
                "display_uom_name": str(display_uom.name),
                "display_numerator": canonical_quantity(display_numerator),
                "display_denominator": canonical_quantity(display_denominator),
                "currency_code": str(currency_code).upper(),
                "average_unit_cost_base": format(average_unit_cost_base.quantize(Decimal("0.000001")), "f"),
                "average_unit_cost_display": format(average_unit_cost_display.quantize(Decimal("0.000001")), "f"),
                "inventory_value": format(inventory_value.quantize(Decimal("0.000001")), "f"),
                "quantity_scale": variant.quantity_scale,''',
        "live response fields",
    )

    t = replace_once(
        t,
        '''        movement_ids = [row[0].id for row in rows]

        stmt_impacts = select(''',
        '''        movement_ids = [row[0].id for row in rows]

        batch_ids = sorted({
            int(row[0].batch_id)
            for row in rows
            if row[0].batch_id is not None
        })
        batch_number_by_id = {}
        if batch_ids:
            batch_number_by_id = {
                int(batch_id): str(batch_number)
                for batch_id, batch_number in (
                    await db.execute(
                        select(ProductBatch.id, ProductBatch.batch_number).filter(
                            ProductBatch.company_id == company_id,
                            ProductBatch.id.in_(batch_ids),
                        )
                    )
                ).all()
            }

        cost_events = list(
            (
                await db.scalars(
                    select(InventoryCostEvent).filter(
                        InventoryCostEvent.company_id == company_id,
                        InventoryCostEvent.inventory_movement_id.in_(movement_ids),
                    )
                )
            ).all()
        )
        cost_event_by_movement = {
            int(event.inventory_movement_id): event for event in cost_events
        }
        cost_uom_ids = sorted({
            int(event.input_uom_id)
            for event in cost_events
            if event.input_uom_id is not None
        })
        cost_uom_by_id = {}
        if cost_uom_ids:
            cost_uom_by_id = {
                int(row.id): row
                for row in (
                    await db.scalars(select(UOM).where(UOM.id.in_(cost_uom_ids)))
                ).all()
            }
        ledger_currency_code = await db.scalar(
            select(Company.currency_code).where(Company.id == company_id)
        )
        if not ledger_currency_code:
            raise RuntimeError("Company currency is unavailable.")

        stmt_impacts = select(''',
        "ledger cost preload",
    )
    t = replace_once(
        t,
        '''            result.append({
                "id": movement.id,''',
        '''            cost_event = cost_event_by_movement.get(int(movement.id))
            input_uom = (
                cost_uom_by_id.get(int(cost_event.input_uom_id))
                if cost_event is not None and cost_event.input_uom_id is not None
                else None
            )
            average_base_after = None
            if cost_event is not None:
                cost_quantity_after = Decimal(cost_event.quantity_after)
                cost_value_after = Decimal(cost_event.value_after)
                average_base_after = (
                    Decimal("0")
                    if cost_quantity_after == 0
                    else cost_value_after / cost_quantity_after
                )

            result.append({
                "id": movement.id,''',
        "ledger cost calc",
    )
    t = replace_once(
        t,
        '''                "type": movement.reference_type,
                "quantity": canonical_quantity(quantity_packs),
                "balance_before": balance_before,
                "balance_after": balance_after,
                "admin_name": admin_name or "غير معروف",''',
        '''                "type": movement.reference_type,
                "quantity": canonical_quantity(quantity_packs),
                "balance_before": balance_before,
                "balance_after": balance_after,
                "balance_scope": "BATCH" if chosen is not None else None,
                "batch_number": (
                    batch_number_by_id.get(int(movement.batch_id))
                    if movement.batch_id is not None
                    else None
                ),
                "currency_code": str(ledger_currency_code).upper(),
                "cost_method": str(cost_event.method) if cost_event is not None else None,
                "input_quantity": (
                    canonical_quantity(cost_event.input_quantity)
                    if cost_event is not None and cost_event.input_quantity is not None
                    else None
                ),
                "input_uom_code": str(input_uom.code) if input_uom is not None else None,
                "input_uom_name": str(input_uom.name) if input_uom is not None else None,
                "input_unit_cost": (
                    format(Decimal(cost_event.input_unit_cost).quantize(Decimal("0.000001")), "f")
                    if cost_event is not None and cost_event.input_unit_cost is not None
                    else None
                ),
                "total_cost": (
                    format(Decimal(cost_event.total_cost).quantize(Decimal("0.000001")), "f")
                    if cost_event is not None
                    else None
                ),
                "average_unit_cost_base_after": (
                    format(average_base_after.quantize(Decimal("0.000001")), "f")
                    if average_base_after is not None
                    else None
                ),
                "admin_name": admin_name or "غير معروف",''',
        "ledger response cost",
    )
    updated["warehouse"] = t

    # Schemas.
    t = updated["schemas"]
    t = replace_once(
        t,
        '''    base_uom_name: str = Field(..., min_length=1, max_length=50)
    quantity_scale: int = Field(..., ge=0, le=6)''',
        '''    base_uom_name: str = Field(..., min_length=1, max_length=50)
    display_uom_id: PositiveDbInt
    display_uom_code: str = Field(..., min_length=1, max_length=20)
    display_uom_name: str = Field(..., min_length=1, max_length=50)
    display_numerator: PositiveQuantity
    display_denominator: PositiveQuantity
    currency_code: str = Field(..., min_length=3, max_length=10)
    average_unit_cost_base: InventoryCostMoneyInput
    average_unit_cost_display: InventoryCostMoneyInput
    inventory_value: InventoryCostMoneyInput
    quantity_scale: int = Field(..., ge=0, le=6)''',
        "inventory schema additions",
    )
    t = replace_once(
        t,
        '''    balance_before: Optional[NonNegativeQuantity] = None
    balance_after: Optional[NonNegativeQuantity] = None
    admin_name: str = Field(..., min_length=1, max_length=120)''',
        '''    balance_before: Optional[NonNegativeQuantity] = None
    balance_after: Optional[NonNegativeQuantity] = None
    balance_scope: Optional[Literal["BATCH"]] = None
    batch_number: Optional[str] = Field(None, max_length=100)
    currency_code: str = Field(..., min_length=3, max_length=10)
    cost_method: Optional[Literal["MOVING_AVERAGE", "FIFO"]] = None
    input_quantity: Optional[PositiveQuantity] = None
    input_uom_code: Optional[str] = Field(None, max_length=20)
    input_uom_name: Optional[str] = Field(None, max_length=50)
    input_unit_cost: Optional[InventoryCostMoneyInput] = None
    total_cost: Optional[InventoryCostMoneyInput] = None
    average_unit_cost_base_after: Optional[InventoryCostMoneyInput] = None
    admin_name: str = Field(..., min_length=1, max_length=120)''',
        "ledger schema additions",
    )
    updated["schemas"] = t

    # Live stock contract.
    t = updated["live_contracts"]
    t = replace_once(
        t,
        '''  base_uom_id: number; base_uom_code: string; base_uom_name: string;
  quantity_scale: number; quantity_step: Quantity;''',
        '''  base_uom_id: number; base_uom_code: string; base_uom_name: string;
  display_uom_id:number; display_uom_code:string; display_uom_name:string;
  display_numerator:Quantity; display_denominator:Quantity; currency_code:string;
  average_unit_cost_base:string; average_unit_cost_display:string; inventory_value:string;
  quantity_scale: number; quantity_step: Quantity;''',
        "live type additions",
    )
    t = replace_once(
        t,
        '''    id,name:str(row.name,"name"),sku:optional(row.sku),base_uom_id:int(row.base_uom_id,"base_uom_id",1),base_uom_code:str(row.base_uom_code,"base_uom_code",20),base_uom_name:str(row.base_uom_name,"base_uom_name",50),quantity_scale:scale,quantity_step:parseQuantity(row.quantity_step,"quantity_step"),available_quantity:parseQuantity(row.available_quantity,"available_quantity",{allowZero:true}),reserved_quantity:parseQuantity(row.reserved_quantity,"reserved_quantity",{allowZero:true}),blocked_quantity:parseQuantity(row.blocked_quantity,"blocked_quantity",{allowZero:true}),total_quantity:parseQuantity(row.total_quantity,"total_quantity",{allowZero:true}),damaged_quantity:parseQuantity(row.damaged_quantity,"damaged_quantity",{allowZero:true}),minimum_quantity:parseQuantity(row.minimum_quantity,"minimum_quantity",{allowZero:true}),''',
        '''    id,name:str(row.name,"name"),sku:optional(row.sku),base_uom_id:int(row.base_uom_id,"base_uom_id",1),base_uom_code:str(row.base_uom_code,"base_uom_code",20),base_uom_name:str(row.base_uom_name,"base_uom_name",50),display_uom_id:int(row.display_uom_id,"display_uom_id",1),display_uom_code:str(row.display_uom_code,"display_uom_code",20),display_uom_name:str(row.display_uom_name,"display_uom_name",50),display_numerator:parseQuantity(row.display_numerator,"display_numerator"),display_denominator:parseQuantity(row.display_denominator,"display_denominator"),currency_code:str(row.currency_code,"currency_code",10),average_unit_cost_base:str(row.average_unit_cost_base,"average_unit_cost_base",64),average_unit_cost_display:str(row.average_unit_cost_display,"average_unit_cost_display",64),inventory_value:str(row.inventory_value,"inventory_value",64),quantity_scale:scale,quantity_step:parseQuantity(row.quantity_step,"quantity_step"),available_quantity:parseQuantity(row.available_quantity,"available_quantity",{allowZero:true}),reserved_quantity:parseQuantity(row.reserved_quantity,"reserved_quantity",{allowZero:true}),blocked_quantity:parseQuantity(row.blocked_quantity,"blocked_quantity",{allowZero:true}),total_quantity:parseQuantity(row.total_quantity,"total_quantity",{allowZero:true}),damaged_quantity:parseQuantity(row.damaged_quantity,"damaged_quantity",{allowZero:true}),minimum_quantity:parseQuantity(row.minimum_quantity,"minimum_quantity",{allowZero:true}),''',
        "live parser additions",
    )
    updated["live_contracts"] = t

    # Exact commercial formatter.
    t = updated["quantity"]
    anchor = '''export const formatQuantity = (value: Quantity, uomName: string): string =>
  `${canonicalFromScaled(scaled(value))} ${uomName}`;
'''
    updated["quantity"] = replace_once(
        t,
        anchor,
        anchor + '''
export function formatCommercialQuantity(
  value: Quantity,
  displayUomName: string,
  baseUomName: string,
  numerator: Quantity,
  denominator: Quantity,
): { primary: string; secondary: string | null } {
  const valueScaled = scaled(value);
  const numeratorScaled = scaled(numerator);
  const denominatorScaled = scaled(denominator);

  if (
    denominatorScaled !== 1_000_000n ||
    numeratorScaled <= 1_000_000n ||
    numeratorScaled % 1_000_000n !== 0n
  ) {
    return { primary: formatQuantity(value, baseUomName), secondary: null };
  }

  const factor = numeratorScaled / 1_000_000n;
  const factorScaled = factor * 1_000_000n;
  const whole = valueScaled / factorScaled;
  const remainder = valueScaled % factorScaled;
  const primary =
    remainder === 0n
      ? `${whole.toString()} ${displayUomName}`
      : `${whole.toString()} ${displayUomName} + ${canonicalFromScaled(remainder)} ${baseUomName}`;

  return {
    primary,
    secondary: `${canonicalFromScaled(valueScaled)} ${baseUomName}`,
  };
}
''',
        "quantity commercial formatter",
    )

    # Live UI.
    t = updated["live"]
    t = replace_once(
        t,
        '''import { compareQuantity, formatQuantity } from "./quantity";''',
        '''import { compareQuantity, formatCommercialQuantity } from "./quantity";
import { useTranslation } from "react-i18next";''',
        "live imports",
    )
    t = replace_once(
        t,
        '''}: Props) {
  const [searchInput, setSearchInput] = useState("");''',
        '''}: Props) {
  const { t } = useTranslation();
  const [searchInput, setSearchInput] = useState("");''',
        "live i18n hook",
    )
    t = replace_once(
        t,
        '''                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">في المستودع</th>''',
        '''                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">{t("inventoryLive.inWarehouse")}</th>''',
        "live inWarehouse",
    )
    t = replace_once(
        t,
        '''                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">
                  <div className="relative group flex items-center gap-1 border-b border-dashed border-slate-400 w-max cursor-help">
                    التوالف بالفرع''',
        '''                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">
                  <div className="relative group flex items-center gap-1 border-b border-dashed border-slate-400 w-max cursor-help">
                    {t("inventoryLive.averageCost")} <Info className="w-3 h-3" />
                    <div className="absolute top-full right-1/2 translate-x-1/2 mt-2 w-max max-w-[240px] text-center bg-slate-800 text-white text-[10px] px-2 py-1.5 rounded-lg hidden group-hover:block z-50 whitespace-normal shadow-xl">
                      {t("inventoryLive.averageCostHint")}
                    </div>
                  </div>
                </th>
                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">
                  <div className="relative group flex items-center gap-1 border-b border-dashed border-slate-400 w-max cursor-help">
                    التوالف بالفرع''',
        "live avg header",
    )
    t = replace_once(
        t,
        '''              {products.map((p) => {
                const isAlert = compareQuantity(p.minimum_quantity, "0") > 0 && compareQuantity(p.available_quantity, p.minimum_quantity) <= 0;
                return (''',
        '''              {products.map((p) => {
                const isAlert = compareQuantity(p.minimum_quantity, "0") > 0 && compareQuantity(p.available_quantity, p.minimum_quantity) <= 0;
                const displayName = t(`uom.${p.display_uom_code}`, { defaultValue: p.display_uom_name });
                const baseName = t(`uom.${p.base_uom_code}`, { defaultValue: p.base_uom_name });
                const renderQuantity = (value: typeof p.available_quantity) =>
                  formatCommercialQuantity(
                    value,
                    displayName,
                    baseName,
                    p.display_numerator,
                    p.display_denominator,
                  );
                return (''',
        "live render helper",
    )
    t = replace_once(
        t,
        '''                    <td className="px-4 py-3 text-emerald-700 font-semibold">
                      {formatQuantity(p.available_quantity, p.base_uom_name)}
                      {compareQuantity(p.blocked_quantity, "0") > 0 && (
                        <div className="text-[10px] font-bold text-amber-600 mt-0.5">
                          محجوب عن الصرف: {formatQuantity(p.blocked_quantity, p.base_uom_name)}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-violet-600 font-semibold">
                      {formatQuantity(p.reserved_quantity, p.base_uom_name)}
                    </td>
                    <td className="px-4 py-3 text-slate-700 font-bold border-l border-slate-100">
                      {formatQuantity(p.total_quantity, p.base_uom_name)}
                    </td>
                    <td className="px-4 py-3 text-red-600 font-bold bg-red-50/30">
                      {formatQuantity(p.damaged_quantity, p.base_uom_name)}
                    </td>''',
        '''                    <td className="px-4 py-3 text-emerald-700 font-semibold">
                      <div>{renderQuantity(p.available_quantity).primary}</div>
                      {renderQuantity(p.available_quantity).secondary && (
                        <div className="mt-0.5 text-[10px] text-slate-400">
                          {renderQuantity(p.available_quantity).secondary}
                        </div>
                      )}
                      {compareQuantity(p.blocked_quantity, "0") > 0 && (
                        <div className="text-[10px] font-bold text-amber-600 mt-0.5">
                          {t("inventoryLive.blocked")}: {renderQuantity(p.blocked_quantity).primary}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-violet-600 font-semibold">
                      {renderQuantity(p.reserved_quantity).primary}
                    </td>
                    <td className="px-4 py-3 text-slate-700 font-bold border-l border-slate-100">
                      {renderQuantity(p.total_quantity).primary}
                    </td>
                    <td className="px-4 py-3 text-slate-700 font-black tabular-nums">
                      {Number(p.average_unit_cost_display).toLocaleString(undefined, {
                        minimumFractionDigits: 3,
                        maximumFractionDigits: 6,
                      })}{" "}{p.currency_code} / {displayName}
                    </td>
                    <td className="px-4 py-3 text-red-600 font-bold bg-red-50/30">
                      {renderQuantity(p.damaged_quantity).primary}
                    </td>''',
        "live commercial rows",
    )
    t = t.replace("colSpan={6}", "colSpan={7}")
    updated["live"] = t

    # Ledger contract.
    t = updated["ledger_contracts"]
    t = replace_once(
        t,
        '''  balance_before:Quantity|null; balance_after:Quantity|null; admin_name:string;
  reference:string|null; notes:string|null; date:string;''',
        '''  balance_before:Quantity|null; balance_after:Quantity|null; balance_scope:"BATCH"|null;
  batch_number:string|null; currency_code:string; cost_method:"MOVING_AVERAGE"|"FIFO"|null;
  input_quantity:Quantity|null; input_uom_code:string|null; input_uom_name:string|null;
  input_unit_cost:string|null; total_cost:string|null; average_unit_cost_base_after:string|null;
  admin_name:string; reference:string|null; notes:string|null; date:string;''',
        "ledger type additions",
    )
    t = replace_once(
        t,
        '''return{id,product_variant_id:int(row.product_variant_id,"product_variant_id",1),product_name:str(row.product_name,"product_name",200),base_uom_id:int(row.base_uom_id,"base_uom_id",1),base_uom_code:str(row.base_uom_code,"base_uom_code",20),quantity_scale:scale,quantity_step:parseQuantity(row.quantity_step,"quantity_step"),type:str(row.type,"type",50),quantity,balance_before:before,balance_after:after,admin_name:str(row.admin_name,"admin_name",120),reference:optional(row.reference,"reference"),notes:optional(row.notes,"notes"),date};''',
        '''return{id,product_variant_id:int(row.product_variant_id,"product_variant_id",1),product_name:str(row.product_name,"product_name",200),base_uom_id:int(row.base_uom_id,"base_uom_id",1),base_uom_code:str(row.base_uom_code,"base_uom_code",20),quantity_scale:scale,quantity_step:parseQuantity(row.quantity_step,"quantity_step"),type:str(row.type,"type",50),quantity,balance_before:before,balance_after:after,balance_scope:row.balance_scope===null?null:(row.balance_scope==="BATCH"?"BATCH":(()=>{throw new Error("نطاق الرصيد غير صالح.")})()),batch_number:optional(row.batch_number,"batch_number"),currency_code:str(row.currency_code,"currency_code",10),cost_method:row.cost_method===null?null:(row.cost_method==="MOVING_AVERAGE"||row.cost_method==="FIFO"?row.cost_method:(()=>{throw new Error("طريقة التكلفة غير صالحة.")})()),input_quantity:row.input_quantity===null?null:parseQuantity(row.input_quantity,"input_quantity"),input_uom_code:optional(row.input_uom_code,"input_uom_code"),input_uom_name:optional(row.input_uom_name,"input_uom_name"),input_unit_cost:row.input_unit_cost===null?null:str(row.input_unit_cost,"input_unit_cost",64),total_cost:row.total_cost===null?null:str(row.total_cost,"total_cost",64),average_unit_cost_base_after:row.average_unit_cost_base_after===null?null:str(row.average_unit_cost_base_after,"average_unit_cost_base_after",64),admin_name:str(row.admin_name,"admin_name",120),reference:optional(row.reference,"reference"),notes:optional(row.notes,"notes"),date};''',
        "ledger parser additions",
    )
    updated["ledger_contracts"] = t

    # Ledger UI.
    t = updated["ledger"]
    t = replace_once(
        t,
        '''import { useState, useEffect, useCallback, useRef } from "react";''',
        '''import { useState, useEffect, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";''',
        "ledger i18n import",
    )
    t = replace_once(
        t,
        '''  const authenticatedFetch = useAuthFetch();
  const access = useInventoryAccess(locationId);''',
        '''  const authenticatedFetch = useAuthFetch();
  const { t } = useTranslation();
  const access = useInventoryAccess(locationId);''',
        "ledger i18n hook",
    )
    t = replace_once(
        t,
        '''                <th className="px-4 py-3 text-xs font-bold text-slate-500">الرصيد قبل</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">الكمية</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">الرصيد بعد</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">المشرف</th>''',
        '''                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.batch")}</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.batchBalanceBefore")}</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.quantity")}</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.batchBalanceAfter")}</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.purchaseCost")}</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.averageAfter")}</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">المشرف</th>''',
        "ledger headers",
    )
    t = t.replace("colSpan={9}", "colSpan={12}")
    t = replace_once(
        t,
        '''                    <td className="px-4 py-3 font-bold text-slate-800">{entry.product_name}</td>
                    <td className="px-4 py-3 text-slate-500 font-semibold text-xs">{entry.balance_before === null ? "—" : formatQuantity(entry.balance_before, entry.base_uom_code)}</td>
                    <td className={`px-4 py-3 font-bold text-xs ${isNeg ? "text-red-600" : "text-emerald-600"}`}>{isNeg ? "-" : "+"}{formatQuantity(absoluteQuantity(entry.quantity), entry.base_uom_code)}</td>''',
        '''                    <td className="px-4 py-3 font-bold text-slate-800">{entry.product_name}</td>
                    <td className="px-4 py-3 text-xs font-black text-slate-600">{entry.batch_number || "—"}</td>
                    <td className="px-4 py-3 text-slate-500 font-semibold text-xs">{entry.balance_before === null ? "—" : formatQuantity(entry.balance_before, t(`uom.${entry.base_uom_code}`, { defaultValue: entry.base_uom_code }))}</td>
                    <td className={`px-4 py-3 font-bold text-xs ${isNeg ? "text-red-600" : "text-emerald-600"}`}>{isNeg ? "-" : "+"}{entry.input_quantity && entry.input_uom_code ? formatQuantity(entry.input_quantity, t(`uom.${entry.input_uom_code}`, { defaultValue: entry.input_uom_name || entry.input_uom_code })) : formatQuantity(absoluteQuantity(entry.quantity), t(`uom.${entry.base_uom_code}`, { defaultValue: entry.base_uom_code }))}</td>''',
        "ledger batch/movement cells",
    )
    t = replace_once(
        t,
        '''{entry.balance_after === null ? "—" : formatQuantity(entry.balance_after, entry.base_uom_code)}</td>
                    <td className="px-4 py-3 text-slate-600 font-semibold text-xs">{entry.admin_name}</td>''',
        '''{entry.balance_after === null ? "—" : formatQuantity(entry.balance_after, t(`uom.${entry.base_uom_code}`, { defaultValue: entry.base_uom_code }))}</td>
                    <td className="px-4 py-3 text-slate-700 font-black text-xs">
                      {entry.input_unit_cost && entry.input_uom_code
                        ? `${entry.input_unit_cost} ${entry.currency_code} / ${t(`uom.${entry.input_uom_code}`, { defaultValue: entry.input_uom_name || entry.input_uom_code })}`
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-slate-700 font-black text-xs">
                      {entry.average_unit_cost_base_after
                        ? `${entry.average_unit_cost_base_after} ${entry.currency_code} / ${t(`uom.${entry.base_uom_code}`, { defaultValue: entry.base_uom_code })}`
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-slate-600 font-semibold text-xs">{entry.admin_name}</td>''',
        "ledger cost cells",
    )
    updated["ledger"] = t

    # No blank screen while location access is refreshing.
    t = updated["main_inventory"]
    t = replace_once(
        t,
        '''      {/* ═══ Tab Content ═══ */}
      <div className="inventory-content flex-1 min-h-0 flex flex-col">
        {selectedLocationId === null''',
        '''      {/* ═══ Tab Content ═══ */}
      <div className="inventory-content flex-1 min-h-0 flex flex-col">
        {selectedLocationId !== null && locationAccess.isPending && (
          <div className="inventory-empty-state flex flex-1 items-center justify-center gap-2 px-6 text-center font-bold text-slate-500">
            <RefreshCcw className="h-5 w-5 animate-spin" />
            جاري تحميل بيانات المستودع...
          </div>
        )}
        {selectedLocationId === null''',
        "location loading state",
    )
    updated["main_inventory"] = t

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
        policySaved: "The inventory costing method was saved.",''',
        "en inbound defaults i18n",
    )
    t = replace_once(
        t,
        '''      uom: {
        CARTON: "كرتونة",''',
        '''      inventoryLive: {
        inWarehouse: "في المستودع",
        averageCost: "متوسط التكلفة",
        averageCostHint:
          "متوسط تكلفة الشركة الحالي لهذا المنتج، معروض بوحدة العرض التجارية عند توفر تحويل واحد واضح.",
        blocked: "محجوب عن الصرف",
      },
      inventoryLedger: {
        batch: "الدفعة",
        batchBalanceBefore: "رصيد الدفعة قبل",
        quantity: "الكمية",
        batchBalanceAfter: "رصيد الدفعة بعد",
        purchaseCost: "تكلفة الشراء",
        averageAfter: "متوسط التكلفة بعد الحركة",
      },
      uom: {
        CARTON: "كرتونة",''',
        "ar inventory i18n",
    )
    t = replace_once(
        t,
        '''      uom: {
        CARTON: "Carton",''',
        '''      inventoryLive: {
        inWarehouse: "In warehouse",
        averageCost: "Average cost",
        averageCostHint:
          "The company's current average cost for this product, shown in the commercial display unit when one unambiguous conversion is configured.",
        blocked: "Blocked from issue",
      },
      inventoryLedger: {
        batch: "Batch",
        batchBalanceBefore: "Batch balance before",
        quantity: "Quantity",
        batchBalanceAfter: "Batch balance after",
        purchaseCost: "Purchase cost",
        averageAfter: "Average cost after movement",
      },
      uom: {
        CARTON: "Carton",''',
        "en inventory i18n",
    )
    t = replace_once(
        t,
        '''          VALIDATION_ERROR: "بيانات الطلب غير صالحة. راجع الحقول المدخلة.",''',
        '''          OPERATIONS_RESPONSE_INVALID: "استجابة غرفة العمليات غير صالحة أو غير مكتملة.",
          VALIDATION_ERROR: "بيانات الطلب غير صالحة. راجع الحقول المدخلة.",''',
        "ar operations error",
    )
    t = replace_once(
        t,
        '''          VALIDATION_ERROR: "The request data is invalid. Review the entered fields.",''',
        '''          OPERATIONS_RESPONSE_INVALID: "The operations response is invalid or incomplete.",
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

check("batchDefaults" in inbound and "defaultBatchTitle" in inbound, "document batch defaults UI")
check("defaults.batch_number" in contracts, "batch defaults resolved in payload builder")
check('"balance_scope": "BATCH"' in warehouse, "ledger balance explicitly batch scoped")
check("InventoryCostEvent" in warehouse, "ledger cost evidence source")
check("average_unit_cost_display" in warehouse and "InventoryCostState" in warehouse, "live average cost visibility")
check("display_uom_code" in schemas and "display_numerator" in schemas, "commercial display UOM contract")
check("formatCommercialQuantity" in live, "commercial quantity display")
check("inventoryLedger.batchBalanceBefore" in ledger, "ledger labels batch balance honestly")
check("parseDriverDataList(data)" in operations, "operations response validated before setState")
check(resources.count("OPERATIONS_RESPONSE_INVALID") >= 2, "operations error translated ar/en")
check(resources.count("defaultBatchTitle") >= 2, "batch-default UI translated ar/en")
check(resources.count("averageCostHint") >= 2, "cost visibility translated ar/en")

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
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.repo_root:
        raise SystemExit("--repo-root is required unless --self-test is used")
    repo = Path(args.repo_root).resolve()
    changed = patch(repo)
    print("STAGE76_INVENTORY_UX_COST_VISIBILITY_PATCH_APPLIED_OK")
    print("CHANGED_FILES=")
    for item in changed:
        print(f"  {item}")


if __name__ == "__main__":
    main()
