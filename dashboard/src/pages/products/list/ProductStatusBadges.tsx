import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { createInventoryBatchFocusNavigationState } from "@/features/inventory/navigation";
import type {
  ProductBatchRestrictionDisposition,
  SimpleProduct,
} from "@/pages/products/contracts";
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

const restrictionOrder: ProductBatchRestrictionDisposition[] = [
  "QUARANTINED",
  "BLOCKED",
  "RECALLED",
];

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
  const restrictionSummary = showBatchWarning
    ? restrictionOrder
        .filter(
          (disposition) =>
            restrictions.counts_by_disposition[disposition] > 0,
        )
        .map(
          (disposition) =>
            `${t(
              `products.commercialStatus.batchRestrictionStates.${disposition}`,
            )}: ${restrictions.counts_by_disposition[disposition]}`,
        )
        .join(" · ")
    : "";

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
        <button
          type="button"
          onClick={() =>
            navigate("/inventory", {
              state: createInventoryBatchFocusNavigationState({
                variantId: item.id,
                batchId:
                  restrictions.representative_reason?.batch_id ?? null,
                productName: item.name,
              }),
            })
          }
          aria-label={t(
            restrictions.representative_reason
              ? "products.commercialStatus.batchRestrictionOpen"
              : "products.commercialStatus.batchRestrictionOpenList",
          )}
          className="mt-1.5 block w-full border-s-2 border-amber-300 ps-3 text-start transition hover:bg-amber-50/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        >
          <p className="text-[9px] font-black leading-4 text-amber-900">
            {t(
              "products.commercialStatus.batchRestrictionWarning",
              { count: restrictions.affected_batch_count },
            )}
          </p>
          <p className="text-[8px] font-semibold leading-4 text-slate-500">
            {restrictionSummary}
          </p>
          {restrictions.representative_reason ? (
            <p className="text-[8px] font-semibold leading-4 text-slate-600">
              {t(
                "products.commercialStatus.batchRestrictionReason",
                {
                  reason:
                    restrictions.representative_reason.disposition_reason,
                },
              )}
            </p>
          ) : null}
          <span className="mt-0.5 block text-[8px] font-black leading-4 text-amber-800 underline underline-offset-2">
            {t(
              restrictions.representative_reason
                ? "products.commercialStatus.batchRestrictionOpen"
                : "products.commercialStatus.batchRestrictionOpenList",
            )}
          </span>
        </button>
      ) : null}
    </div>
  );
}
