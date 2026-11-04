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
import { batchUiNote } from "./batchUiNotes";
import { BatchSearchSelect } from "./BatchSearchSelect";

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
  active: boolean;
  scope: string;
  filters: BatchIndexFilters;
  onFiltersChange: (next: BatchIndexFilters) => void;
  expiryWarningDays: number;
  onExpiryWarningDaysChange: (value: number) => void;
  families: BatchFilterFamilyOption[];
  products: BatchFilterProductOption[];
  familySearch: string;
  productSearch: string;
  onFamilySearchChange: (value: string) => void;
  onProductSearchChange: (value: string) => void;
  onOpenSelector: (kind: "family" | "product") => void;
  onCloseSelector: (kind: "family" | "product") => void;
  onMoreSelector: (kind: "family" | "product") => void;
  onRetrySelector: (kind: "family" | "product") => void;
  familyDiscovery: { cursor: string | null; loading: boolean; loadingMore: boolean; error: boolean };
  productDiscovery: { cursor: string | null; loading: boolean; loadingMore: boolean; error: boolean };
}

const controlClass =
  "h-9 min-w-0 rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-semibold text-slate-700 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200";

export function BatchIndexFilters({
  t,
  language,
  active,
  scope,
  filters,
  onFiltersChange,
  expiryWarningDays,
  onExpiryWarningDaysChange,
  families,
  products,
  familySearch,
  productSearch,
  onFamilySearchChange,
  onProductSearchChange,
  onOpenSelector,
  onCloseSelector,
  onMoreSelector,
  onRetrySelector,
  familyDiscovery,
  productDiscovery,
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
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-8">
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

        <BatchSearchSelect
          label={text("family")}
          active={active}
          scope={scope}
          allLabel={text("allFamilies")}
          language={language}
          value={filters.familyId}
          options={families}
          search={familySearch}
          onSearchChange={onFamilySearchChange}
          onSelect={id => patch({ familyId: id })}
          onOpen={() => onOpenSelector("family")}
          onClose={() => onCloseSelector("family")}
          discovery={familyDiscovery}
          onMore={() => onMoreSelector("family")}
          onRetry={() => onRetrySelector("family")}
          searchLabel={batchUiNote(language, "familySearch")}
        />
        <BatchSearchSelect
          label={text("product")}
          active={active}
          scope={scope}
          allLabel={text("allProducts")}
          language={language}
          value={filters.productVariantId}
          options={products}
          search={productSearch}
          onSearchChange={onProductSearchChange}
          onSelect={id => patch({ productVariantId: id })}
          onOpen={() => onOpenSelector("product")}
          onClose={() => onCloseSelector("product")}
          discovery={productDiscovery}
          onMore={() => onMoreSelector("product")}
          onRetry={() => onRetrySelector("product")}
          searchLabel={batchUiNote(language, "productSearch")}
        />

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

        <label
          className="flex h-9 min-w-0 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 text-[11px] font-semibold text-slate-700"
          title={text("warningDaysHint")}
        >
          <span className="min-w-0 flex-1 truncate">{text("warningDaysShort")}</span>
          <input
            type="number"
            min={1}
            max={MAX_BATCH_EXPIRY_WARNING_DAYS}
            value={expiryWarningDays}
            onChange={event => {
              const value = Number(event.target.value);
              if (Number.isFinite(value) && value >= 1) {
                onExpiryWarningDaysChange(normalizeBatchExpiryWarningDays(value));
              }
            }}
            aria-label={text("warningDays")}
            className="h-7 w-12 min-w-0 rounded border border-slate-200 bg-white px-1 text-center text-[11px] font-semibold tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-slate-300"
          />
          <span className="shrink-0">{text("daysUnit")}</span>
        </label>
      </div>
    </section>
  );
}
