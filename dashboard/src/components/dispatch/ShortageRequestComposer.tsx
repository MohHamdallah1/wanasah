import { ClipboardList, Eraser, Minus, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Shop, Zone } from "@/types/dispatch";
import { dispatchUiText } from "@/features/dispatch/dispatchUiText";
import { ShortageShopPicker } from "./ShortageShopPicker";
import { ShortageProductPicker } from "./ShortageProductPicker";
import { ShortageDriverPicker } from "./ShortageDriverPicker";
import { useShortageVehicleAvailability } from "@/features/dispatch/useShortageVehicleAvailability";

type RequestItem = { productId: string; productName: string; quantity: number };

/** One visible command workspace; the in-memory rows are NOT a second draft workflow. */
export function ShortageRequestComposer({
  zones, shops, shopId, zoneId, onChooseShop,
  drivers, driverId, onDriverChange, productScope, draft,
  onQuickAdd, onUpdateQuantity, onRemove, onClear,
  editing, blocked, allowUnassigned, onAllowUnassigned,
}: {
  zones: readonly Zone[];
  shops: readonly Shop[];
  shopId: string;
  zoneId: string;
  onChooseShop: (zoneId: string, shopId: string) => void;
  drivers: { id: string; name: string }[];
  driverId: string;
  onDriverChange: (id: string) => void;
  productScope: string | null;
  draft: RequestItem[];
  onQuickAdd: (id: string, name: string) => void;
  onUpdateQuantity: (index: number, quantity: number) => void;
  onRemove: (index: number) => void;
  onClear: () => void;
  editing: boolean;
  blocked: boolean;
  allowUnassigned: boolean;
  onAllowUnassigned: (value: boolean) => void;
}) {
  const { i18n } = useTranslation();
  const t = (key: Parameters<typeof dispatchUiText>[1], values?: Record<string, string | number>) =>
    dispatchUiText(i18n.language, key, values ?? {});
  const number = new Intl.NumberFormat(i18n.language.startsWith("ar") ? "ar" : "en");
  const unitCount = draft.reduce((sum, item) =>
    sum + (Number.isSafeInteger(item.quantity) && item.quantity > 0 ? item.quantity : 0), 0);
  const stock = useShortageVehicleAvailability({
    driverId, scope: productScope, productIds: draft.map(item => item.productId),
  });
  const stockSummary = draft.reduce((result, item) => {
    const line = stock.byProduct.get(item.productId);
    if (stock.status !== "VERIFIED" || !line) result.unknown++;
    else if (Number(line.available_base) > 0) result.present++;
    else result.missing++;
    return result;
  }, {present:0,missing:0,unknown:0});

  return <fieldset disabled={blocked} data-testid="shortage-quick-composer"
    className="min-w-0 space-y-4">
    {editing && <p role="status"
      className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-900">
      {t("shortageEditMode")}
    </p>}
    <div className="min-w-0 rounded-2xl border border-slate-200 bg-slate-50/80 px-4 py-4 shadow-sm sm:px-5">
      <div className="grid min-w-0 grid-cols-1 items-start gap-3 lg:grid-cols-3">
        <ShortageShopPicker zones={zones} shops={shops} zoneId={zoneId} shopId={shopId}
          disabled={editing || blocked} onChoose={onChooseShop}/>
        <ShortageDriverPicker drivers={drivers} driverId={driverId}
          onChange={onDriverChange} disabled={blocked} editing={editing}
          allowUnassigned={allowUnassigned} onAllowUnassigned={onAllowUnassigned}/>
      </div>
    </div>

    <ShortageProductPicker scope={productScope} drafted={draft} driverId={driverId} onAdd={onQuickAdd} disabled={blocked}/>
    <section className="flex h-60 min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl border border-sky-200 bg-white shadow-sm"
        data-testid="shortage-current-order">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-sky-100 bg-sky-50/80 px-4 py-3">
          <div className="flex items-center gap-2">
            <ClipboardList className="h-5 w-5 text-sky-800" aria-hidden="true"/>
            <h3 className="text-sm font-bold text-slate-900">{t("shortageStudioOrder")}</h3>
          </div>
          <span className="rounded-lg bg-white px-2.5 py-1 text-xs font-bold tabular-nums text-sky-900">
            {t("shortageStudioLineCount", {count: number.format(draft.length)})}
          </span>
        </header>
        {draft.length > 0 && <div className="flex shrink-0 items-center justify-between gap-2 px-4 pt-2">
          <span className="min-w-0 text-xs text-slate-500">
            {t("shortageStudioUnitCount", {count: number.format(unitCount)})}
            {driverId && <span className="block text-[11px] leading-4 text-slate-500">
              {t("shortageVehicleSummary", {
                present: number.format(stockSummary.present),
                missing: number.format(stockSummary.missing),
                unknown: number.format(stockSummary.unknown),
              })}
            </span>}
          </span>
          <button type="button" onClick={onClear}
            className="inline-flex min-h-9 items-center gap-1 rounded-lg px-2 text-xs font-semibold text-slate-500 transition hover:bg-red-50 hover:text-red-700">
            <Eraser aria-hidden="true" className="h-4 w-4"/>{t("shortageStudioClear")}
          </button>
        </div>}
        {draft.length === 0 ? <div className="grid min-h-0 flex-1 place-content-center justify-items-center gap-2 overflow-y-auto px-4 py-3 text-center">
          <span className="grid h-14 w-14 place-items-center rounded-2xl bg-slate-100 text-slate-400">
            <ClipboardList aria-hidden="true" className="h-7 w-7"/>
          </span>
          <p className="text-sm font-semibold text-slate-600">{t("shortageStudioEmptyOrder")}</p>
          <p className="max-w-48 text-xs leading-5 text-slate-400">{t("shortageStudioTapProduct")}</p>
        </div> :
          <div className="min-h-0 flex-1 divide-y divide-slate-100 overflow-y-auto overscroll-contain px-3 py-1">
            {draft.map((item, index) => <div key={item.productId} className="flex min-w-0 items-center gap-2 py-3">
              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-slate-100 text-xs font-bold text-slate-500">
                {number.format(index+1)}
              </span>
              <span className="min-w-0 flex-1 break-words text-xs font-semibold leading-5 text-slate-800">
                {item.productName}
                {driverId && <span className="block text-[11px] font-normal leading-4 text-slate-500">
                  {stock.status !== "VERIFIED" || !stock.byProduct.get(item.productId)
                    ? t("shortageVehicleUnknown")
                    : Number(stock.byProduct.get(item.productId)!.available_base) > 0
                      ? t("shortageVehicleAvailable", {
                          count: stock.byProduct.get(item.productId)!.available_base,
                          unit: stock.byProduct.get(item.productId)!.base_uom,
                        })
                      : t("shortageVehicleNeedsSupply")}
                </span>}
              </span>
              <div className="inline-flex shrink-0 items-center rounded-lg border border-slate-200 bg-slate-50">
                <button type="button" disabled={item.quantity<=1}
                  onClick={() => onUpdateQuantity(index, item.quantity-1)}
                  aria-label={t("shortageDecrease", {product: item.productName})}
                  className="grid h-9 w-8 place-items-center rounded-lg text-slate-700 hover:bg-slate-200 disabled:opacity-30">
                  <Minus className="h-3.5 w-3.5" aria-hidden="true"/>
                </button>
                <input type="number" min="1" step="1" inputMode="numeric"
                  aria-label={t("shortageQuickQuantityOf", {product: item.productName})}
                  value={item.quantity} onChange={e => onUpdateQuantity(index, Number(e.target.value))}
                  onFocus={e => e.currentTarget.select()}
                  className="h-9 w-10 border-0 bg-transparent text-center text-xs font-bold tabular-nums text-slate-900 outline-none focus-visible:ring-2 focus-visible:ring-sky-300"/>
                <button type="button" disabled={!Number.isSafeInteger(item.quantity) || item.quantity>=Number.MAX_SAFE_INTEGER}
                  onClick={() => onUpdateQuantity(index, item.quantity+1)}
                  aria-label={t("shortageIncrease", {product: item.productName})}
                  className="grid h-9 w-8 place-items-center rounded-lg text-slate-700 hover:bg-slate-200 disabled:opacity-30">
                  <Plus className="h-3.5 w-3.5" aria-hidden="true"/>
                </button>
              </div>
              <button type="button" onClick={() => onRemove(index)}
                aria-label={t("shortageStudioRemoveProduct", {product: item.productName})}
                className="grid h-9 w-8 shrink-0 place-items-center rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-700">
                <Trash2 aria-hidden="true" className="h-4 w-4"/>
              </button>
            </div>)}
          </div>}
      </section>
  </fieldset>;
}
