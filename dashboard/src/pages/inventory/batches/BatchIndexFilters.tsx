import { Search } from "lucide-react";
import type { TFunction } from "i18next";

import {
  MAX_BATCH_EXPIRY_WARNING_DAYS,
  normalizeBatchExpiryWarningDays,
} from "./batchDisplayPreferences";
import {
  type BatchIndexAttention,
  type BatchIndexDispositionFilter,
  type BatchIndexExpiryState,
  type BatchIndexFilters,
  type BatchIndexSellability,
  type BatchIndexSort,
} from "./batchIndexContracts";
import { batchIndexText } from "./batchIndexI18n";

export interface BatchFilterFamilyOption {
  id: number;
  name: string;
}

export interface BatchFilterProductOption {
  id: number;
  name: string;
  sku: string | null;
}

interface Props {
  t: TFunction;
  language: string;
  filters: BatchIndexFilters;
  searchInput: string;
  onSearchInputChange: (value: string) => void;
  onFiltersChange: (next: BatchIndexFilters) => void;
  expiryWarningDays: number;
  onExpiryWarningDaysChange: (value: number) => void;
  families: BatchFilterFamilyOption[];
  products: BatchFilterProductOption[];
}

const controlClass =
  "h-9 min-w-0 rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-semibold text-slate-700 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200";

export function BatchIndexFilters({
  t,
  language,
  filters,
  searchInput,
  onSearchInputChange,
  onFiltersChange,
  expiryWarningDays,
  onExpiryWarningDaysChange,
  families,
  products,
}: Props) {
  const text = (key: Parameters<typeof batchIndexText>[2]) =>
    batchIndexText(t, language, key);
  const patch = (next: Partial<BatchIndexFilters>) =>
    onFiltersChange({ ...filters, ...next });

  return (
    <section
      aria-label={text("filters")}
      className="border-b border-slate-200 bg-white p-2.5"
    >
      <div className="relative mb-2">
        <Search
          aria-hidden="true"
          className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
        />
        <input
          type="search"
          value={searchInput}
          onChange={(event) => onSearchInputChange(event.target.value)}
          placeholder={text("searchPlaceholder")}
          aria-label={text("searchPlaceholder")}
          maxLength={200}
          className="h-9 w-full rounded-lg border border-slate-200 bg-white ps-9 pe-3 text-sm font-semibold text-slate-800 outline-none transition placeholder:font-medium placeholder:text-slate-400 focus:border-slate-400 focus:ring-2 focus:ring-slate-200"
        />
      </div>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
        <select
          aria-label={text("expiry")}
          value={filters.expiryState}
          onChange={(event) => patch({ expiryState: event.target.value as BatchIndexExpiryState })}
          className={controlClass}
        >
          {(["ALL", "EXPIRED", "EXPIRES_TODAY", "EXPIRING_SOON", "NO_EXPIRY"] as const).map((value) => (
            <option key={value} value={value}>{text(`expiry_${value}`)}</option>
          ))}
        </select>

        <select
          aria-label={text("sellability")}
          value={filters.sellability}
          onChange={(event) => patch({ sellability: event.target.value as BatchIndexSellability })}
          className={controlClass}
        >
          {(["ALL", "SELLABLE", "NOT_SELLABLE"] as const).map((value) => (
            <option key={value} value={value}>{text(`sellability_${value}`)}</option>
          ))}
        </select>

        <select
          aria-label={text("disposition")}
          value={filters.disposition}
          onChange={(event) => patch({ disposition: event.target.value as BatchIndexDispositionFilter })}
          className={controlClass}
        >
          {(["ALL", "RELEASED", "QUARANTINED", "BLOCKED", "RECALLED"] as const).map((value) => (
            <option key={value} value={value}>{text(`disposition_${value}`)}</option>
          ))}
        </select>

        <select
          aria-label={text("attention")}
          value={filters.attention}
          onChange={(event) => patch({ attention: event.target.value as BatchIndexAttention })}
          className={controlClass}
        >
          {(["ALL", "UNAVAILABLE", "DAMAGED", "DISPOSAL_PENDING"] as const).map((value) => (
            <option key={value} value={value}>{text(`attention_${value}`)}</option>
          ))}
        </select>

        <select
          aria-label={text("family")}
          value={filters.familyId ?? ""}
          onChange={(event) => patch({ familyId: event.target.value ? Number(event.target.value) : null })}
          className={controlClass}
        >
          <option value="">{text("allFamilies")}</option>
          {families.map((family) => (
            <option key={family.id} value={family.id}>{family.name}</option>
          ))}
        </select>

        <select
          aria-label={text("product")}
          value={filters.productVariantId ?? ""}
          onChange={(event) => patch({ productVariantId: event.target.value ? Number(event.target.value) : null })}
          className={controlClass}
        >
          <option value="">{text("allProducts")}</option>
          {products.map((product) => (
            <option key={product.id} value={product.id}>
              {product.name}{product.sku ? ` · ${product.sku}` : ""}
            </option>
          ))}
        </select>

        <select
          aria-label={text("sort")}
          value={filters.sort}
          onChange={(event) => patch({ sort: event.target.value as BatchIndexSort })}
          className={controlClass}
        >
          {(["EXPIRY_ASC", "EXPIRY_DESC", "PRODUCT_ASC", "PRODUCT_DESC", "BATCH_IDENTITY_ASC", "UNAVAILABLE_DESC"] as const).map((value) => (
            <option key={value} value={value}>{text(`sort_${value}`)}</option>
          ))}
        </select>

        <label className="min-w-0">
          <span className="sr-only">{text("warningDays")}</span>
          <input
            type="number"
            min={1}
            max={MAX_BATCH_EXPIRY_WARNING_DAYS}
            value={expiryWarningDays}
            onChange={(event) => {
              const value = Number(event.target.value);
              if (Number.isFinite(value) && value >= 1) {
                onExpiryWarningDaysChange(normalizeBatchExpiryWarningDays(value));
              }
            }}
            aria-label={text("warningDays")}
            title={text("warningDaysHint")}
            className={`${controlClass} w-full`}
          />
        </label>
      </div>
      <p className="mt-1.5 text-[10px] font-medium text-slate-500">
        {text("warningDaysHint")}
      </p>
    </section>
  );
}