import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import type { ArchiveBlocker } from "../contracts";
import { resolveI18nLocale } from "@/lib/locale";
import { archiveOwnerGap, archiveOwnerNavigation } from "./navigation";

export function ArchiveBlockerList({ blockers, variantId }: { blockers: ArchiveBlocker[]; variantId: number }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const number = new Intl.NumberFormat(resolveI18nLocale(i18n));
  return <ul className="mt-3 divide-y divide-amber-100" dir={i18n.dir()}>
    {blockers.map((blocker) => {
      const action = archiveOwnerNavigation(blocker, variantId);
      return <li key={blocker.code} className="grid gap-2 py-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
        <div>
          <p className="text-xs font-bold">{t(`catalogLifecycle.blockers.${blocker.code}`, { defaultValue: t("archiveOwners.unknown") })}</p>
          <p className="mt-1 text-xs font-normal leading-5">
            {t(action ? `archiveOwners.hints.${action.label}` : `archiveOwners.gaps.${archiveOwnerGap(blocker)}`)}
          </p>
          {blocker.code === "PRODUCT_LOCATION" && action && <p className="mt-1 text-xs font-normal">{t("archiveOwners.historyGuard")}</p>}
        </div>
        <div className="flex items-center gap-2">
          <span className="tabular-nums">{number.format(blocker.count)}</span>
          {action && <button type="button" onClick={() => navigate(action.path, { state: action.state })}
            className="rounded-lg border border-amber-200 bg-white px-3 py-2 text-xs font-bold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500">
            {t(`archiveOwners.actions.${action.label}`)}
          </button>}
        </div>
      </li>;
    })}
  </ul>;
}
