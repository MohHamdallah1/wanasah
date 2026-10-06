import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { createInventoryBatchFocusNavigationState } from "@/features/inventory/navigation";
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
    "id" | "name" | "lifecycle_status" | "operational_hold" | "status_reason"
  > &
    Partial<Pick<SimpleProduct, "batch_restrictions">>;
}) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { status, reason } = productTableStatus(item);
  const restrictions = item.batch_restrictions ?? null;
  const statusReason = item.status_reason?.trim() || null;
  const showBatchWarning =
    item.lifecycle_status === "ACTIVE" &&
    item.operational_hold === "NONE" &&
    restrictions !== null &&
    restrictions.affected_batch_count > 0;

  const openAffectedBatches = () => {
    navigate("/inventory", {
      state: createInventoryBatchFocusNavigationState({
        variantId: item.id,
        batchId: null,
        productName: item.name,
      }),
    });
  };

  return (
    <div dir={i18n.dir()} className="min-w-[8.75rem] text-start">
      <div className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className={`h-2 w-2 shrink-0 rounded-full ${dotTones[status.tone]}`}
        />
        <span className={`text-[11px] font-black ${valueTones[status.tone]}`}>
          {t(status.valueKey)}
        </span>
      </div>

      {reason ? (
        <p
          title={
            statusReason
              ? `${t(reason.valueKey)} (${statusReason})`
              : t(reason.valueKey)
          }
          className="mt-1 max-w-[18rem] truncate whitespace-nowrap ps-4 text-[9px] font-semibold leading-4 text-slate-500"
        >
          {t(reason.valueKey)}
          {statusReason ? ` (${statusReason})` : ""}
        </p>
      ) : null}

      {showBatchWarning && restrictions ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 ps-4">
          <span className="text-[9px] font-black text-amber-800">
            {t("productQualityWorkspace.affectedBatchesCompact", {
              count: restrictions.affected_batch_count,
            })}
          </span>
          <button
            type="button"
            onClick={openAffectedBatches}
            className="text-[9px] font-black text-slate-700 underline decoration-slate-300 underline-offset-2 transition hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
          >
            {t("productQualityWorkspace.manageAffectedBatches")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
