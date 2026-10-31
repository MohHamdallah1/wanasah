import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Modal } from "@/components/ui/modal";
import { apiErrorMessage } from "@/lib/apiErrors";
import { durableScope } from "@/lib/durableOperations";
import { addQuantity, subtractQuantity, compareQuantity } from "@/lib/quantity";
import { formatLocaleDecimal } from "@/lib/localeNumbers";
import { currentLocale } from "@/i18n";
import type { PendingRoute } from "@/types/dispatch";
import { adjustmentReview, buildAdjustmentPayload, parseAdjustmentDraft, type AdjustLoadItem } from "@/features/dispatch/adjustLoad";
import { formatRouteLoadQuantity } from "@/features/dispatch/routeLoadUom";
import { ProductSearchControls } from "./ProductSearchControls";
import { MeasuredProductPage } from "./DispatchProductWindow";
import { useDispatchWindowSentinels } from "@/features/dispatch/useDispatchWindowSentinels";
import { useLoadProductSearchText } from "@/features/dispatch/useLoadProductSearchText";
import { useAdjustLoadCommand } from "@/features/dispatch/useAdjustLoadCommand";
import { hasAdjustmentDraft, useAdjustLoadProducts } from "@/features/dispatch/useAdjustLoadProducts";

// DASHBOARD_DISPATCH_ROUTE_CONTRACT_V3
interface AdjustInventoryModalProps {
  isOpen: boolean;
  onClose: () => void;
  route: PendingRoute | null;
  onSuccess: () => void | Promise<void>;
  companyId?: number;
  principalId?: number;
}

