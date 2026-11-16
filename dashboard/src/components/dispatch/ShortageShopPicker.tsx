import { useMemo, useState } from "react";
import { Search, Store, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Shop, Zone } from "@/types/dispatch";
import { dispatchUiText } from "@/features/dispatch/dispatchUiText";

const normalize = (value: string): string => value.normalize("NFKC")
  .replace(/[\u064B-\u065F\u0670]/g, "").replace(/[أإآ]/g, "ا")
  .replace(/ى/g, "ي").toLocaleLowerCase().trim();

export function ShortageShopPicker({
  shops, zones, shopId, zoneId, disabled, onChoose,
}: {
  shops: readonly Shop[];
  zones: readonly Zone[];
  shopId: string;
  zoneId: string;
  disabled: boolean;
  onChoose: (zoneId: string, shopId: string) => void;
}) {
  const { i18n } = useTranslation();
  const t = (key: Parameters<typeof dispatchUiText>[1]) => dispatchUiText(i18n.language, key);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState(false);
  const zoneNames = useMemo(() => new Map(zones.map(zone => [zone.id, zone.name])), [zones]);
  const selected = shops.find(shop =>
    shop.id === shopId && shop.zoneId === zoneId && !shop.archived && zoneNames.has(shop.zoneId));
  // Company directory is read from the authorized Backend. Index only that
  // admitted snapshot once, not 50k normalized shop strings per keystroke.
  const indexed = useMemo(() => shops
    .filter(shop => !shop.archived && shop.zoneId && zoneNames.has(shop.zoneId))
    .map(shop => ({ shop, search: normalize(
      [shop.name, shop.owner, shop.phone, zoneNames.get(shop.zoneId) ?? ""].join(" "),
    ) })), [shops, zoneNames]);
  const key = normalize(query);
  const matches = useMemo(() => {
    if (key.length < 2) return [];
    const rows: Shop[] = [];
    for (const row of indexed) {
      if (row.search.includes(key)) rows.push(row.shop);
      if (rows.length >= 25) break;
    }
    return rows;
  }, [indexed, key]);

  const change = () => { setQuery(""); setEditing(true); };
  const choose = (shop: Shop) => {
    onChoose(shop.zoneId, shop.id);
    setQuery("");
    setEditing(false);
  };

  return <section className="min-w-0 space-y-2" aria-label={t("shortageQuickShopStep")}>
    <div className="flex items-center gap-2 text-sm font-bold text-slate-800">
      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#1e87bb] text-xs text-white">1</span>
      <span>{t("shortageQuickShopStep")}</span>
    </div>
    {selected && !editing ? <div className="flex min-w-0 items-center gap-3 rounded-xl border border-blue-200 bg-blue-50 p-3">
      <Store aria-hidden="true" className="h-5 w-5 shrink-0 text-[#1e87bb]"/>
      <span className="min-w-0 flex-1">
        <strong className="block truncate text-sm text-slate-900">{selected.name}</strong>
        <span className="block truncate text-xs text-slate-600">{zoneNames.get(selected.zoneId)}
          {selected.owner ? " · " + selected.owner : ""}
        </span>
      </span>
      {!disabled && <button type="button" onClick={change}
        className="min-h-10 rounded-lg border border-blue-200 bg-white px-3 text-xs font-bold text-blue-800 focus-visible:ring-2"
      >{t("shortageQuickChangeShop")}</button>}
    </div> : <div className="relative space-y-2">
      <div className="relative">
        <Search aria-hidden="true" className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500"/>
        <input type="search" aria-label={t("shortageQuickSearchShop")}
          placeholder={t("shortageQuickSearchShop")} value={query} maxLength={100}
          onChange={event => setQuery(event.target.value)} disabled={disabled}
          className="h-12 w-full rounded-xl border border-slate-300 bg-white ps-10 pe-10 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"/>
        {selected && !disabled && <button type="button" aria-label={t("shortageQuickCancelShopSearch")}
          onClick={() => { setQuery(""); setEditing(false); }}
          className="absolute end-2 top-1/2 -translate-y-1/2 rounded p-1 text-slate-500">
          <X aria-hidden="true" className="h-4 w-4"/>
        </button>}
      </div>
      {key.length < 2 ? <p className="text-xs text-slate-500">{t("shortageQuickShopHint")}</p>
        : matches.length ? <div className="max-h-52 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-sm">
          {matches.map(shop => <button type="button" key={shop.id} onClick={() => choose(shop)}
            className="flex min-h-12 w-full min-w-0 items-center gap-3 border-b border-slate-100 px-3 py-2 text-start last:border-b-0 hover:bg-blue-50 focus-visible:bg-blue-50">
            <Store aria-hidden="true" className="h-4 w-4 shrink-0 text-slate-500"/>
            <span className="min-w-0 flex-1">
              <strong className="block truncate text-sm">{shop.name}</strong>
              <span className="block truncate text-xs text-slate-500">{zoneNames.get(shop.zoneId)}
                {shop.owner ? " · " + shop.owner : ""}{shop.phone ? " · " + shop.phone : ""}
              </span>
            </span>
          </button>)}
        </div> : <p role="status" className="text-sm text-slate-600">{t("shortageQuickNoShops")}</p>}
    </div>}
  </section>;
}
