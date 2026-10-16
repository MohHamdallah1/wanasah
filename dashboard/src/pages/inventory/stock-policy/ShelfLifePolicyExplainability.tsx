import { AlertTriangle, Info, RefreshCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import {
  parseBatchIndexCursorPage,
  type WarehouseBatchIndexItem,
} from "../batches/batchIndexContracts";
import { batchIndexText } from "../batches/batchIndexI18n";
import { parseEffectiveShelfLifePolicy, type EffectiveShelfLifePolicy } from "./contracts";
import { useShelfLifePolicyCopy } from "./i18n";

interface Props {
  locationId: number;
  productVariantId: number | null;
}

export function ShelfLifePolicyExplainability({
  locationId,
  productVariantId,
}: Props) {
  const authFetch = useAuthFetch();
  const { t, copy: text, dir, locale } = useShelfLifePolicyCopy();
  const language = dir === "rtl" ? "ar" : "en";
  const number = useMemo(
    () => new Intl.NumberFormat(locale, { numberingSystem: "latn", maximumFractionDigits: 0 }),
    [locale],
  );

  const [policy, setPolicy] = useState<EffectiveShelfLifePolicy | null>(null);
  const [batches, setBatches] = useState<WarehouseBatchIndexItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(() => setReloadKey((value) => value + 1), []);

  useEffect(() => {
    setPolicy(null);
    setBatches([]);
    setFailed(false);
    if (productVariantId === null) return;

    const controller = new AbortController();
    setLoading(true);
    const policyParams = new URLSearchParams({
      location_id: String(locationId),
      product_variant_id: String(productVariantId),
    });
    const batchParams = new URLSearchParams({
      location_id: String(locationId),
      product_variant_id: String(productVariantId),
      limit: "3",
      expiry_state: "ALL",
      sellability: "ALL",
      sort: "EXPIRY_ASC",
    });

    void Promise.all([
      authFetch(`/warehouse/inventory/stock-policy/effective?${policyParams.toString()}`, {
        signal: controller.signal,
      }),
      authFetch(`/warehouse/inventory/batches/cursor?${batchParams.toString()}`, {
        signal: controller.signal,
      }),
    ])
      .then(([policyRaw, batchRaw]) => {
        if (controller.signal.aborted) return;
        const parsedPolicy = parseEffectiveShelfLifePolicy(policyRaw);
        const parsedBatches = parseBatchIndexCursorPage(batchRaw);
        if (
          parsedPolicy.location_id !== locationId ||
          parsedPolicy.product_variant_id !== productVariantId ||
          parsedBatches.location_id !== locationId ||
          parsedBatches.items.some((item) => item.product_variant_id !== productVariantId)
        ) {
          throw new Error("STOCK_POLICY_SCOPE_MISMATCH");
        }
        setPolicy(parsedPolicy);
        setBatches(parsedBatches.items);
      })
      .catch((error: unknown) => {
        if (!(error instanceof Error && error.name === "AbortError")) {
          setPolicy(null);
          setBatches([]);
          setFailed(true);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [authFetch, locationId, productVariantId, reloadKey]);

  const batchText = (
    key: Parameters<typeof batchIndexText>[2],
    values: Record<string, unknown> = {},
  ) => batchIndexText(t, language, key, values);

  if (productVariantId === null) {
    return (
      <section dir={dir} className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-3 text-xs text-slate-600">
        <div className="flex items-start gap-2">
          <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div>
            <strong className="block text-slate-800">{text.title}</strong>
            <span>{text.chooseOne}</span>
          </div>
        </div>
      </section>
    );
  }

  if (failed) {
    return (
      <section dir={dir} role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-800">
        <div className="flex items-center justify-between gap-3">
          <span className="inline-flex items-center gap-2 font-bold">
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            {text.loadError}
          </span>
          <button type="button" onClick={load} className="rounded-lg border border-red-200 bg-white px-3 py-1.5 font-bold outline-none focus-visible:ring-2 focus-visible:ring-red-300">
            {text.retry}
          </button>
        </div>
      </section>
    );
  }

  return (
    <section dir={dir} aria-live="polite" className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
      <div className="flex items-start justify-between gap-3">
        <div>
          <strong className="block text-sm text-slate-900">{text.title}</strong>
          <span className="mt-0.5 block text-[11px] text-slate-500">{text.readOnly}</span>
        </div>
        {loading ? <RefreshCcw className="h-4 w-4 shrink-0 animate-spin text-slate-400" aria-label={String(t("common.loading"))} /> : null}
      </div>

      {policy ? (
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="rounded-lg border border-slate-200 bg-white p-2.5">
            <span className="block text-[10px] font-semibold text-slate-500">{text.requirement}</span>
            <strong className="mt-1 block text-sm text-slate-900 tabular-nums">
              {policy.requirement_applies
                ? text.days.replace("{{count}}", number.format(policy.minimum_remaining_shelf_life_days))
                : text.noRequirement}
            </strong>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-2.5 text-[11px] leading-5 text-slate-600">
            {text.warningSeparate}
          </div>
        </div>
      ) : null}

      {policy && !loading ? (
        <div>
          <strong className="text-[11px] text-slate-800">{text.sampleTitle}</strong>
          {batches.length === 0 ? (
            <p className="mt-1 text-[11px] text-slate-500">{text.noBatches}</p>
          ) : (
            <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {batches.map((batch) => (
                <article key={batch.batch_id} className="rounded-lg border border-slate-200 bg-white p-2.5">
                  <div className="flex items-start justify-between gap-2">
                    <strong className="min-w-0 truncate text-[11px] text-slate-900">{batch.batch_number ?? batchText("noLotSupplied")}</strong>
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[9px] font-black ${batch.sellability_state === "SELLABLE" ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"}`}>
                      {batchText(`sellability_${batch.sellability_state}`)}
                    </span>
                  </div>
                  <div className="mt-2 flex items-baseline justify-between gap-2">
                    <span className="text-[10px] text-slate-500">{text.remaining}</span>
                    <strong className="tabular-nums text-slate-800">
                      {batch.days_to_expiry === null
                        ? text.noExpiry
                        : text.days.replace("{{count}}", number.format(batch.days_to_expiry))}
                    </strong>
                  </div>
                  {batch.sellability_reason_codes.map((code) => (
                    <div key={code} className="mt-2 rounded-md bg-slate-50 px-2 py-1.5 text-[10px] leading-4 text-slate-600">
                      <span className="block font-semibold">{batchText(`reason_${code}`)}</span>
                      <span className="block font-mono text-[9px] text-slate-400">{text.reasonCode}: {code}</span>
                    </div>
                  ))}
                </article>
              ))}
            </div>
          )}
        </div>
      ) : null}

      <p className="border-t border-slate-200 pt-2 text-[10px] leading-4 text-slate-500">{text.costRule}</p>
    </section>
  );
}
