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
  good: "text-slate-950",
  warning: "text-amber-950",
  muted: "text-slate-700",
  blocked: "text-rose-900",
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
  const { status, reason } =
    productTableStatus(item);

  return (
    <div
      dir={i18n.dir()}
      className="min-w-[8.75rem] text-start"
    >
      <div className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className={`h-2 w-2 shrink-0 rounded-full ${dotTones[status.tone]}`}
        />
        <span
          className={`text-[11px] font-black ${valueTones[status.tone]}`}
        >
          {t(status.valueKey)}
        </span>
      </div>
      {reason ? (
        <p className="mt-1 ps-4 text-[9px] font-semibold leading-4 text-slate-500">
          {t(reason.valueKey)}
        </p>
      ) : null}
    </div>
  );
}
