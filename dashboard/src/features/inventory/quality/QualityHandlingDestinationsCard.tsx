import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  MapPin,
  RefreshCcw,
  Save,
  ShieldCheck,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { warehousePresentationCopy } from "@/pages/inventory/warehouse-locations/presentationI18n";
import { useTransferDestinationPolicy } from "./useTransferDestinationPolicy";

const focusRing =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30";

export function QualityHandlingDestinationsCard({
  compact = false,
  onSaved,
}: {
  compact?: boolean;
  onSaved?: () => void | Promise<void>;
} = {}) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage ?? i18n.language;
  const presentation = warehousePresentationCopy(language);
  const controller = useTransferDestinationPolicy(onSaved);
  const {
    canManage,
    policy,
    inPlaceActive,
    loading,
    saving,
    pending,
    loadError,
    saveDraft,
    publish,
    canPublish,
  } = controller;
  if (!canManage) return null;

  const row = (labelKey: string) => (
    <div className="flex min-w-0 items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2.5">
      <span className="min-w-0 text-xs font-black text-slate-800">
        {t(labelKey)}
      </span>
      <span className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-slate-100 px-2.5 py-1 text-[10px] font-black text-slate-700">
        <MapPin aria-hidden="true" className="h-3.5 w-3.5" />
        {t("transferDestinationSetup.sameLocation")}
      </span>
    </div>
  );

  return (
    <section
      dir={i18n.dir()}
      className="rounded-2xl border border-blue-100 bg-blue-50/35 p-3 sm:p-4"
      aria-labelledby="quality-destinations-title"
      data-warehouse-setup="quality-policy"
      data-quality-destination-mode="in-place"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.14em] text-blue-700">
            <ShieldCheck aria-hidden="true" className="h-4 w-4" />
            {presentation.qualityPolicy}
          </div>
          <h3
            id="quality-destinations-title"
            className="text-sm font-black text-slate-900"
          >
            {t("transferDestinationSetup.setup")}
          </h3>
          <div className="mt-1 max-w-3xl space-y-0.5 text-[10px] font-semibold leading-5 text-slate-500">
            <p>{t("transferDestinationSetup.hint")}</p>
            {!compact ? <p>{t("transferDestinationSetup.sameLocationHint")}</p> : null}
          </div>
        </div>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[9px] font-black ${
            inPlaceActive
              ? "bg-emerald-50 text-emerald-700"
              : "bg-white text-slate-600"
          }`}
        >
          {inPlaceActive ? (
            <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5" />
          ) : (
            <CircleDashed aria-hidden="true" className="h-3.5 w-3.5" />
          )}
          {t(
            inPlaceActive
              ? "transferDestinationSetup.active"
              : "transferDestinationSetup.needsApply",
          )}
        </span>
      </div>

      {loadError ? (
        <div
          role="alert"
          className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold text-red-700"
        >
          <span className="flex min-w-0 items-center gap-2 break-words">
            <AlertTriangle aria-hidden="true" className="h-4 w-4 shrink-0" />
            {loadError}
          </span>
          <button
            type="button"
            onClick={() => void controller.loadPolicy()}
            className={`inline-flex items-center gap-1 rounded-lg border border-red-200 bg-white px-2 py-1 font-bold ${focusRing}`}
          >
            <RefreshCcw aria-hidden="true" className="h-3.5 w-3.5" />
            {t("transferDestinationSetup.retry")}
          </button>
        </div>
      ) : null}

      <div className="mt-3 grid gap-2">
        {row("transferDestinationSetup.quarantine")}
        {row("transferDestinationSetup.vendorReturn")}
        {row("transferDestinationSetup.disposal")}
      </div>

      {!inPlaceActive || policy.draft ? (
        <div className="mt-3 flex flex-wrap justify-end gap-2">
          <button
            type="button"
            disabled={loading || saving || Boolean(pending) || Boolean(loadError)}
            onClick={() => void saveDraft()}
            className={`inline-flex min-h-9 items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-xs font-black text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 ${focusRing}`}
          >
            <Save aria-hidden="true" className="h-4 w-4" />
            {saving ? t("common.loading") : t("transferDestinationSetup.save")}
          </button>
          <button
            type="button"
            disabled={!canPublish || loading || saving || Boolean(pending)}
            onClick={() => void publish()}
            className={`min-h-9 rounded-xl bg-blue-600 px-4 text-xs font-black text-white disabled:cursor-not-allowed disabled:opacity-40 ${focusRing}`}
          >
            {t("transferDestinationSetup.apply")}
          </button>
        </div>
      ) : null}

      {pending ? (
        <div
          role="alert"
          className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-900"
        >
          <span className="flex min-w-0 items-center gap-2 break-words">
            <AlertTriangle aria-hidden="true" className="h-4 w-4 shrink-0" />
            {t("transferDestinationSetup.pending")}
          </span>
          <button
            type="button"
            disabled={saving}
            onClick={() => void controller.retry()}
            className={`inline-flex items-center gap-1 rounded-lg border border-amber-200 bg-white px-2 py-1 font-bold disabled:opacity-40 ${focusRing}`}
          >
            <RefreshCcw aria-hidden="true" className="h-3.5 w-3.5" />
            {t("transferDestinationSetup.retry")}
          </button>
        </div>
      ) : null}
    </section>
  );
}
