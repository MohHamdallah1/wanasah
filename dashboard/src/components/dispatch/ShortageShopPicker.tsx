import { useMemo, useState } from "react";
import { MapPin, Search, Store } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Shop, Zone } from "@/types/dispatch";
import { dispatchUiText } from "@/features/dispatch/dispatchUiText";

const normalize = (value: string) => value.normalize("NFKC")
  .replace(/[\u064B-\u065F\u0670]/g, "").replace(/[أإآ]/g, "ا")
  .replace(/ى/g, "ي").toLocaleLowerCase().trim();
const MAX_OPTIONS = 120;

/** Bounded native selects: OS option menus cannot be clipped by the dialog. */
export function ShortageShopPicker({ shops, zones, shopId, zoneId, disabled, onChoose }: {
  shops: readonly Shop[];
  zones: readonly Zone[];
  shopId: string;
  zoneId: string;
  disabled: boolean;
  onChoose: (zoneId: string, shopId: string) => void;
}) {
  const { i18n } = useTranslation();
  const t = (key: Parameters<typeof dispatchUiText>[1], args?: Record<string, string | number>) =>
    dispatchUiText(i18n.language, key, args ?? {});
  const [search, setSearch] = useState("");
  const zoneNames = useMemo(() => new Map(zones.map(zone => [zone.id, zone.name])), [zones]);
  const authorized = useMemo(() => shops
    .filter(shop => !shop.archived && !!shop.zoneId && zoneNames.has(shop.zoneId))
    .map(shop => ({ shop, keywords: normalize(
      [shop.name, shop.owner, shop.phone, zoneNames.get(shop.zoneId) ?? ""].join(" "),
    ) })), [shops, zoneNames]);
  const inZone = useMemo(() => authorized.filter(row => !zoneId || row.shop.zoneId === zoneId),
    [authorized, zoneId]);
  const term = normalize(search);
  const filtered = useMemo(() => {
    if (!term) return inZone;
    return inZone.filter(row => row.keywords.includes(term));
  }, [inZone, term]);
  const shown = filtered.slice(0, MAX_OPTIONS).map(row => row.shop);
  const selected = authorized.find(row => row.shop.id === shopId && row.shop.zoneId === zoneId)?.shop;
  if (selected && !shown.some(shop => shop.id === selected.id)) shown.unshift(selected);

  return <div data-testid="shortage-zone-shop-workbench"
    className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 lg:col-span-2 lg:grid-cols-2">
    <div className="min-w-0 space-y-1.5">
      <label htmlFor="shortage-zone-select" className="flex items-center gap-1.5 text-xs font-bold text-slate-700">
        <MapPin aria-hidden="true" className="h-4 w-4 text-sky-700"/>{t("shortageStudioZone")}
      </label>
      <select id="shortage-zone-select" value={zoneId} disabled={disabled}
        onChange={event => { const id=event.target.value; onChoose(id, selected?.zoneId===id ? selected.id : ""); setSearch(""); }}
        className="h-12 w-full min-w-0 rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-100 disabled:bg-slate-100">
        <option value="">{t("shortageStudioAllZones")}</option>
        {zones.map(zone => <option key={zone.id} value={zone.id}>{zone.name}</option>)}
      </select>
    </div>
    <div className="min-w-0 space-y-1.5">
      <label htmlFor="shortage-shop-select" className="flex items-center justify-between gap-2 text-xs font-bold text-slate-700">
        <span className="flex min-w-0 items-center gap-1.5"><Store aria-hidden="true" className="h-4 w-4 text-sky-700"/>
          {t("shortageStudioShop")}</span>
        <span className="shrink-0 text-[11px] font-normal text-slate-500">
          {t("shortageStudioShopCount",{count:inZone.length})}
        </span>
      </label>
      {inZone.length > MAX_OPTIONS && !disabled && <div className="relative">
        <Search aria-hidden="true" className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"/>
        <input type="search" value={search} maxLength={100}
          onChange={event => setSearch(event.target.value)}
          aria-label={t("shortageStudioFindShop")} placeholder={t("shortageStudioFindShop")}
          className="mb-1 h-9 w-full rounded-lg border border-slate-200 bg-white ps-10 pe-3 text-xs outline-none focus:ring-2 focus:ring-sky-100"/>
      </div>}
      <select id="shortage-shop-select" value={selected?.id ?? ""} disabled={disabled}
        onChange={event => {
          const shop=shown.find(candidate=>candidate.id===event.target.value);
          if (shop) {onChoose(shop.zoneId,shop.id); setSearch("");}
          else onChoose(zoneId,"");
        }}
        className="h-12 w-full min-w-0 rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-100 disabled:bg-slate-100">
        <option value="">{t("shortageStudioFindShop")}</option>
        {shown.map(shop => <option key={shop.id} value={shop.id}>
          {shop.name}{!zoneId ? " — "+zoneNames.get(shop.zoneId) : ""}
        </option>)}
      </select>
      {filtered.length>MAX_OPTIONS && <p className="text-[11px] text-slate-500">{t("shortageStudioRefineShop")}</p>}
    </div>
  </div>;
}
