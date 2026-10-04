import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorMessage } from "@/lib/apiErrors";
import { FINANCIAL_SETTLEMENT_READY_STATUS, parseDriverDataList, type DriverData } from "@/data/operations-data";
import type { SettlementOwnerIntent } from "./navigation";

export function useSettlementOwnerNavigation({ intent, onReady, onConsumed }: {
  intent: SettlementOwnerIntent | null;
  onReady: (driver: DriverData) => void;
  onConsumed: () => void;
}) {
  const authFetch = useAuthFetch();
  const { t } = useTranslation();
  useEffect(() => {
    if (!intent) return;
    const controller = new AbortController();
    void authFetch(`/admin/sessions/today?session_id=${intent.sessionId}`, { signal: controller.signal })
      .then((raw) => {
        if (controller.signal.aborted) return;
        const driver = parseDriverDataList(raw).find((item) => item.session.session_id === intent.sessionId);
        if (!driver || driver.settlement.status !== FINANCIAL_SETTLEMENT_READY_STATUS) throw new Error(t("archiveOwners.inaccessible"));
        onReady(driver);
      }).catch((error: unknown) => {
        if (!controller.signal.aborted) toast.error(apiErrorMessage(error, t("archiveOwners.inaccessible")));
      }).finally(() => { if (!controller.signal.aborted) onConsumed(); });
    return () => controller.abort();
  }, [authFetch, intent, onConsumed, onReady, t]);
}
