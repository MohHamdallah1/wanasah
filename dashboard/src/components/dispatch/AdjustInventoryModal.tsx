import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorMessage } from "@/lib/apiErrors";
import { addQuantity, subtractQuantity, compareQuantity } from "@/lib/quantity";
import { formatLocaleDecimal } from "@/lib/localeNumbers";
import { currentLocale } from "@/i18n";
import type { PendingRoute } from "@/types/dispatch";
import { adjustmentReview, buildAdjustmentPayload, parseAdjustLoadInventory, parseAdjustmentDraft, type AdjustLoadItem } from "@/features/dispatch/adjustLoad";
import { formatRouteLoadQuantity } from "@/features/dispatch/routeLoadUom";
import { useAdjustLoadCommand } from "@/features/dispatch/useAdjustLoadCommand";

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
  const authenticatedFetch = useAuthFetch();
  const command = useAdjustLoadCommand(isOpen ? route?.id : undefined, companyId, principalId);
  const [inventory, setInventory] = useState<AdjustLoadItem[]>([]);
  const [deltas, setDeltas] = useState<Record<string, string>>({});
  const [draftScope, setDraftScope] = useState<string | null>(null);
  const [draftError, setDraftError] = useState(false);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<"edit" | "review">("edit");

  useEffect(() => {
    if (!isOpen || !route?.id) return;
    const controller = new AbortController();
    setLoading(true); setInventory([]); setStep("edit"); setSearch("");
    void authenticatedFetch(`/dispatch/route/${route.id}/live_inventory`, { signal: controller.signal })
      .then((data) => {
        if (controller.signal.aborted) return;
        try { setInventory(parseAdjustLoadInventory(data)); }
        catch { throw Object.assign(new Error(), { code: "DISPATCH_ADJUSTMENT_INVALID" }); }
      }).catch((error) => {
        if (!controller.signal.aborted) toast.error(apiErrorMessage(error, t("dispatchAdjustLoad.loadError")));
      }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [authenticatedFetch, isOpen, route?.id, t]);

  useEffect(() => {
    setDraftScope(null); setDraftError(false);
    if (!isOpen || !command.scope) return;
    try {
      setDeltas(parseAdjustmentDraft(localStorage.getItem(`${command.scope}:draft`)));
      setDraftScope(command.scope);
    } catch { setDraftError(true); }
  }, [isOpen, command.scope]);
  useEffect(() => {
    if (isOpen && command.scope && draftScope === command.scope && !draftError) {
      localStorage.setItem(`${command.scope}:draft`, JSON.stringify(deltas));
    }
  }, [command.scope, deltas, draftError, draftScope, isOpen]);

  const blocked = !command.scope || !command.ready || loading || command.busy ||
    !!command.pending || !!command.recoveryError || draftError;
  const update = (id: string, value: string) => {
    if (blocked) return;
    setDeltas((current) => ({ ...current, [id]: value }));
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
    : item.product_name.toLocaleLowerCase(i18n.language).includes(search.toLocaleLowerCase(i18n.language)));
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
        {command.pending ? <div role="alert" className="space-y-3">
          <p>{t("dispatchAdjustLoad.unknown")}</p>
          <button type="button" onClick={() => void save(true)}
            disabled={command.busy || !command.online || !!command.recoveryError}>{t("common.retry")}</button>
        </div> : <form onSubmit={(event) => {
          event.preventDefault();
          if (blocked) return;
          if (step === "edit") review(); else void save();
        }} className="space-y-4">
          {step === "edit" && <input aria-label={t("dispatchAdjustLoad.search")} placeholder={t("dispatchAdjustLoad.search")}
            value={search} onChange={(event) => setSearch(event.target.value)} className="w-full rounded border p-2" />}
          {loading ? <p role="status">{t("common.loading")}</p> : <div className="max-h-[50vh] space-y-3 overflow-auto">{rows.map(renderRow)}</div>}
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
