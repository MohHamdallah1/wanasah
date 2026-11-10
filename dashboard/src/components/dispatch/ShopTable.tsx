import { GripVertical, Pencil, Archive } from "lucide-react";
import { Shop, Zone } from "@/types/dispatch";
import { SequenceInput } from "@/components/ui/sequence-input";
import { useMemo } from "react";
import { canReorderShop } from "@/features/dispatch/shopOrder/scope";
import { shopOrderText } from "@/features/dispatch/shopOrder/messages";
import { dispatchUiText } from "@/features/dispatch/dispatchUiText";
import { useTenantIdentity } from "@/features/tenantIdentity/useTenantIdentity";
import { formatLocaleMoney } from "@/lib/localeNumbers";

interface ShopTableProps {
  shops: Shop[];
  zones: Zone[];
  isEditMode: boolean;
  isSaving: boolean;
  language: string;
  selectedShopIds: string[];
  allFilteredShops: Shop[] | null;
  selectedZoneIdForZones: string;
  onToggleSelectAll: () => void;
  onToggleSelectShop: (id: string) => void;
  onSequenceChange: (shopId: string, newSeq: number) => void;
  onEditShop: (shop: Shop) => void;
  onArchiveShop: (id: string) => void;
  onDragStart: (e: React.DragEvent, id: string) => void;
  onDrop: (e: React.DragEvent, targetId: string) => void;
}

