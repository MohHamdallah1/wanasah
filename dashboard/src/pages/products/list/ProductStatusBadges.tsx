import { AlertOctagon } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { SimpleProduct } from "@/pages/products/contracts";
import { productTableStatus } from "@/pages/products/list/productTableStatus";

const tones = {
  available: "bg-emerald-50 text-emerald-800 ring-emerald-200 dark:bg-emerald-950 dark:text-emerald-200 dark:ring-emerald-800",
  retiring: "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950 dark:text-amber-200 dark:ring-amber-800",
  archived: "bg-slate-100 text-slate-700 ring-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-600",
  hold: "bg-orange-50 text-orange-900 ring-orange-200 dark:bg-orange-950 dark:text-orange-200 dark:ring-orange-800",
  recall: "bg-rose-100 text-rose-900 ring-rose-300 dark:bg-rose-950 dark:text-rose-200 dark:ring-rose-700",
};

export function ProductStatusBadges({ item }: {
  item: Pick<SimpleProduct, "lifecycle_status" | "operational_hold">;
}) {
  const { t, i18n } = useTranslation();
  const { primary, secondary } = productTableStatus(item);
  return (
    <div dir={i18n.dir()} className="flex flex-wrap items-center justify-center gap-1">
      <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-1 text-[10px] font-black ring-1 ring-inset ${tones[primary.tone]}`}>
        {primary.tone === "recall" ? <AlertOctagon aria-hidden="true" className="h-3 w-3" /> : null}
        {t(primary.labelKey)}
      </span>
      {secondary ? (
        <span className={`inline-flex whitespace-nowrap rounded-full px-1.5 py-0.5 text-[9px] font-semibold ring-1 ring-inset ${tones[secondary.tone]}`}>
          {t(secondary.labelKey)}
        </span>
      ) : null}
    </div>
  );
}
