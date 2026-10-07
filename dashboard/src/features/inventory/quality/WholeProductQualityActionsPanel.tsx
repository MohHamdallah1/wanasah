import { AlertTriangle, ArrowRight, PackageCheck, Pencil, Trash2, Truck, Warehouse } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { parseConversions } from "@/features/catalog/contracts";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import { resolveI18nLocale } from "@/lib/locale";
import { formatMoneyDisplay } from "@/lib/money";
import {
  compareQuantity,
  formatCommercialQuantity,
  type Quantity,
} from "@/lib/quantity";
import { aggregateProductQualityLocations } from "./productQualityLocationModel";
import {
  useProductQualityCommands,
  type WholeProductQualityAction,
} from "./useProductQualityCommands";
import { useProductQualitySources } from "./useProductQualitySources";
import { useWholeProductQualityPreview } from "./useWholeProductQualityPreview";
import type { WholeProductQualityPreview } from "./wholeProductQualityPreviewContract";

const scaled = (value: string): bigint => {
  const [whole, fraction = ""] = value.split(".");
  return BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0"));
};
const canonical = (value: bigint): Quantity => {
  const whole = value / 1_000_000n;
  const fraction = (value % 1_000_000n).toString().padStart(6, "0").replace(/0+$/, "");
  return (fraction ? `${whole}.${fraction}` : whole.toString()) as Quantity;
};
const exactRatio = (numerator: Quantity, denominator: Quantity): Quantity | null => {
  const top = scaled(numerator) * 1_000_000n;
  const bottom = scaled(denominator);
  if (bottom <= 0n || top % bottom !== 0n) return null;
  return canonical(top / bottom);
};
const previewSignature = (preview: WholeProductQualityPreview): string => JSON.stringify(preview);

