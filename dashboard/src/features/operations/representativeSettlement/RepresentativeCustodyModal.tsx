import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import { apiErrorMessage } from "@/lib/apiErrors";
import {
  approveVariance,
  authorizeRecount,
  loadReceivingWarehouses,
  readCustody,
  readRecountSheet,
  readVariance,
  receiveCustody,
  submitRecount,
  type SettlementAuthFetch,
} from "./api";
import type { CustodySnapshot, ReceivingWarehouse, RecountSheet, VarianceReview } from "./contracts";
import { representativeSettlementCopy } from "./copy";
import { CustodyCountStep, RecountStep, VarianceReviewStep } from "./SettlementCustodySteps";

type Stage = "loading" | "count" | "review" | "recount" | "handoff" | "transition";

export function RepresentativeCustodyModal({
  isOpen, onClose, driverName, sessionId, authFetch, onFinancialReady,
}: {
  isOpen: boolean;
  onClose: () => void;
  driverName: string;
  sessionId: number;
  authFetch: SettlementAuthFetch;
  onFinancialReady: (sessionId: number) => void;
}) {
  const { i18n } = useTranslation();
  const copy = representativeSettlementCopy(i18n.resolvedLanguage || i18n.language);
  const dir = i18n.dir();
  const [stage, setStage] = useState<Stage>("loading");
  const [custody, setCustody] = useState<CustodySnapshot | null>(null);
  const [warehouses, setWarehouses] = useState<ReceivingWarehouse[]>([]);
  const [destinationId, setDestinationId] = useState("");
  const [actual, setActual] = useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = useState(false);
  const [notes, setNotes] = useState("");
  const [variance, setVariance] = useState<VarianceReview | null>(null);
  const [recountSheet, setRecountSheet] = useState<RecountSheet | null>(null);
  const [recountActual, setRecountActual] = useState<Record<string, string>>({});
  const [recountNotes, setRecountNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [validation, setValidation] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadVarianceReview = useCallback(async (signal?: AbortSignal) => {
    const review = await readVariance(authFetch, sessionId, signal);
    setVariance(review);
    setError(null);
    setStage("review");
  }, [authFetch, sessionId]);

  const resumeVarianceStage = useCallback(async (signal?: AbortSignal) => {
    try {
      const sheet = await readRecountSheet(authFetch, sessionId, signal);
      setRecountSheet(sheet);
      setRecountActual({});
      setError(null);
      setStage("recount");
      return;
    } catch {
      // PENDING_REVIEW has no blind count sheet; use the business variance review.
    }
    await loadVarianceReview(signal);
  }, [authFetch, loadVarianceReview, sessionId]);

  const loadJourney = useCallback(async (signal?: AbortSignal) => {
    setStage("loading");
    setError(null);
    const [snapshot, destinations] = await Promise.all([
      readCustody(authFetch, sessionId, signal),
      loadReceivingWarehouses(authFetch, signal),
    ]);
    setCustody(snapshot);
    setWarehouses(destinations);
    setDestinationId((current) => current && destinations.some((item) => String(item.id) === current) ? current : "");
    setConfirmed(false);
    setValidation(null);
    if (snapshot.custody_received) {
      setStage("transition");
      onFinancialReady(sessionId);
      return;
    }
    if (snapshot.review_required) {
      await resumeVarianceStage(signal);
      return;
    }
    if (snapshot.inventory_reconciled) {
      setActual(Object.fromEntries(snapshot.lines.map((line) => [line.line_key, line.expected_quantity])));
      setStage("handoff");
      return;
    }
    setActual({});
    setStage("count");
  }, [authFetch, onFinancialReady, resumeVarianceStage, sessionId]);

  useEffect(() => {
    if (!isOpen) return;
    const controller = new AbortController();
    setCustody(null);
    setVariance(null);
    setRecountSheet(null);
    setActual({});
    setRecountActual({});
    setNotes("");
    setRecountNotes("");
    setDestinationId("");
    setConfirmed(false);
    void loadJourney(controller.signal).catch((loadError: unknown) => {
      if (!controller.signal.aborted) {
        setError(apiErrorMessage(loadError, copy.loadError));
        setStage("loading");
      }
    });
    return () => controller.abort();
  }, [copy.loadError, isOpen, loadJourney]);

  const submitReceipt = async () => {
    if (!custody || busy) return;
    setValidation(null);
    if (!destinationId) { setValidation(copy.warehouseRequired); return; }
    if (!confirmed) { setValidation(copy.confirmationRequired); return; }
    const items = custody.lines.map((line) => ({
      line_key: line.line_key,
      actual_quantity: stage === "handoff" ? line.expected_quantity : (actual[line.line_key] ?? "").trim(),
    }));
    if (items.some((item) => !item.actual_quantity)) { setValidation(copy.countRequired); return; }
    setBusy(true);
    setError(null);
    try {
      const result = await receiveCustody(authFetch, sessionId, {
        destination_location_id: Number(destinationId),
        receiver_confirms_handoff: true,
        items,
        notes: notes.trim() || null,
      });
      if (result.review_required || result.status === "REVIEW_REQUIRED") {
        await loadVarianceReview();
      } else if (result.financial_ready || result.status === "CUSTODY_RECEIVED") {
        setStage("transition");
        onFinancialReady(sessionId);
      } else {
        await loadJourney();
      }
    } catch (submitError: unknown) {
      setError(apiErrorMessage(submitError, copy.loadError));
    } finally {
      setBusy(false);
    }
  };

  const requestRecount = async (payload: { reason: string; authorizer_username: string; authorizer_password: string }) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await authorizeRecount(authFetch, sessionId, payload);
      const sheet = await readRecountSheet(authFetch, sessionId);
      setRecountSheet(sheet);
      setRecountActual({});
      setRecountNotes("");
      setStage("recount");
    } catch (commandError: unknown) {
      setError(apiErrorMessage(commandError, copy.loadError));
    } finally {
      setBusy(false);
    }
  };

  const submitRecountResult = async () => {
    if (!recountSheet || busy) return;
    setValidation(null);
    const items = recountSheet.lines.map((line) => ({ line_key: line.line_key, actual_quantity: (recountActual[line.line_key] ?? "").trim() }));
    if (items.some((item) => !item.actual_quantity)) { setValidation(copy.countRequired); return; }
    setBusy(true);
    setError(null);
    try {
      await submitRecount(authFetch, sessionId, { items, notes: recountNotes.trim() || null });
      await loadVarianceReview();
    } catch (commandError: unknown) {
      setError(apiErrorMessage(commandError, copy.loadError));
    } finally {
      setBusy(false);
    }
  };

  const approve = async (payload: { password: string; notes: string | null }) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await approveVariance(authFetch, sessionId, payload);
      const snapshot = await readCustody(authFetch, sessionId);
      setCustody(snapshot);
      setActual(Object.fromEntries(snapshot.lines.map((line) => [line.line_key, line.expected_quantity])));
      setConfirmed(false);
      setValidation(null);
      setStage(snapshot.custody_received ? "transition" : "handoff");
      if (snapshot.custody_received) onFinancialReady(sessionId);
    } catch (commandError: unknown) {
      setError(apiErrorMessage(commandError, copy.loadError));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={busy ? () => undefined : onClose} title={copy.title + " — " + driverName} maxWidth="max-w-5xl">
      <div dir={dir} className="max-h-[78vh] overflow-y-auto p-1">
        {stage === "loading" && <div className="min-h-56 flex flex-col items-center justify-center gap-4">
          <p className="font-bold text-slate-500">{copy.loading}</p>
          {error && <><p role="alert" className="text-sm font-bold text-red-600">{error}</p><button type="button" onClick={() => void loadJourney().catch((e) => setError(apiErrorMessage(e, copy.loadError)))} className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-black text-white">{copy.retry}</button></>}
        </div>}
        {(stage === "count" || stage === "handoff") && custody && <CustodyCountStep
          snapshot={custody} warehouses={warehouses} destinationId={destinationId} onDestinationChange={setDestinationId}
          actual={actual} onActualChange={(key, value) => setActual((current) => ({ ...current, [key]: value }))}
          readOnly={stage === "handoff"} confirmed={confirmed} onConfirmedChange={setConfirmed}
          notes={notes} onNotesChange={setNotes} busy={busy} validation={validation || error}
          onSubmit={() => void submitReceipt()} copy={copy}
        />}
        {stage === "review" && variance && <VarianceReviewStep review={variance} busy={busy} error={error} onRecount={(payload) => void requestRecount(payload)} onApprove={(payload) => void approve(payload)} copy={copy} />}
        {stage === "recount" && recountSheet && <RecountStep sheet={recountSheet} actual={recountActual} onActualChange={(key, value) => setRecountActual((current) => ({ ...current, [key]: value }))} notes={recountNotes} onNotesChange={setRecountNotes} busy={busy} validation={validation || error} onSubmit={() => void submitRecountResult()} copy={copy} />}
        {stage === "transition" && <div className="min-h-56 flex items-center justify-center"><p role="status" className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 font-black text-emerald-800">{copy.financialTransition}</p></div>}
      </div>
    </Modal>
  );
}
