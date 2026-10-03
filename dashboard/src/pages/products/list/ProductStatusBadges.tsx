import { useTranslation } from "react-i18next";

import type { SimpleProduct } from "@/pages/products/contracts";
import { productTableStatus } from "@/pages/products/list/productTableStatus";

const dotTones = {
  good: "bg-emerald-500",
  warning: "bg-amber-500",
  muted: "bg-slate-400",
  blocked: "bg-rose-500",
};

const valueTones = {
  good: "text-slate-900",
  warning: "text-amber-900",
  muted: "text-slate-600",
  blocked: "text-rose-800",
};

export function ProductStatusBadges({
  item,
}: {
  item: Pick<
    SimpleProduct,
    "lifecycle_status" | "operational_hold"
  >;
}) {
  const { t, i18n } = useTranslation();
  const { product, sales } =
    productTableStatus(item);

  return (
    <div
      dir={i18n.dir()}
      className="grid min-w-[9.5rem] gap-1.5 text-start"
    >
      {[product, sales].map((line) => (
        <div
          key={line.labelKey}
          className="grid grid-cols-[auto_3.2rem_minmax(0,1fr)] items-center gap-1.5 leading-none"
        >
          <span
            aria-hidden="true"
            className={`h-1.5 w-1.5 rounded-full ${dotTones[line.tone]}`}
          />
          <span className="text-[9px] font-bold text-slate-400">
            {t(line.labelKey)}
          </span>
          <span
            className={`truncate text-[10px] font-black ${valueTones[line.tone]}`}
          >
            {t(line.valueKey)}
          </span>
        </div>
      ))}
    </div>
  );
}
