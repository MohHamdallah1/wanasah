import {
  Activity,
  ShieldAlert,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  CatalogVariant,
} from "@/pages/inventory/catalog/contracts";

type Props = {
  variant: CatalogVariant;
};

const lifecycleTone = (
  status: CatalogVariant["lifecycle_status"],
) => {
  if (status === "ACTIVE") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (status === "RETIRING") {
    return "border-amber-200 bg-amber-50 text-amber-800";
  }
  if (status === "ARCHIVED") {
    return "border-slate-200 bg-slate-100 text-slate-600";
  }
  return "border-sky-200 bg-sky-50 text-sky-700";
};

const holdTone = (
  hold: CatalogVariant["operational_hold"],
) => {
  if (hold === "RECALL") {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }
  if (hold === "SALES_HOLD") {
    return "border-amber-200 bg-amber-50 text-amber-800";
  }
  return "border-slate-200 bg-white text-slate-600";
};

export function ProductLifecycleStatusRail({
  variant,
}: Props) {
  const { t } = useTranslation();

  return (
    <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
      <div className="flex min-w-0 items-center gap-2.5 rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white text-slate-500 ring-1 ring-slate-200">
          <Activity className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="text-[10px] font-bold text-slate-400">
            {t(
              "products.details.lifecycle",
            )}
          </p>
          <span
            className={`mt-1 inline-flex rounded-full border px-2 py-0.5 text-[10px] font-black ${lifecycleTone(
              variant.lifecycle_status,
            )}`}
          >
            {t(
              `products.details.lifecycleModes.${variant.lifecycle_status}`,
            )}
          </span>
        </div>
      </div>

      <div className="flex min-w-0 items-center gap-2.5 rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white text-slate-500 ring-1 ring-slate-200">
          <ShieldAlert className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="text-[10px] font-bold text-slate-400">
            {t(
              "products.details.operationalHold",
            )}
          </p>
          <span
            className={`mt-1 inline-flex rounded-full border px-2 py-0.5 text-[10px] font-black ${holdTone(
              variant.operational_hold,
            )}`}
          >
            {t(
              `products.details.holdModes.${variant.operational_hold}`,
            )}
          </span>
        </div>
      </div>

      <div className="flex items-center justify-center rounded-xl border border-slate-200 bg-white px-3 py-2 text-[10px] font-black tabular-nums text-slate-400">
        v{variant.version}
      </div>
    </div>
  );
}