export function WholeProductQualityActionsPanel({
  productVariantId,
  baseUomId,
  baseUomName,
  onBack,
}: {
  productVariantId: number;
  baseUomId: number;
  baseUomName: string;
  onBack: () => void;
}) {
  const { t, i18n } = useTranslation();
  const locale = resolveI18nLocale(i18n);
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const query = useProductQualitySources(productVariantId);
  const [activeAction, setActiveAction] = useState<WholeProductQualityAction | null>(null);
  const [reason, setReason] = useState("");
  const [reasonEditing, setReasonEditing] = useState(false);
  const [reasonTouched, setReasonTouched] = useState(false);
  const [recipientName, setRecipientName] = useState("");
  const [previewChanged, setPreviewChanged] = useState(false);

  const pages = query.data?.pages ?? [];
  const allLoaded = !query.hasNextPage && !query.isFetchingNextPage;
  const locations = useMemo(
    () => (allLoaded ? aggregateProductQualityLocations(pages) : []),
    [allLoaded, pages],
  );
  const commands = useProductQualityCommands({
    productVariantId,
    onSucceeded: async () => { await query.refetch(); },
  });
  const preview = useWholeProductQualityPreview(productVariantId, activeAction !== null);
  const conversions = useQuery({
    queryKey: ["product-quality-display-uom", access.data?.company_id ?? null, access.data?.driver_id ?? null, productVariantId],
    enabled: access.data !== undefined,
    queryFn: async ({ signal }) => parseConversions(await authFetch(`/catalog/variants/${productVariantId}/conversions`, { signal })),
    staleTime: 60_000,
    retry: false,
  });

  useEffect(() => {
    if (!activeAction || !preview.data || reasonTouched) return;
    const savedReason = preview.data.issueReason ?? "";
    setReason(savedReason);
    setReasonEditing(savedReason.length === 0);
  }, [activeAction, preview.data, reasonTouched]);

  const display = useMemo(() => {
    const candidates = (conversions.data ?? []).filter((item) =>
      item.to_uom.id === baseUomId && compareQuantity(item.numerator, item.denominator) > 0,
    );
    if (candidates.length !== 1) return { name: baseUomName, factor: "1" as Quantity };
    const factor = exactRatio(candidates[0].numerator, candidates[0].denominator);
    return factor ? { name: candidates[0].from_uom.name, factor } : { name: baseUomName, factor: "1" as Quantity };
  }, [baseUomId, baseUomName, conversions.data]);

  const format = (value: Quantity) => formatCommercialQuantity(value, display.name, baseUomName, display.factor);
  const totalQuantity = useMemo(
    () => canonical(locations.reduce((sum, location) => sum + scaled(location.onHandQuantity), 0n)),
    [locations],
  );
  const totalDisplay = format(totalQuantity);
  const currentBatchValuation = useMemo(() => {
    if (preview.data?.costingMethod !== "MOVING_AVERAGE") return new Map();
    return new Map(preview.data.valuationLines.map((line) => [line.batchId, line]));
  }, [preview.data]);

  const openAction = (action: WholeProductQualityAction) => {
    setActiveAction(action);
    setReason("");
    setReasonEditing(false);
    setReasonTouched(false);
    setRecipientName("");
    setPreviewChanged(false);
  };

  const submit = async () => {
    if (!activeAction || !reason.trim() || !preview.data || preview.data.blockerCodes.length > 0) return;
    if (activeAction === "RETURN_TO_VENDOR" && !recipientName.trim()) return;

    const shownSignature = previewSignature(preview.data);
    const refreshed = await preview.refetch();
    if (!refreshed.data || refreshed.isError) return;
    if (previewSignature(refreshed.data) !== shownSignature) {
      setPreviewChanged(true);
      return;
    }

    const ok = await commands.resolveAll({
      action: activeAction,
      reason,
      recipientName,
    });
    if (ok) setActiveAction(null);
  };

  const previewBlocked = (preview.data?.blockerCodes.length ?? 0) > 0;
  const submitDisabled = commands.busyKey !== null
    || preview.isFetching
    || !preview.data
    || preview.isError
    || previewBlocked
    || !reason.trim()
    || (activeAction === "RETURN_TO_VENDOR" && !recipientName.trim());

  return <div className="space-y-3" dir={i18n.dir()}>
    <div className="flex items-center justify-between gap-2">
      <button type="button" onClick={onBack} className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-black text-slate-700">
        <ArrowRight className="h-4 w-4" />{t("common.back")}
      </button>
      <h3 className="text-sm font-black text-slate-950">{t("productQualityInline.title")}</h3>
    </div>

    {query.isLoading || !allLoaded ? <p role="status" className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs font-bold text-slate-500">{t("common.loading")}</p> : null}
    {query.isError ? <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs font-bold text-rose-800">{apiErrorMessage(query.error, t("productQualityInline.errors.load"))}</div> : null}
    {!query.isLoading && allLoaded && !query.isError && locations.length === 0 ? <p className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs font-bold text-slate-500">{t("productQualityInline.noStock")}</p> : null}

    {allLoaded && !query.isError && locations.length > 0 ? <>
      <div className="rounded-xl border border-slate-200 bg-white p-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-black text-slate-950">{t("productQualityInline.affectedStock")}</p>
            <p className="mt-1 text-[10px] font-semibold text-slate-500">{t("productQualityInline.total", { quantity: totalDisplay.primary, secondary: totalDisplay.secondary ? ` (${totalDisplay.secondary})` : "" })}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => openAction("DISPOSE")} disabled={commands.busyKey !== null} className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-rose-200 bg-white px-3 text-[10px] font-black text-rose-800 transition hover:bg-rose-50 disabled:opacity-40"><Trash2 className="h-3.5 w-3.5" />{t("productQualityInline.actions.disposeAll")}</button>
            <button type="button" onClick={() => openAction("RETURN_TO_VENDOR")} disabled={commands.busyKey !== null} className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-sky-200 bg-white px-3 text-[10px] font-black text-sky-900 transition hover:bg-sky-50 disabled:opacity-40"><Truck className="h-3.5 w-3.5" />{t("productQualityInline.actions.returnAll")}</button>
          </div>
        </div>
        <div className="mt-3 space-y-1.5">
          {locations.map((location) => {
            const quantity = format(location.onHandQuantity);
            return <div key={location.locationId} className="flex items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2">
              <div className="flex min-w-0 items-center gap-2">
                {location.locationType === "VEHICLE" ? <Truck className="h-4 w-4 shrink-0 text-slate-400" /> : <Warehouse className="h-4 w-4 shrink-0 text-slate-400" />}
                <span className="truncate text-[11px] font-black text-slate-800">{location.locationName}</span>
              </div>
              <span className="shrink-0 text-[10px] font-bold text-slate-600">{quantity.primary}{quantity.secondary ? ` (${quantity.secondary})` : ""}</span>
            </div>;
          })}
        </div>
      </div>

      {activeAction ? <form onSubmit={(event) => { event.preventDefault(); void submit(); }} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
        <div className="flex items-center gap-2">
          <PackageCheck className="h-4 w-4 text-slate-500" />
          <p className="text-xs font-black text-slate-950">{t(activeAction === "DISPOSE" ? "productQualityInline.confirm.disposeTitle" : "productQualityInline.confirm.returnTitle")}</p>
        </div>
        <p className="mt-1 text-[10px] font-semibold text-slate-500">{t("productQualityInline.confirm.scope", { quantity: totalDisplay.primary, secondary: totalDisplay.secondary ? ` (${totalDisplay.secondary})` : "" })}</p>

        {preview.isLoading ? <p role="status" className="mt-3 rounded-lg border border-slate-200 bg-white p-3 text-[10px] font-bold text-slate-500">{t("productQualityInline.preview.loading")}</p> : null}
        {preview.isError ? <div role="alert" className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-[10px] font-bold text-rose-800">{apiErrorMessage(preview.error, t("productQualityInline.errors.preview"))}</div> : null}
        {previewChanged ? <div role="alert" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-[10px] font-bold text-amber-900">{t("productQualityInline.preview.changed")}</div> : null}

        {preview.data ? <div className="mt-3 space-y-3">
          <section className="grid gap-1.5 sm:grid-cols-2">
            {preview.data.locations.map((location) => {
              const quantity = format(location.quantity);
              return <div key={location.locationId} className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-2">
                <div className="flex min-w-0 items-center gap-1.5">
                  {location.locationType === "VEHICLE" ? <Truck className="h-3.5 w-3.5 shrink-0 text-slate-400" /> : <Warehouse className="h-3.5 w-3.5 shrink-0 text-slate-400" />}
                  <span className="truncate text-[10px] font-black text-slate-800">{location.locationName}</span>
                </div>
                <span className="shrink-0 text-[10px] font-bold tabular-nums text-slate-600">{quantity.primary}{quantity.secondary ? ` (${quantity.secondary})` : ""}</span>
              </div>;
            })}
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-3">
            <p className="text-[10px] font-black text-slate-800">{t("productQualityInline.preview.batchesTitle")}</p>
            <div className="mt-2 max-h-52 overflow-y-auto rounded-md border border-slate-100">
              {preview.data.batches.map((batch) => {
                const quantity = format(batch.quantity);
                const valuation = currentBatchValuation.get(batch.batchId);
                return <div key={batch.batchId} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 border-b border-slate-100 px-2.5 py-2 last:border-b-0 sm:grid-cols-4">
                  <span className="text-[10px] font-black text-slate-800">{batch.batchNumber}</span>
                  <span className="text-[10px] font-bold tabular-nums text-slate-600">{quantity.primary}{quantity.secondary ? ` (${quantity.secondary})` : ""}</span>
                  {valuation ? <>
                    <span className="text-[9px] tabular-nums text-slate-600">{t("productQualityInline.preview.unitCostInline", { value: formatMoneyDisplay(valuation.unitCost, preview.data.currencyCode, locale) })}</span>
                    <span className="text-[9px] font-bold tabular-nums text-slate-700">{t("productQualityInline.preview.valueInline", { value: formatMoneyDisplay(valuation.bookValue, preview.data.currencyCode, locale) })}</span>
                  </> : null}
                </div>;
              })}
            </div>
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="text-[10px] font-black text-slate-800">{t("productQualityInline.preview.valuationTitle")}</p>
                {preview.data.costingMethod ? <p className="mt-0.5 text-[9px] font-semibold text-slate-500">{t(`productQualityInline.preview.costing.${preview.data.costingMethod}`)}</p> : null}
              </div>
              {preview.data.valuationAvailable && preview.data.totalBookValue ? <div className="text-end">
                <p className="text-[9px] font-semibold text-slate-500">{t("productQualityInline.preview.totalBookValue")}</p>
                <strong className="text-sm font-black tabular-nums text-slate-950">{formatMoneyDisplay(preview.data.totalBookValue, preview.data.currencyCode, locale)}</strong>
              </div> : null}
            </div>
            {preview.data.valuationAvailable && preview.data.costingMethod === "FIFO" ? <p className="mt-2 rounded-md bg-sky-50 px-2.5 py-2 text-[9px] font-semibold text-sky-900">{t("productQualityInline.preview.fifoNote")}</p> : null}
            {!preview.data.valuationAvailable ? <div role="note" className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-[9px] font-semibold text-amber-900">{t("productQualityInline.preview.valuationUnavailable")}</div> : null}
          </section>

          {previewBlocked ? <div role="alert" className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-[10px] font-bold text-amber-900">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{t("productQualityInline.preview.blocked")}</span>
          </div> : null}

          <section className="rounded-lg border border-slate-200 bg-white p-3">
            {!reasonEditing ? <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[9px] font-black text-slate-500">{t("productQualityInline.fields.reason")}</p>
                <p className="mt-1 break-words text-[11px] font-bold text-slate-900">{reason || t("productQualityInline.fields.reasonMissing")}</p>
              </div>
              <button type="button" onClick={() => setReasonEditing(true)} className="inline-flex shrink-0 items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[9px] font-black text-slate-700">
                <Pencil className="h-3 w-3" />{t("productQualityInline.fields.editReason")}
              </button>
            </div> : <label className="text-[10px] font-black text-slate-700">{t("productQualityInline.fields.reason")}
              <input
                autoFocus
                value={reason}
                onChange={(event) => { setReason(event.target.value); setReasonTouched(true); }}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
              />
            </label>}
          </section>

          {activeAction === "RETURN_TO_VENDOR" ? <label className="block text-[10px] font-black text-slate-700">{t("productQualityInline.fields.recipientName")}
            <input autoFocus={!reasonEditing} value={recipientName} onChange={(event) => setRecipientName(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
          </label> : null}
        </div> : null}

        <div className="mt-3 flex justify-end gap-2">
          <button type="button" onClick={() => setActiveAction(null)} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[10px] font-black text-slate-700">{t("common.cancel")}</button>
          <button type="submit" disabled={submitDisabled} className={`rounded-lg px-4 py-2 text-[10px] font-black text-white disabled:opacity-40 ${activeAction === "DISPOSE" ? "bg-rose-700" : "bg-sky-700"}`}>
            {t(activeAction === "DISPOSE" ? "productQualityInline.confirm.disposeButton" : "productQualityInline.confirm.returnButton")}
          </button>
        </div>
      </form> : null}
    </> : null}
  </div>;
}
