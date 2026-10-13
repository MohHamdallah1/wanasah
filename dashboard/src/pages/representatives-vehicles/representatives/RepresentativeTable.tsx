import { useTranslation } from "react-i18next";

import type { Representative } from "./contracts";
import { formatRepresentativeMoney } from "./representativeMoney";
import { RepresentativeRowActions } from "./RepresentativeRowActions";

interface RepresentativeTableProps {
  items: Representative[];
  loading?: boolean;
  canManage: boolean;
  canResetCredentials: boolean;
  onEdit: (representative: Representative) => void;
  onLifecycle: (representative: Representative) => void;
  onResetCredentials: (representative: Representative) => void;
}

export function RepresentativeTable({
  items,
  loading = false,
  canManage,
  canResetCredentials,
  onEdit,
  onLifecycle,
  onResetCredentials,
}: RepresentativeTableProps) {
  const { t } = useTranslation();
  const jodLabel = t("representativesVehicles.representatives.currency.jod");

  if (loading && items.length === 0) {
    return (
      <div className="space-y-2 p-3" role="status" aria-label={t("representativesVehicles.representatives.loading")}>
        {[0, 1, 2, 3].map((row) => (
          <div key={row} className="h-14 animate-pulse rounded-xl bg-slate-100" />
        ))}
      </div>
    );
  }

  return (
    <table className="w-full min-w-[880px] table-fixed border-separate border-spacing-0 text-start text-sm">
      <colgroup>
        <col className="w-[24%]" />
        <col className="w-[17%]" />
        <col className="w-[18%]" />
        <col className="w-[24%]" />
        <col className="w-[10%]" />
        <col className="w-[7%]" />
      </colgroup>
      <thead className="sticky top-0 z-10 bg-slate-50/95 text-[11px] font-black text-slate-500 backdrop-blur">
        <tr>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.representatives.fields.name")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.representatives.fields.username")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.representatives.fields.phone")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.representatives.fields.debtPermission")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.representatives.fields.status")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-center">{t("representativesVehicles.representatives.actions")}</th>
        </tr>
      </thead>
      <tbody>
        {items.map((representative) => (
          <tr key={representative.id} className="group transition hover:bg-amber-50/55">
            <td className="border-b border-slate-100 px-4 py-3 text-start font-black text-slate-800">{representative.full_name}</td>
            <td className="border-b border-slate-100 px-4 py-3 text-start font-semibold text-slate-600"><bdi dir="ltr">{representative.username}</bdi></td>
            <td className="border-b border-slate-100 px-4 py-3 text-start font-semibold text-slate-600"><bdi dir="ltr">{representative.phone_number || "—"}</bdi></td>
            <td className="border-b border-slate-100 px-4 py-3 text-start font-semibold text-slate-600">
              {representative.can_allow_debt
                ? t("representativesVehicles.representatives.fields.creditAllowed", {
                    limit: formatRepresentativeMoney(representative.max_debt_limit, {
                      currencyLabel: jodLabel,
                    }),
                  })
                : t("representativesVehicles.representatives.fields.creditDisabled")}
            </td>
            <td className="border-b border-slate-100 px-4 py-3 text-start">
              <span className={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-black ${representative.is_active ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200" : "bg-slate-100 text-slate-600 ring-1 ring-slate-200"}`}>
                {t(representative.is_active ? "representativesVehicles.representatives.active" : "representativesVehicles.representatives.inactive")}
              </span>
            </td>
            <td className="border-b border-slate-100 px-4 py-2 text-center">
              <RepresentativeRowActions
                representative={representative}
                canManage={canManage}
                canResetCredentials={canResetCredentials}
                onEdit={onEdit}
                onLifecycle={onLifecycle}
                onResetCredentials={onResetCredentials}
              />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
