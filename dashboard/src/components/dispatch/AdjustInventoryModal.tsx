import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Modal } from "@/components/ui/modal";
import { apiErrorMessage } from "@/lib/apiErrors";
import { addQuantity, subtractQuantity, compareQuantity } from "@/lib/quantity";
import { formatLocaleDecimal } from "@/lib/localeNumbers";
import { currentLocale } from "@/i18n";
import type { PendingRoute } from "@/types/dispatch";
import { adjustmentReview, buildAdjustmentPayload, parseAdjustmentDraft, type AdjustLoadItem } from "@/features/dispatch/adjustLoad";
import { formatRouteLoadQuantity } from "@/features/dispatch/routeLoadUom";
import { ProductSearchControls } from "./ProductSearchControls";
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
  const command = useAdjustLoadCommand(isOpen ? route?.id : undefined, companyId, principalId);
  const [draftDeltas, setDeltas] = useState<Record<string, string>>({});
  const [draftScope, setDraftScope] = useState<string | null>(null);
  const [draftError, setDraftError] = useState(false);
  const loadContext = JSON.stringify([route?.id, route?.vehicleId, route?.sourceWarehouseId]);
  const contextScope = command.scope ? `${command.scope}:${loadContext}` : null;
  const deltas = draftScope === contextScope ? draftDeltas : {};
  const [search, setSearch] = useLoadProductSearchText(JSON.stringify([isOpen, contextScope]));
  const [step, setStep] = useState<"edit" | "review">("edit");
  const products = useAdjustLoadProducts(isOpen ? route?.id : undefined, step === "edit" ? search : "", deltas, command.scope, loadContext, step === "edit");
  const { items: inventory, loading } = products;

  useEffect(() => {
    setStep("edit");
  }, [isOpen, loadContext]);

  useEffect(() => {
    setDraftScope(null); setDraftError(false);
    if (!isOpen || !command.scope) return;
    try {
      const storedContext = localStorage.getItem(`${command.scope}:draft-context`);
      const rawDraft = storedContext && storedContext !== loadContext ? null : localStorage.getItem(`${command.scope}:draft`);
      setDeltas(Object.fromEntries(Object.entries(parseAdjustmentDraft(rawDraft))
        .filter(([, value]) => hasAdjustmentDraft(value))));
      setDraftScope(contextScope);
    } catch { setDraftError(true); }
  }, [isOpen, command.scope, contextScope, loadContext]);
  useEffect(() => {
    if (isOpen && command.scope && draftScope === contextScope && !draftError) {
      localStorage.setItem(`${command.scope}:draft`, JSON.stringify(draftDeltas));
      localStorage.setItem(`${command.scope}:draft-context`, loadContext);
    }
  }, [command.scope, contextScope, loadContext, draftDeltas, draftError, draftScope, isOpen]);

  const blocked = !command.scope || !command.ready || loading || command.busy ||
    command.recoveryRequired || !!command.recoveryError || draftError || !!products.error;
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
      if (command.scope) localStorage.removeItem(`${command.scope}:draft`);
      setDeltas({});
      toast.success(t(mode === "HANDSHAKE" ? "dispatchAdjustLoad.handshake" : "dispatchAdjustLoad.saved"));
      await onSuccess();
      onClose();
    } catch (error) { toast.error(apiErrorMessage(error, t("dispatchAdjustLoad.saveError"))); }
  };
  const rows = inventory.filter((item) => step === "review"
    ? compareQuantity(deltas[item.product_id] || "0", "0") !== 0
    : true);
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
    <Modal isOpen={isOpen} onClose={() => { if (!command.busy) onClose(); }}
      title={t(step === "edit" ? "dispatchAdjustLoad.title" : "dispatchAdjustLoad.reviewTitle")}>
      <div dir={i18n.dir()} className="space-y-4">
        {!command.online && <p role="status">{t("dispatchAdjustLoad.offline")}</p>}
        {(command.recoveryError || draftError) && <p role="alert">{t("dispatchAdjustLoad.unknown")}</p>}
        {command.busy && !command.recoveryRequired && <p role="status">{t("dispatchAdjustLoad.saving")}</p>}
        {command.recoveryRequired ? <div role="alert" className="space-y-3">
          <p>{t("dispatchAdjustLoad.unknown")}</p>
          <button type="button" onClick={() => void save(true)}
            disabled={command.busy || !command.online || !!command.recoveryError}>{t("common.retry")}</button>
        </div> : <form onSubmit={(event) => {
          event.preventDefault();
          if (blocked) return;
          if (step === "edit") review(); else void save();
        }} className="space-y-4">
          {step === "edit" && <ProductSearchControls search={search} onChange={setSearch} page={products.page} />}
          {loading && <p role="status">{t("common.loading")}</p>}
          {!!products.error && <div role="alert"><p>{apiErrorMessage(products.error, t("dispatchAdjustLoad.loadError"))}</p>
            <button type="button" onClick={products.retry}>{t("common.retry")}</button></div>}
          {!loading && !products.error && !inventory.length && <p role="status">{t("dispatchAdjustLoad.loadedEmpty")}</p>}
          <div className="max-h-[50vh] space-y-3 overflow-auto">{rows.map(renderRow)}</div>
          {route?.sessionBound && <p>{t("dispatchAdjustLoad.handshake")}</p>}
          <div className="flex gap-3 border-t pt-4">
            <button type="button" disabled={command.busy} onClick={() => step === "review" ? setStep("edit") : onClose()}>
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
