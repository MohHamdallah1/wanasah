import { useCallback, useEffect, useState } from "react";
import { SettlementModal } from "@/components/operations/SettlementModal";
import { FINANCIAL_SETTLEMENT_READY_STATUS, type DriverData, type SessionSettlementReport } from "@/data/operations-data";
import type { SettlementAuthFetch } from "./api";
import { RepresentativeCustodyModal } from "./RepresentativeCustodyModal";

export function RepresentativeSettlementJourney({
  isOpen, onClose, driver, report, isReportLoading, reportError, onRetryReport,
  isSubmitting, onConfirmSettlement, authFetch, onCustodyCompleted,
}: {
  isOpen: boolean;
  onClose: () => void;
  driver: DriverData | null;
  report: SessionSettlementReport | null;
  isReportLoading: boolean;
  reportError: string | null;
  onRetryReport: () => void;
  isSubmitting: boolean;
  onConfirmSettlement: (actualCash: number, notes: string) => void;
  authFetch: SettlementAuthFetch;
  onCustodyCompleted: (sessionId: number) => void;
}) {
  const [phase, setPhase] = useState<"custody" | "financial">("custody");
  const handleFinancialReady = useCallback((sessionId: number) => {
    setPhase("financial");
    onCustodyCompleted(sessionId);
  }, [onCustodyCompleted]);

  useEffect(() => {
    if (!isOpen || !driver) return;
    setPhase(driver.settlement.status === FINANCIAL_SETTLEMENT_READY_STATUS ? "financial" : "custody");
  }, [driver, isOpen]);
  if (!driver) return null;
  if (phase === "financial") {
    return <SettlementModal isOpen={isOpen} onClose={onClose} driver={driver} report={report} isReportLoading={isReportLoading} reportError={reportError} onRetryReport={onRetryReport} isSubmitting={isSubmitting} onConfirmSettlement={onConfirmSettlement} />;
  }
  return <RepresentativeCustodyModal isOpen={isOpen} onClose={onClose} driverName={driver.session.driver_name} sessionId={driver.session.session_id} authFetch={authFetch} onFinancialReady={handleFinancialReady} />;
}
