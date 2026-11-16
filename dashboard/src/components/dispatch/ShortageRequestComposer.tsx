import { Minus, Plus, Send, Trash2, Eraser } from "lucide-react";
import { useTranslation } from "react-i18next";
import { CustomSelect } from "@/components/ui/custom-select";
import type { Shop, Zone } from "@/types/dispatch";
import { dispatchUiText } from "@/features/dispatch/dispatchUiText";
import { ShortageShopPicker } from "./ShortageShopPicker";
import { ShortageProductPicker } from "./ShortageProductPicker";

type DraftItem = { productId: string; productName: string; quantity: number };
export function ShortageRequestComposer({
  zones, shops, shopId, zoneId, onChooseShop,
  drivers, driverId, onDriverChange, productScope, draft,
  onQuickAdd, onUpdateQuantity, onRemove, onClear, onSubmit,
  editing, onCancelEdit, blocked,
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
  draft: DraftItem[];
  onQuickAdd: (id: string, name: string) => void;
  onUpdateQuantity: (index: number, quantity: number) => void;
  onRemove: (index: number) => void;
  onClear: () => void;
  onSubmit: () => void;
  editing: boolean;
  onCancelEdit: () => void;
  blocked: boolean;
}) {
  const { i18n } = useTranslation();
  const t = (key: Parameters<typeof dispatchUiText>[1], vars?: Record<string, string | number>) =>
    dispatchUiText(i18n.language, key, vars ?? {});
  const validShop = shops.some(shop => shop.id === shopId && shop.zoneId === zoneId &&
    !shop.archived && zones.some(zone => zone.id === shop.zoneId));
  const validDraft = draft.length > 0 && draft.every(item =>
    Number.isSafeInteger(item.quantity) && item.quantity > 0);
  const submitReady = validShop && validDraft && !blocked;
  const number = new Intl.NumberFormat(i18n.language.startsWith("ar") ? "ar" : "en");

  return <fieldset disabled={blocked} className="min-w-0 space-y-4" data-testid="shortage-quick-composer">
    {editing && <p role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm font-semibold text-amber-900">
      {t("shortageEditMode")}
    </p>}
    <ShortageShopPicker shops={shops} zones={zones} shopId={shopId} zoneId={zoneId}
      disabled={editing || blocked} onChoose={onChooseShop}/>
    <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(18rem,0.92fr)] xl:items-start">
      <ShortageProductPicker scope={productScope} drafted={draft} onAdd={onQuickAdd} disabled={blocked}/>
      <section className="min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 bg-slate-50 px-4 py-3">
          <h3 className="text-sm font-bold text-slate-800">{t("shortageQuickDraftTitle", { count: number.format(draft.length) })}</h3>
          {draft.length > 0 && <button type="button" onClick={onClear}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-lg px-2 text-xs font-semibold text-slate-600 hover:bg-red-50 hover:text-red-700">
            <Eraser className="h-4 w-4" aria-hidden="true"/>{t("shortageClear")}
          </button>}
        </div>
        {draft.length === 0 ? <p className="px-4 py-10 text-center text-sm text-slate-500">{t("shortageQuickDraftEmpty")}</p>
          : <div className="max-h-64 divide-y divide-slate-100 overflow-y-auto">
          {draft.map((item, index) => <div key={item.productId} className="flex min-w-0 flex-wrap items-center gap-2 p-3">
            <span className="min-w-[7rem] flex-1 break-words text-sm font-semibold text-slate-800">{item.productName}</span>
            <div className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-slate-200">
              <button type="button" disabled={item.quantity <= 1} onClick={() => onUpdateQuantity(index, item.quantity - 1)}
                aria-label={t("shortageDecrease", { product: item.productName })}
                className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-700 hover:bg-slate-100 disabled:opacity-30">
                <Minus aria-hidden="true" className="h-4 w-4"/>
              </button>
              <input type="number" min="1" step="1" inputMode="numeric"
                aria-label={t("shortageQuickQuantityOf", { product: item.productName })}
                value={item.quantity}
                onChange={event => onUpdateQuantity(index, Number(event.target.value))}
                onFocus={event => event.currentTarget.select()}
                className="h-9 w-14 rounded border-0 bg-transparent text-center text-sm font-bold tabular-nums text-slate-900 outline-none focus-visible:ring-2 focus-visible:ring-blue-400"/>
              <button type="button" onClick={() => onUpdateQuantity(index, item.quantity + 1)}
                aria-label={t("shortageIncrease", { product: item.productName })}
                className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-700 hover:bg-slate-100">
                <Plus aria-hidden="true" className="h-4 w-4"/>
              </button>
            </div>
            <button type="button" onClick={() => onRemove(index)}
              aria-label={t("shortageRemove", { product: item.productName })}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-red-50 hover:text-red-700">
              <Trash2 aria-hidden="true" className="h-4 w-4"/>
            </button>
          </div>)}
        </div>}
        <div className="space-y-3 border-t border-slate-100 p-4">
          <div className="flex items-center gap-2 text-sm font-bold text-slate-800">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#1e87bb] text-xs text-white">3</span>
            <span>{t("shortageQuickDriverStep")}</span>
          </div>
          <CustomSelect label={t("shortageDriver")}
            options={[{ id: "", label: t("shortageNoDriver") }, ...drivers.map(driver => ({
              id: driver.id, label: driver.name,
            }))]}
            value={driverId} onChange={onDriverChange} disabled={editing}/>
          {!driverId && <p className="text-xs leading-relaxed text-amber-800">{t("shortageQuickUnassignedNotice")}</p>}
          <button type="button" disabled={!submitReady} onClick={onSubmit}
            className="flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-emerald-700 px-4 py-3 text-sm font-bold text-white hover:bg-emerald-800 focus-visible:ring-2 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-40">
            <Send aria-hidden="true" className="h-4 w-4"/>
            {t(editing ? "shortageSaveEdit" : "shortageQuickSend", { count: number.format(draft.length) })}
          </button>
          {!validShop && <p role="status" className="text-center text-xs text-slate-500">{t("shortageQuickChooseShopFirst")}</p>}
          {editing && <button type="button" onClick={onCancelEdit}
            className="min-h-10 w-full rounded-lg border border-slate-300 bg-white text-xs font-semibold text-slate-700 hover:bg-slate-50">
            {t("shortageCancelEdit")}
          </button>}
        </div>
      </section>
    </div>
  </fieldset>;
}
