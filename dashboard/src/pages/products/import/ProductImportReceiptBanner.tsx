import {
  AlertCircle,
  CheckCircle2,
  X,
} from "lucide-react";
import {
  useTranslation,
} from "react-i18next";

type Props = {
  imported: number;
  needsReview: number;
  hasFilters: boolean;
  onClearFilters: () => void;
  onDismiss: () => void;
};

export function ProductImportReceiptBanner({
  imported,
  needsReview,
  hasFilters,
  onClearFilters,
  onDismiss,
}: Props) {
  const { t } = useTranslation();

  return (
    <section
      role="status"
      className="rounded-xl border border-emerald-200 bg-emerald-50/70 px-3 py-3 text-start sm:px-4"
      aria-label={t(
        "products.importReceipt.label",
      )}
    >
      <div className="flex items-start gap-2.5">
        <CheckCircle2
          aria-hidden="true"
          className="mt-0.5 h-5 w-5 shrink-0 text-emerald-700"
        />
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-sm font-black text-emerald-950">
            {t(
              "products.importReceipt.saved",
              { count: imported },
            )}
          </p>
          {needsReview > 0 ? (
            <p className="flex items-start gap-1.5 text-xs font-semibold text-amber-900">
              <AlertCircle
                aria-hidden="true"
                className="mt-0.5 h-3.5 w-3.5 shrink-0"
              />
              {t(
                "products.importReceipt.needsReview",
                { count: needsReview },
              )}
            </p>
          ) : null}
          <p className="text-[11px] leading-5 text-emerald-900">
            {t(
              "products.importReceipt.listHint",
            )}
          </p>
          {hasFilters ? (
            <button
              type="button"
              onClick={onClearFilters}
              className="mt-1 rounded-md border border-emerald-300 bg-white px-2.5 py-1 text-xs font-bold text-emerald-900 hover:bg-emerald-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600"
            >
              {t(
                "products.importReceipt.clearFilters",
              )}
            </button>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label={t(
            "products.importReceipt.dismiss",
          )}
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-emerald-800 hover:bg-emerald-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600"
        >
          <X aria-hidden="true" className="h-4 w-4" />
        </button>
      </div>
    </section>
  );
}