export function ShopTable({
  shops,
  zones,
  isEditMode,
  isSaving,
  language,
  selectedShopIds,
  allFilteredShops,
  selectedZoneIdForZones,
  onToggleSelectAll,
  onToggleSelectShop,
  onSequenceChange,
  onEditShop,
  onArchiveShop,
  onDragStart,
  onDrop,
}: ShopTableProps) {
  const tenantCurrency = useTenantIdentity().data?.currency_code;
  const label = (key: Parameters<typeof dispatchUiText>[1], values?: Record<string, string | number>) =>
    dispatchUiText(language, key, values);
  // +++ الكي الجراحي: بناء فهرس (Map) للمناطق مرة واحدة فقط لجعل سرعة البحث O(1) +++
  const zonesMap = useMemo(() => {
    const map = new Map<string, string>();
    zones.forEach(z => map.set(z.id, z.name));
    return map;
  }, [zones]);
  
  return (
    <div className="dispatch-shop-table flex-1 overflow-x-auto overflow-y-auto" dir={language.startsWith("ar") ? "rtl" : "ltr"}>
      <table className="w-full min-w-[760px] text-sm">
        <thead className="sticky top-0 bg-white shadow-sm z-10">
          <tr className="text-slate-400 text-[10px] uppercase border-b border-slate-100">
            {isEditMode && (
              <th scope="col" className="w-12 p-3 px-4">
                <input
                  type="checkbox"
                  checked={shops.length > 0 && selectedShopIds.length === shops.length}
                  onChange={onToggleSelectAll}
                  aria-label={label("shopSelectAll")}
                  className="w-4 h-4 rounded border-slate-300 text-[#1e87bb] focus:ring-[#1e87bb]/20 cursor-pointer"
                />
              </th>
            )}
            <th className="w-20 p-3 text-center">{label("shopOrder")}</th>
            <th className="text-start p-3">{label("shop")}</th>
            <th className="text-start p-3">{label("shopOwnerPhone")}</th>
            <th className="p-4 text-start font-bold text-slate-500">{label("zone")}</th>
            <th className="text-center p-3">{label("shopDebt")}</th>
            {isEditMode && <th className="w-24 p-3"></th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">
          {shops.length === 0 ? (
            <tr>
              <td colSpan={isEditMode ? 7 : 5} className="p-12 text-center text-slate-400">{label("shopEmpty")}</td>
            </tr>
          ) : (
            shops.map((shop) => {
              const orderEditable = isEditMode && !isSaving && canReorderShop(shop, selectedZoneIdForZones);
              return <tr
                key={shop.id}
                draggable={orderEditable}
                onDragStart={(e) => orderEditable && onDragStart(e, shop.id)}
                onDragOver={(e) => { if (orderEditable) e.preventDefault(); }}
                onDrop={(e) => { if (orderEditable) onDrop(e, shop.id); }}
                className={`group hover:bg-slate-50/80 transition-colors ${isEditMode ? 'cursor-default' : 'cursor-default'}`}
              >
                {isEditMode && (
                  <td className="p-3 px-4 text-center flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={selectedShopIds.includes(shop.id)}
                      onChange={() => onToggleSelectShop(shop.id)}
                      aria-label={label("shopSelect", { shop: shop.name })}
                      className="w-4 h-4 rounded border-slate-300 text-[#1e87bb] focus:ring-[#1e87bb]/20 cursor-pointer"
                    />
                    <GripVertical aria-hidden="true" className={`w-4 h-4 ${orderEditable ? "text-slate-300 group-hover:text-slate-500 cursor-grab active:cursor-grabbing" : "text-slate-200"}`} />
                  </td>
                )}
                <td className="p-3 text-center">
                  {orderEditable ? (
                    <label className="inline-block">
                      <span className="sr-only">{shopOrderText(language, "orderInput", { shop: shop.name })}</span>
                      <SequenceInput value={shop.sequence} onCommit={(n) => onSequenceChange(shop.id, n)} />
                    </label>
                  ) : isEditMode ? (
                    <input type="number" disabled value={shop.sequence}
                      aria-label={shopOrderText(language, "outsideZone")}
                      title={shopOrderText(language, "outsideZone")}
                      className="w-12 h-8 text-center rounded-lg border border-slate-200 bg-slate-100 text-slate-400" />
                  ) : (
                    <span className="font-bold text-slate-700">{shop.sequence}</span>
                  )}
                </td>
                <td className="p-3">
                  <div className="flex flex-col">
                    <p className="font-bold text-slate-800">
                      {shop.name}
                      {allFilteredShops !== null && (
                        <span className="ms-2 text-[10px] bg-emerald-50 text-[#1e87bb] px-1.5 py-0.5 rounded-md font-bold">
                          {zonesMap.get(shop.zoneId) || label("shopNoZone")}
                        </span>
                      )}
                    </p>
                    {shop.mapLink ? (
                      <a href={shop.mapLink} target="_blank" rel="noreferrer" className="text-[10px] text-emerald-600 font-medium hover:underline w-fit">{label("shopShowMap")}</a>
                    ) : (
                      <span className="text-[10px] text-slate-400">{label("shopNoMap")}</span>
                    )}
                  </div>
                </td>
                <td className="p-3">
                  <p className="font-medium text-slate-700">{shop.owner}</p>
                  <p className="text-xs text-slate-400">{shop.phone}</p>
                </td>
                <td className="p-4 text-slate-600 font-medium">
                  {zonesMap.get(shop.zoneId) || label("shopNoZone")}
                </td>
                <td className="p-3 text-center">
                  <span className={`px-2 py-1 rounded-lg text-xs font-bold ${shop.initialDebt !== null && shop.initialDebt > 0 ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-500'}`}>
                    {shop.initialDebt === null || shop.financeRedacted !== false
                      ? label("shopFinanceUnavailable")
                      : tenantCurrency
                        ? formatLocaleMoney(String(shop.initialDebt), tenantCurrency, language)
                        : label("currencyUnavailable")}
                  </span>
                </td>
                {isEditMode && (
                  <td className="p-3">
                    {/* +++ إزالة opacity-0 لتظهر الأيقونات دائماً في وضع التعديل +++ */}
                    <div className="flex justify-end gap-2 px-4">
                      {/* تولتيب صاروخي لزر التعديل */}
                      <div className="relative group/btn flex items-center">
                        <button
                          type="button"
                          onClick={() => onEditShop(shop)}
                          aria-label={label("shopEdit", { shop: shop.name })}
                          className="p-2 text-slate-400 hover:text-[#1e87bb] hover:bg-emerald-50 rounded-lg transition-all shadow-sm border border-transparent hover:border-emerald-100"
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-max bg-slate-800 text-white text-[10px] font-bold px-2.5 py-1.5 rounded-lg hidden group-hover/btn:block z-50 shadow-xl">
                          {label("shopEdit", { shop: shop.name })}
                        </div>
                      </div>

                      {/* تولتيب صاروخي لزر الأرشفة */}
                      <div className="relative group/btn flex items-center">
                        <button
                          type="button"
                          onClick={() => onArchiveShop(shop.id)}
                          disabled={isEditMode && shop.zoneId !== selectedZoneIdForZones}
                          aria-label={label("shopArchive", { shop: shop.name })}
                          title={isEditMode && shop.zoneId !== selectedZoneIdForZones ? shopOrderText(language, "outsideZone") : undefined}
                          className="p-2 text-slate-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all shadow-sm border border-transparent hover:border-red-100 disabled:opacity-30 disabled:cursor-not-allowed"
                        >
                          <Archive className="w-4 h-4" />
                        </button>
                        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-max bg-slate-800 text-white text-[10px] font-bold px-2.5 py-1.5 rounded-lg hidden group-hover/btn:block z-50 shadow-xl">
                          {label("shopArchive", { shop: shop.name })}
                        </div>
                      </div>
                    </div>
                  </td>
                )}
              </tr>;
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