export function AdjustInventoryModal({
  isOpen, onClose, route, onSuccess, companyId, principalId,
}: AdjustInventoryModalProps) {
  const { t, i18n } = useTranslation();
  const loadContext = JSON.stringify([
    route?.id,
    route?.vehicleId,
    route?.sourceWarehouseId,
    route?.workSessionId ?? null,
    route?.adjustmentContextRevision ?? 1,
  ]);
  const command = useAdjustLoadCommand(isOpen ? route?.id : undefined, companyId, principalId, loadContext);
  const legacyScope = isOpen && route?.id && Number.isSafeInteger(companyId) && (companyId ?? 0) > 0 &&
    Number.isSafeInteger(principalId) && (principalId ?? 0) > 0
    ? durableScope(companyId!, principalId!, "dispatch-adjust-base", route.id) : null;
  const [draftDeltas, setDeltas] = useState<Record<string, string>>({});
  const [draftScope, setDraftScope] = useState<string | null>(null);
  const [draftError, setDraftError] = useState(false);
  const [pendingContext, setPendingContext] = useState<{
    scope: string; context: string; deltas: Record<string, string>;
  } | null>(null);
  const [reviewOld, setReviewOld] = useState(false);
  const [closePrompt, setClosePrompt] = useState(false);
  const [cancelLegacyPrompt, setCancelLegacyPrompt] = useState(false);
  const contextScope = command.scope ? `${command.scope}:${loadContext}` : null;
  // Storage and execution are bound to the precise physical context. Never
  // reuse a draft for the same route after changing its Vehicle or Warehouse.
  const draftKey = (scope: string, context: string) =>
    `${scope}:draft:${encodeURIComponent(context)}`;
  const deltas = draftScope === contextScope ? draftDeltas : {};
  const [search, setSearch] = useLoadProductSearchText(JSON.stringify([isOpen, contextScope]));
  const [step, setStep] = useState<"edit" | "review">("edit");
  const products = useAdjustLoadProducts(isOpen ? route?.id : undefined, step === "edit" ? search : "", deltas, command.scope, loadContext, step === "edit");
  const { items: inventory, pinnedItems, loading } = products;
  const pinnedIds = useMemo(() => new Set(pinnedItems.map((item) => item.product_id)), [pinnedItems]);
  const { topRef, bottomRef } = useDispatchWindowSentinels(products.page);

  useEffect(() => {
    setStep("edit");
    setCancelLegacyPrompt(false);
  }, [isOpen, loadContext]);

  useEffect(() => {
    setDraftError(false);
    setClosePrompt(false);
    if (!isOpen || !command.scope || !contextScope) {
      setDraftScope(null);
      setPendingContext(null);
      setReviewOld(false);
      return;
    }
    // Capture the previous scope BEFORE loading the new one. Changing a route,
    // physical custody location, or signed-in principal must never erase edits.
    if (draftScope && draftScope !== contextScope &&
        Object.values(draftDeltas).some(hasAdjustmentDraft)) {
      const separator = draftScope.lastIndexOf(":[");
      const oldScope = separator >= 0 ? draftScope.slice(0, separator) : "";
      const oldContext = separator >= 0 ? draftScope.slice(separator + 1) : "";
      if (oldScope && oldContext) {
        try { localStorage.setItem(draftKey(oldScope, oldContext), JSON.stringify(draftDeltas)); }
        catch { setDraftError(true); }
        setPendingContext((previous) => previous ?? { scope: oldScope, context: oldContext, deltas: { ...draftDeltas } });
      }
    }
    try {
      const storedContext = legacyScope ? localStorage.getItem(`${legacyScope}:draft-context`) : null;
      const oldValue = legacyScope ? localStorage.getItem(`${legacyScope}:draft`) : null;
      const legacyDraft = oldValue && storedContext ? Object.fromEntries(
        Object.entries(parseAdjustmentDraft(oldValue)).filter(([, value]) => hasAdjustmentDraft(value))
      ) : {};
      if (storedContext && Object.keys(legacyDraft).length) {
        const identity = JSON.parse(storedContext) as unknown;
        if (!Array.isArray(identity) || identity.length !== 3 || identity[0] !== route?.id) {
          throw new Error("Legacy draft physical identity is invalid");
        }
        const oldCommandScope = durableScope(companyId!, principalId!, "dispatch-adjust-base",
          `${route!.id}:${storedContext}`);
        const migratedKey = draftKey(oldCommandScope, storedContext);
        if (localStorage.getItem(migratedKey) === null) {
          localStorage.setItem(migratedKey, JSON.stringify(legacyDraft));
        }
        if (storedContext !== loadContext) {
          setPendingContext((previous) => previous ?? {
            scope: oldCommandScope, context: storedContext, deltas: legacyDraft,
          });
        }
        // Preserve the durable request-id key: only retire migrated draft slots.
        localStorage.removeItem(`${legacyScope}:draft`);
        localStorage.removeItem(`${legacyScope}:draft-context`);
      }
      const rawDraft = localStorage.getItem(draftKey(command.scope, loadContext));
      const restored = Object.fromEntries(Object.entries(parseAdjustmentDraft(rawDraft))
        .filter(([, value]) => hasAdjustmentDraft(value)));
      setDeltas(restored);
      setDraftScope(contextScope);
    } catch { setDraftError(true); setDraftScope(null); setDeltas({}); }
  // Only scope transitions load a different draft; editing deltas must not rehydrate.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, contextScope]);
  useEffect(() => {
    if (isOpen && command.scope && draftScope === contextScope && !draftError) {
      try {
        localStorage.setItem(draftKey(command.scope, loadContext), JSON.stringify(draftDeltas));
      } catch { setDraftError(true); }
    }
  }, [command.scope, contextScope, loadContext, draftDeltas, draftError, draftScope, isOpen]);

  const blocked = !command.scope || !command.ready || loading || command.busy ||
    command.recoveryRequired || !!command.recoveryError || draftError || !!products.error ||
    !!pendingContext || draftScope !== contextScope;
  const update = (id: string, value: string) => {
    if (blocked) return;
    setDeltas((current) => {
      const next = { ...current };
      if (hasAdjustmentDraft(value)) next[id] = value; else delete next[id];
      return next;
    });
  };
  const changeByStep = (item: AdjustLoadItem, increase: boolean) => {
    try {
      const value = (increase ? addQuantity : subtractQuantity)(deltas[item.product_id] || "0", item.quantity_step);
      adjustmentReview(item, value);
      update(item.product_id, value);
    } catch { toast.error(t("dispatchAdjustLoad.invalid")); }
  };
  const review = () => {
    try {
      const payload = buildAdjustmentPayload(inventory, deltas, route?.sessionBound);
      if (!payload.deltas.length) return toast.info(t("dispatchAdjustLoad.empty"));
      setStep("review");
    } catch (error) { toast.error(apiErrorMessage(error, t("dispatchAdjustLoad.invalid"))); }
  };
  const save = async (retry = false) => {
    try {
      const payload = retry ? undefined : buildAdjustmentPayload(inventory, deltas, route?.sessionBound);
      if (payload && !payload.deltas.length) return;
      const mode = await command.execute(payload);
      if (!mode) return;
      if (command.scope) {
        localStorage.removeItem(draftKey(command.scope, loadContext));
      }
      setDeltas({});
      toast.success(t(mode === "HANDSHAKE" ? "dispatchAdjustLoad.handshake" : "dispatchAdjustLoad.saved"));
      await onSuccess();
      onClose();
    } catch (error) { toast.error(apiErrorMessage(error, t("dispatchAdjustLoad.saveError"))); }
  };
  const previousOwnIdentity = !!pendingContext && !!command.scope &&
    pendingContext.scope.split(":").slice(0, 5).join(":") ===
    command.scope.split(":").slice(0, 5).join(":");
  const hasUnsent = Object.values(deltas).some(hasAdjustmentDraft);
  const requestClose = () => {
    if (command.busy) return;
    if (hasUnsent || command.recoveryRequired) setClosePrompt(true);
    else onClose();
  };
  const discardCurrent = () => {
    if (!command.scope || command.recoveryRequired || command.busy) return;
    try {
      localStorage.removeItem(draftKey(command.scope, loadContext));
      setDeltas({});
      setClosePrompt(false);
      onClose();
    } catch { setDraftError(true); }
  };
  const resolvePrevious = (discard: boolean) => {
    if (!pendingContext || command.busy || command.recoveryRequired) return;
    // A different account may not read or delete a previous account's draft.
    if (discard && !previousOwnIdentity) return;
    try {
      if (discard) localStorage.removeItem(draftKey(pendingContext.scope, pendingContext.context));
      setPendingContext(null);
      setReviewOld(false);
    } catch { setDraftError(true); }
  };
  const reviewRows = inventory.filter((item) => compareQuantity(deltas[item.product_id] || "0", "0") !== 0);
  const renderRow = (item: AdjustLoadItem) => {
    let preview: ReturnType<typeof adjustmentReview> | null = null;
    try { preview = adjustmentReview(item, deltas[item.product_id] || "0"); } catch { /* Show the localized validation hint. */ }
    const unitLabel = t(`uom.${item.base_uom_code}`, { defaultValue: item.base_uom_name });
    const unit = { ...item, base_uom_name: unitLabel };
    return (
      <section key={item.product_id} data-product-id={item.product_id} className="space-y-2 rounded-xl border p-3">
        <h3 className="font-bold">{item.product_name}</h3>
        <p>{t("dispatchAdjustLoad.current")}: <strong>{formatRouteLoadQuantity(item.current_base_quantity, unit)}</strong></p>
        <p className="text-sm">{t("dispatchAdjustLoad.base", {
          quantity: formatLocaleDecimal(item.current_base_quantity, currentLocale()), unit: unitLabel,
        })}</p>
        {compareQuantity(item.reserved_base_quantity, "0") > 0 && <p>{t("dispatchAdjustLoad.reserved")}: {formatRouteLoadQuantity(item.reserved_base_quantity, unit)}</p>}
        {compareQuantity(item.pending_base_quantity, "0") !== 0 && <p>{t("dispatchAdjustLoad.pending")}: {formatRouteLoadQuantity(item.pending_base_quantity, unit)}</p>}
        {step === "edit" ? (
          <label className="flex flex-wrap items-center gap-2">
            <span>{t("dispatchAdjustLoad.delta", { unit: unitLabel })}</span>
            <button type="button" aria-label={t("dispatchAdjustLoad.decrease")} disabled={blocked} onClick={() => changeByStep(item, false)}>−</button>
            <input type="number" step={item.quantity_step} value={deltas[item.product_id] ?? ""}
              aria-label={t("dispatchAdjustLoad.delta", { unit: unitLabel })} aria-invalid={!preview} disabled={blocked}
              onChange={(event) => update(item.product_id, event.target.value)}
              className="w-28 rounded border p-2" />
            <button type="button" aria-label={t("dispatchAdjustLoad.increase")} disabled={blocked} onClick={() => changeByStep(item, true)}>+</button>
          </label>
        ) : <p>{t("dispatchAdjustLoad.delta", { unit: unitLabel })}: {preview && formatLocaleDecimal(preview.delta, currentLocale())}</p>}
        {preview ? <>
          <p>{t("dispatchAdjustLoad.result")}: <strong>{formatRouteLoadQuantity(preview.result, unit)}</strong></p>
          <p>{t("dispatchAdjustLoad.direction")}: {t(preview.direction === "ADD" ? "dispatchAdjustLoad.addDirection"
            : preview.direction === "UNLOAD" ? "dispatchAdjustLoad.unloadDirection" : "dispatchAdjustLoad.noChange")}</p>
        </> : <p role="alert">{t("dispatchAdjustLoad.invalid")}</p>}
      </section>
    );
  };

  return (
    <Modal isOpen={isOpen} onClose={requestClose}
      title={t(step === "edit" ? "dispatchAdjustLoad.title" : "dispatchAdjustLoad.reviewTitle")}>
      <div dir={i18n.dir()} className="space-y-4">
        {!command.online && <p role="status">{t("dispatchAdjustLoad.offline")}</p>}
        {(command.recoveryError || draftError) && <p role="alert">{t("dispatchAdjustLoad.unknown")}</p>}
        {command.busy && !command.recoveryRequired && <p role="status">{t("dispatchAdjustLoad.saving")}</p>}
        {pendingContext && <section role="alertdialog" aria-label={t("dispatchAdjustLoad.contextChangedTitle")}
          className="space-y-3 rounded-xl border border-amber-300 p-3" data-adjust-context-review>
          <strong>{t("dispatchAdjustLoad.contextChangedTitle")}</strong>
          <p>{t("dispatchAdjustLoad.contextChangedBody")}</p>
          {previousOwnIdentity && <>
            <button type="button" onClick={() => setReviewOld((value) => !value)}>{t("dispatchAdjustLoad.reviewPrevious")}</button>
            {reviewOld && <ul data-adjust-old-draft>{Object.entries(pendingContext.deltas).map(([id, amount]) =>
              <li key={id} dir="ltr">{id}: {amount}</li>)}</ul>}
          </>}
          <div className="flex flex-wrap gap-3">
            <button type="button" onClick={() => resolvePrevious(false)}>{t("dispatchAdjustLoad.keepPrevious")}</button>
            {previousOwnIdentity && <button type="button" onClick={() => resolvePrevious(true)}>
              {t("dispatchAdjustLoad.discardPrevious")}
            </button>}
          </div>
        </section>}
        {closePrompt && <section role="alertdialog" aria-label={t("dispatchAdjustLoad.closeTitle")}
          className="space-y-3 rounded-xl border border-amber-300 p-3" data-adjust-close-review>
          <strong>{t("dispatchAdjustLoad.closeTitle")}</strong>
          <p>{t("dispatchAdjustLoad.closeBody")}</p>
          <div className="flex flex-wrap gap-3">
            <button type="button" onClick={() => setClosePrompt(false)}>{t("dispatchAdjustLoad.continueEditing")}</button>
            <button type="button" onClick={onClose}>{t("dispatchAdjustLoad.keepAndClose")}</button>
            {!command.recoveryRequired && <button type="button" onClick={discardCurrent}>{t("dispatchAdjustLoad.discardAndClose")}</button>}
          </div>
        </section>}
        {command.legacyPending && <section role="alert" className="space-y-3 rounded-xl border p-3"
          data-adjust-legacy-recovery>
          <strong>{t("dispatchAdjustLoad.legacyRecoveryTitle")}</strong>
          <p>{t("dispatchAdjustLoad.legacyRecoveryHint")}</p>
          <button type="button" disabled={!command.online || command.checkingLegacy}
            onClick={() => void command.inspectLegacy().catch((error) =>
              toast.error(apiErrorMessage(error, t("dispatchAdjustLoad.legacyVerifyError"))))}>
            {t("dispatchAdjustLoad.legacyVerify")}
          </button>
          {command.legacyOutcome === "COMMITTED" && <>
            <p role="status">{t("dispatchAdjustLoad.legacyCommitted")}</p>
            <button type="button" onClick={command.acknowledgeCommittedLegacy}>
              {t("dispatchAdjustLoad.legacyAcknowledge")}
            </button>
          </>}
          {command.legacyOutcome === "NOT_CONFIRMED" && <>
            <p role="status">{t("dispatchAdjustLoad.legacyNotConfirmed")}</p>
            <button type="button" disabled={!command.online || command.checkingLegacy || command.cancellingLegacy}
              onClick={() => setCancelLegacyPrompt(true)}>
              {t("dispatchAdjustLoad.legacyCancel")}
            </button>
          </>}
          {command.legacyOutcome === "INDETERMINATE" && <p role="status">
            {t("dispatchAdjustLoad.legacyIndeterminate")}
          </p>}
          {command.legacyOutcome === "CANCELLED" && <>
            <p role="status">{t("dispatchAdjustLoad.legacyCancelled")}</p>
            <button type="button" onClick={command.acknowledgeCancelledLegacy}>
              {t("dispatchAdjustLoad.legacyCancelledAcknowledge")}
            </button>
          </>}
          {cancelLegacyPrompt && command.legacyOutcome === "NOT_CONFIRMED" && <div
            role="alertdialog" aria-label={t("dispatchAdjustLoad.legacyCancelTitle")}
            className="space-y-3 rounded-lg border border-amber-300 p-3">
            <strong>{t("dispatchAdjustLoad.legacyCancelTitle")}</strong>
            <p>{t("dispatchAdjustLoad.legacyCancelHint")}</p>
            <div className="flex flex-wrap gap-3">
              <button type="button" disabled={command.cancellingLegacy}
                onClick={() => setCancelLegacyPrompt(false)}>
                {t("dispatchAdjustLoad.back")}
              </button>
              <button type="button" disabled={command.cancellingLegacy || !command.online}
                onClick={() => void command.cancelLegacy().then((state) => {
                  setCancelLegacyPrompt(false);
                  if (state === "CANCELLED") toast.success(t("dispatchAdjustLoad.legacyCancelSuccess"));
                  else if (state === "COMMITTED") toast.info(t("dispatchAdjustLoad.legacyCommittedBeforeCancel"));
                }).catch((error) =>
                  toast.error(apiErrorMessage(error, t("dispatchAdjustLoad.legacyCancelError"))))}>
                {t(command.cancellingLegacy ? "dispatchAdjustLoad.legacyCancelling" : "dispatchAdjustLoad.legacyCancelConfirm")}
              </button>
            </div>
          </div>}
        </section>}
        {command.recoveryRequired && !command.legacyPending ? <div role="alert" className="space-y-3">
          <p>{t("dispatchAdjustLoad.unknown")}</p>
          <button type="button" onClick={() => void save(true)}
            disabled={command.busy || !command.online || !!command.recoveryError}>{t("common.retry")}</button>
        </div> : !command.legacyPending && <form onSubmit={(event) => {
          event.preventDefault();
          if (blocked) return;
          if (step === "edit") review(); else void save();
        }} className="space-y-4">
          {step === "edit" && <ProductSearchControls search={search} onChange={setSearch} page={products.page} />}
          {loading && <p role="status">{t("common.loading")}</p>}
          {!!products.error && <div role="alert"><p>{apiErrorMessage(products.error, t("dispatchAdjustLoad.loadError"))}</p>
            <button type="button" onClick={products.retry}>{t("common.retry")}</button></div>}
          {!loading && !products.error && !inventory.length && <p role="status">{t("dispatchAdjustLoad.loadedEmpty")}</p>}
          {step === "review" ? (
            <div className="space-y-3">{reviewRows.map(renderRow)}</div>
          ) : <>
            <div className="space-y-3">{pinnedItems.map(renderRow)}</div>
            {products.page.topSpacerHeight > 0 && <div aria-hidden="true" style={{ height: products.page.topSpacerHeight }} />}
            <div ref={topRef} data-window-boundary="top" aria-hidden="true" className="h-px" />
            {products.page.pages.map((windowPage) => (
              <MeasuredProductPage key={windowPage.index} index={windowPage.index} onMeasure={products.page.registerPageHeight} className="space-y-3">
                {windowPage.items.map((product) => product.load!).filter((item) => item && !pinnedIds.has(item.product_id)).map(renderRow)}
              </MeasuredProductPage>
            ))}
            <div ref={bottomRef} data-window-boundary="bottom" aria-hidden="true" className="h-px" />
            {products.page.bottomSpacerHeight > 0 && <div aria-hidden="true" style={{ height: products.page.bottomSpacerHeight }} />}
          </>}
          {route?.sessionBound && <p>{t("dispatchAdjustLoad.handshake")}</p>}
          <div className="flex gap-3 border-t pt-4">
            <button type="button" disabled={command.busy} onClick={() => step === "review" ? setStep("edit") : requestClose()}>
              {t(step === "review" ? "dispatchAdjustLoad.back" : "common.cancel")}
            </button>
            <button type="submit" disabled={blocked || !command.online} className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50">
              {t(step === "review" ? "dispatchAdjustLoad.confirm" : "dispatchAdjustLoad.review")}
            </button>
          </div>
        </form>}
      </div>
    </Modal>
  );
}
