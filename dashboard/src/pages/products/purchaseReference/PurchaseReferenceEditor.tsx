import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Modal } from "@/components/ui/modal";
import { apiErrorCode, apiErrorMessage } from "@/lib/apiErrors";
import {
  completeDurableOperation, durableScope, getOrCreateDurableCommand,
  readDurableCommand, type DurableCommand,
} from "@/lib/durableOperations";
import type { SimpleProduct } from "../contracts";
import {
  parsePurchaseReference, validateReferenceCommand,
  type PurchaseReference, type PurchaseReferenceCommand,
} from "./contracts";

type Props = {
  product: SimpleProduct | null;
  companyId: number | null;
  actorId: number | null;
  online: boolean;
  authenticatedFetch: (url: string, options?: RequestInit) => Promise<unknown>;
  onClose: () => void;
};

export function PurchaseReferenceEditor({
  product, companyId, actorId, online, authenticatedFetch, onClose,
}: Props) {
  const { t } = useTranslation();
  const [reference, setReference] = useState<PurchaseReference | null>(null);
  const [amount, setAmount] = useState("");
  const [uomId, setUomId] = useState(0);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] =
    useState<DurableCommand<PurchaseReferenceCommand> | null>(null);

  const scope = product && companyId && actorId
    ? durableScope(companyId, actorId, "purchase-cost-reference", product.id)
    : null;

  useEffect(() => {
    if (!product || !scope) return;
    let active = true;
    setLoading(true);
    setError("");
    setReference(null);
    setPending(null);
    setAmount("");
    setUomId(product.base_uom_id);
    void (async () => {
      try {
        // A lost HTTP response must be reconciled with the ORIGINAL command.
        const frozen = await readDurableCommand<PurchaseReferenceCommand>(scope);
        if (frozen) {
          // Recovery cannot depend on a second GET succeeding first.
          if (!active) return;
          setPending(frozen);
          setAmount(frozen.payload.amount);
          setUomId(frozen.payload.purchase_uom_id);
          return;
        }
        const result = parsePurchaseReference(
          await authenticatedFetch("/purchase-cost-references/" + product.id),
        );
        if (!active) return;
        setReference(result);
        setAmount(result?.amount ?? "");
        setUomId(result?.purchase_uom_id ?? product.base_uom_id);
      } catch (exception) {
        if (active) setError(
          apiErrorMessage(exception, t("products.purchaseReference.loadFailed")),
        );
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [authenticatedFetch, product, scope, t]);

  const save = async () => {
    if (!product || !scope || !online || loading || saving || error) return;
    setSaving(true);
    try {
      const command = pending ?? await getOrCreateDurableCommand(
        scope,
        validateReferenceCommand(
          { amount, purchase_uom_id: uomId, currency_code: product.currency_code },
          reference?.revision ?? 0,
        ),
      );
      setPending(command);
      const result = await authenticatedFetch("/purchase-cost-references/" + product.id, {
        method: "PUT",
        body: JSON.stringify({ request_id: command.requestId, ...command.payload }),
      });
      if (!result || typeof result !== "object" ||
          !("reference" in result) || !(result as { reference?: unknown }).reference) {
        throw new Error("PURCHASE_REFERENCE_RESPONSE_INVALID");
      }
      completeDurableOperation(scope, command.requestId);
      setPending(null);
      toast.success(t("products.purchaseReference.saved"));
      onClose();
    } catch (exception) {
      if (apiErrorCode(exception) === "PURCHASE_REFERENCE_REVISION_CONFLICT") {
        // A confirmed revision rejection never committed: the backend checks
        // successful replay before the revision compare.
        const stale = await readDurableCommand<PurchaseReferenceCommand>(scope);
        if (stale) completeDurableOperation(scope, stale.requestId);
        setPending(null);
        setError(t("products.purchaseReference.conflict"));
      } else {
        toast.error(apiErrorMessage(exception, t("products.purchaseReference.saveFailed")));
      }
    } finally {
      setSaving(false);
    }
  };

  const options = product ? [
    { id: product.base_uom_id, label: product.base_uom_code },
    ...(product.package_uom_id && product.package_uom_code
      ? [{ id: product.package_uom_id, label: product.package_uom_code }]
      : []),
    ...(reference && reference.purchase_uom_id !== product.base_uom_id &&
      reference.purchase_uom_id !== product.package_uom_id
      ? [{ id: reference.purchase_uom_id, label: reference.purchase_uom_code }]
      : []),
  ] : [];

  return (
    <Modal
      isOpen={product !== null}
      onClose={() => { if (!saving) onClose(); }}
      title={t("products.purchaseReference.title")}
      subtitle={product?.name}
      maxWidth="max-w-lg"
      footer={
        <>
          <button type="button" onClick={onClose} disabled={saving} className="px-4 py-2 text-sm font-semibold">
            {t("common.cancel")}
          </button>
          <button type="button" onClick={() => void save()}
            disabled={loading || saving || !online || !!error || (!pending && !amount.trim())}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-bold text-white disabled:opacity-50">
            {pending ? t("products.purchaseReference.retry") : t("products.purchaseReference.save")}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-xs text-slate-600">{t("products.purchaseReference.help")}</p>
        {loading ? <p role="status">{t("common.loading")}</p> : null}
        {error ? <p role="alert" className="text-sm text-rose-700">{error}</p> : null}
        {pending ? (
          <p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
            {t("products.purchaseReference.pending")}
          </p>
        ) : null}
        <label className="block text-xs font-bold">
          {t("products.purchaseReference.amount")}
          <input type="text" inputMode="decimal" value={amount}
            onChange={(event) => setAmount(event.target.value.replace(/[^0-9.]/g, ""))}
            disabled={loading || saving || !!error || !!pending}
            aria-label={t("products.purchaseReference.amount")}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 tabular-nums" />
        </label>
        <label className="block text-xs font-bold">
          {t("products.purchaseReference.purchaseUnit")}
          <select value={uomId}
            onChange={(event) => setUomId(Number(event.target.value))}
            disabled={loading || saving || !!error || !!pending}
            aria-label={t("products.purchaseReference.purchaseUnit")}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2">
            {options.map((option) => <option key={option.id} value={option.id}>{t("uom." + option.label, { defaultValue: option.label })}</option>)}
          </select>
        </label>
        <p className="text-xs text-slate-500">{product?.currency_code} · {t("products.purchaseReference.revision")}: {reference?.revision ?? 0}</p>
      </div>
    </Modal>
  );
}
