import { useTranslation } from "react-i18next";

import type { WholeProductIssueSourcesPage } from "./wholeProductIssueContract";

/** Present company-level server evidence, never derive it from readable stock. */
export function ProductQualityReadiness({ evidence, checking }: {
  evidence: Pick<WholeProductIssueSourcesPage, "ready_to_resume_sales" | "company_requirements_remaining">;
  checking: boolean;
}) {
  const { t } = useTranslation();
  return <div role="status" aria-live="polite" className="space-y-1 rounded-xl border border-border bg-card p-3 text-card-foreground">
    {checking ? <p className="text-sm">{t("common.loading")}</p> : <>
      <p className="text-sm font-semibold">{t(evidence.ready_to_resume_sales
        ? "inventoryQualityIssue.readiness.readyTitle" : "inventoryQualityIssue.readiness.pendingTitle")}</p>
      <p className="text-xs text-muted-foreground">{t(evidence.company_requirements_remaining
        ? "inventoryQualityIssue.readiness.pendingHint" : "inventoryQualityIssue.readiness.readyHint")}</p>
    </>}
  </div>;
}
