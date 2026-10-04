import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import { resolveI18nLocale } from "@/lib/locale";
import { parseVariants, type CatalogVariant } from "@/features/catalog/contracts";
import type { InventoryOwnerFocusIntent } from "@/features/inventory/navigation";
import { ProductLocationManager } from "@/features/inventory/productLocations/ProductLocationManager";
import { TabTransfers } from "../TabTransfers";
import { Tab3Stocktake } from "../Tab3Stocktake";
import { TabBatches } from "../TabBatches";
import type { BatchSpecialTransferResult } from "../batches/batchSpecialTransferContract";
import type { ReservationOwner } from "../batches/batchStockSourcesContract";

const permissions = { batch: "inventory.read", transfer: "transfer.read", stocktake: "stocktake.read", "product-location": "product_location.read" } as const;

/** Inventory owns this entry. IDs are hints; existing owner reads/commands remain authoritative. */
export function ArchiveOwnerWorkspace({ intent, onClose, onOpenTransfers, onOpenReservationOwner, onInventoryChanged }: {
  intent: InventoryOwnerFocusIntent;
  onClose: () => void;
  onOpenTransfers: (result?: BatchSpecialTransferResult) => void | Promise<void>;
  onOpenReservationOwner: (owner: ReservationOwner) => void;
  onInventoryChanged: () => void | Promise<void>;
}) {
  const { t, i18n } = useTranslation();
  const authFetch = useAuthFetch();
  const access = useInventoryAccess(intent.locationId);
  const [variant, setVariant] = useState<CatalogVariant | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [consumed, setConsumed] = useState(false);
  const consume = useCallback(() => setConsumed(true), []);
  const focusUnavailable = useCallback((failure: unknown) => setError(apiErrorMessage(failure, t("archiveOwners.inaccessible"))), [t]);
  const allowed = access.isSuccess && access.can(permissions[intent.flow]);
  const needsVariant = intent.flow === "batch" || intent.flow === "product-location";
  useEffect(() => {
    if (!allowed || !needsVariant) return;
    const controller = new AbortController();
    void authFetch("/catalog/variants/resolve", { method: "POST", body: JSON.stringify({ ids: [intent.variantId] }), signal: controller.signal })
      .then((raw) => {
        if (controller.signal.aborted) return;
        const resolved = parseVariants(raw).items.find((item) => item.id === intent.variantId);
        if (!resolved) throw new Error(t("archiveOwners.inaccessible"));
        setVariant(resolved);
      }).catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(apiErrorMessage(failure, t("archiveOwners.inaccessible")));
      });
    return () => controller.abort();
  }, [allowed, authFetch, intent.variantId, needsVariant, t]);
  const number = new Intl.NumberFormat(resolveI18nLocale(i18n));
  const ready = allowed && (!needsVariant || variant !== null);
  return <section className="flex min-h-0 flex-1 flex-col gap-4" dir={i18n.dir()}>
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
      <h2 className="font-bold">{t("archiveOwners.focusTitle")}</h2>
      <p className="text-sm">{t("archiveOwners.focusIdentity", { location: number.format(intent.locationId), operation: number.format(intent.operationId) })}</p>
      {intent.flow === "product-location" && <p className="mt-2 text-sm">{t("archiveOwners.historyGuard")}</p>}
      <button type="button" onClick={onClose} className="mt-3 rounded-lg border px-3 py-2 focus-visible:ring-2">{t("archiveOwners.back")}</button>
    </div>
    {(error || access.isError || (access.isSuccess && !allowed)) ? <p role="alert">{error ?? t("archiveOwners.inaccessible")}</p> : !ready ? <p role="status">{t("archiveOwners.loading")}</p> : <>
      {intent.flow === "transfer" && <TabTransfers locationId={intent.locationId} focus={consumed ? null : { headerId: intent.operationId, reference: intent.reference }} onFocusConsumed={consume} onInventoryChanged={onInventoryChanged} />}
      {/* This focused entry resumes a session; it does not offer creation of a different stocktake. */}
      {intent.flow === "stocktake" && access.data && <Tab3Stocktake locationId={intent.locationId} companyId={`${access.data.company_id}:${access.data.driver_id}`} focusSessionId={intent.operationId} onFocusUnavailable={focusUnavailable} isAuditLocked authenticatedFetch={authFetch} onStocktakeChanged={onInventoryChanged} />}
      {intent.flow === "product-location" && variant && <ProductLocationManager variant={variant} locations={[]} focusLocationId={intent.locationId} focusAssignmentId={intent.operationId} />}
      {intent.flow === "batch" && variant && <TabBatches locationId={intent.locationId} focus={consumed ? null : { version: 1, kind: "batch-focus", tab: "batches", variantId: variant.id, batchId: intent.operationId, productName: variant.name, locationId: intent.locationId }} onFocusConsumed={consume}
        onOpenTransfers={async (result) => { await onOpenTransfers(result); onClose(); }}
        onOpenReservationOwner={onOpenReservationOwner} />}
    </>}
  </section>;
}
