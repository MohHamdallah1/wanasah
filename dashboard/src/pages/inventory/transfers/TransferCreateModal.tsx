import { Link } from "react-router-dom";
import { Modal } from "@/components/ui/modal";
import { createInventoryTabNavigationState } from "@/features/inventory/navigation";
import { apiErrorRequestId, apiErrorStatus } from "@/lib/apiErrors";
import { useTransferTranslation, formatTransferNumber } from "./i18n";
import type { TransferCreateController } from "./hooks/useTransferCreate";
import { compareQuantity } from "../quantity";
import { totalDraftQuantity, getErrorMessage } from "./utils";
import { FefoOverrideEditor } from "./FefoOverrideEditor";

interface TransferCreateModalProps { locationId: number; controller: TransferCreateController }
export function TransferCreateModal({ controller: c }: TransferCreateModalProps) {
  const { t, i18n } = useTransferTranslation();
  const error = c.sources.error || c.destinations.error || c.sourceProductsError || c.restoreError;
  const unavailable = apiErrorStatus(error) === 403 || apiErrorStatus(error) === 404 ||
    (!!c.source && !c.sources.loading && !c.sources.valid) || (!!c.destination && !c.destinations.loading && !c.destinations.valid);
  const requestId = apiErrorRequestId(error);
  return <Modal isOpen={c.createOpen} onClose={c.closeCreate} title={t("inventoryTransfers.createTitle")} maxWidth="max-w-6xl">
    <div dir={i18n.dir()}>
      {(c.command.pending && !c.command.busy) || c.command.recoveryError ? <div role="alert" className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
        <p>{t("inventoryTransfers.pending")}</p>
        <button type="button" disabled={c.command.busy || !!c.command.recoveryError} onClick={() => void c.retryPendingDispatch()}>{t("inventoryTransfers.retry")}</button>
      </div> : <form className="space-y-4" data-cp13-create-flow="transfer" onSubmit={(event) => { event.preventDefault(); void c.handleDispatchTransfer(); }}>
        {c.policyBlocked && <Link to="/inventory" state={createInventoryTabNavigationState("warehouses")}>{t("inventoryTransfers.policySetup")}</Link>}
        <fieldset disabled={c.createSubmitting} className="space-y-4 min-w-0">
          <div className="grid gap-3 md:grid-cols-2">
            {(["source", "destination"] as const).map((purpose) => {
              const query = purpose === "source" ? c.sources : c.destinations;
              const selected = purpose === "source" ? c.source : c.destination;
              const other = purpose === "source" ? c.destination : c.source;
              return <label key={purpose} className="block space-y-1 text-sm font-bold">
                <span>{t(`inventoryTransfers.${purpose}Warehouse`)}</span>
                <input type="search" aria-label={t(`inventoryTransfers.${purpose}Search`)} value={query.search} onChange={(event) => query.setSearch(event.target.value)} maxLength={100} className="w-full rounded-lg border p-2" />
                <select aria-label={t(`inventoryTransfers.${purpose}Warehouse`)} value={selected?.id ?? ""} disabled={query.loading}
                  onChange={(event) => (purpose === "source" ? c.updateSource : c.updateDestination)(event.target.value)} className="w-full rounded-lg border p-2">
                  <option value="">{t("inventoryTransfers.chooseLocation")}</option>
                  {query.items.filter((item) => item.id !== other?.id).map((item) => <option key={item.id} value={item.id}>{item.name} ({item.code})</option>)}
                </select>
                {query.loading && <span role="status">{t("inventoryTransfers.loading")}</span>}
              </label>;
            })}
          </div>
          {unavailable ? <p role="alert">{t("inventoryTransfers.warehouseUnavailable")}{requestId && ` (${requestId})`}</p>
            : !!error && <p role="alert">{getErrorMessage(error, t("inventoryTransfers.sourceFailure"))}</p>}
          {!!error && <button type="button" onClick={() => { c.sources.retry(); c.destinations.retry(); c.retryProducts(); c.retryRestore(); }}>{t("inventoryTransfers.retry")}</button>}
          <section className="space-y-2 rounded-xl border p-3">
            <h3 className="font-bold">{t("inventoryTransfers.products")}</h3>
            <p className="text-xs text-slate-500">{t("inventoryTransfers.sourceHint")}</p>
            <input type="search" aria-label={t("inventoryTransfers.productSearch")} value={c.productSearchInput} onChange={(event) => c.setProductSearchInput(event.target.value)} maxLength={100} disabled={!c.ready} className="w-full rounded-lg border p-2" />
            {(c.sourceProductsLoading || c.restoring) && <p role="status">{t("inventoryTransfers.sourceLoading")}</p>}
            <div className="max-h-96 overflow-auto"><table className="w-full text-sm">
              <thead><tr><th>{t("inventoryTransfers.products")}</th><th>{t("inventoryTransfers.availableTransfer")}</th><th>{t("inventoryTransfers.baseUom")}</th><th>{t("inventoryTransfers.quantity")}</th></tr></thead>
              <tbody>{c.products.map((product) => {
                const lines = c.draftItems.filter((item) => item.id === product.id);
                const invalid = lines.some((item) => { try { return compareQuantity(totalDraftQuantity(item), product.available_quantity) > 0; } catch { return item.quantity !== "0"; } });
                return <tr key={product.id} data-product-id={product.id} className="border-t align-top">
                  <td className="p-2"><strong>{product.name}</strong><p className="text-xs text-slate-500">{product.sku}</p></td>
                  <td className="p-2">{formatTransferNumber(product.available_quantity)}</td><td className="p-2">{t(`uom.${product.base_uom_code}`, { defaultValue: product.base_uom_name })}</td>
                  <td className="p-2 space-y-2">
                    {(!lines.length || lines.every((line) => line.fefo_mode === "auto")) && <div className="flex gap-2">
                      <input aria-label={t("inventoryTransfers.productQuantity", { name: product.name })} aria-invalid={invalid} inputMode="decimal" value={lines[0]?.quantity ?? ""} disabled={!c.ready || c.restoring}
                        onChange={(event) => c.updateProductQuantity(product, event.target.value)} className="w-28 rounded border p-2" />
                      <button type="button" disabled={!c.ready || c.restoring} onClick={() => c.updateProductQuantity(product, product.available_quantity)}>{t("inventoryTransfers.all")}</button>
                    </div>}
                    {invalid && <p role="alert">{t("inventoryTransfers.quantityExceeds", { name: product.name })}</p>}
                    {c.canOverride && lines.length > 0 && <details><summary>{t("inventoryTransfers.advancedFefo")}</summary>
                      {lines.map((item) => <div key={item.draft_key} className="my-2 rounded border p-2">
                        <FefoOverrideEditor canOverride={c.canOverride} item={item} draftItems={c.draftItems} options={c.overrideOptionsByProduct[item.id]} loading={c.overrideLoadingProductIds.includes(item.id)}
                          onModeChange={c.setDraftFefoMode} onBatchChange={c.setOverrideBatch} onReasonChange={c.setOverrideReason} onAddBatchLine={c.addOverrideBatchLine} />
                        {item.fefo_mode === "override" && <label>{t("inventoryTransfers.quantity")}<input aria-label={t("inventoryTransfers.productQuantity", { name: product.name })} value={item.quantity} inputMode="decimal" onChange={(event) => c.updateDraftQuantity(item.draft_key, event.target.value)} className="w-28 rounded border p-2" /></label>}
                        <button type="button" onClick={() => c.removeDraftLine(item.draft_key)}>{t("inventoryTransfers.remove")}</button>
                      </div>)}
                    </details>}
                  </td>
                </tr>;
              })}</tbody>
            </table></div>
            {c.ready && !c.sourceProductsLoading && !c.restoring && !c.products.length && <p>{t("inventoryTransfers.sourceEmpty")}</p>}
            {c.sourceProductsNextCursor && <button type="button" disabled={c.sourceProductsLoading} onClick={() => void c.loadMoreSourceProducts()}>{t("inventoryTransfers.more")}</button>}
          </section>
          <label className="block text-sm">{t("inventoryTransfers.notes")}<textarea aria-label={t("inventoryTransfers.notes")} value={c.createNotes} onChange={(event) => c.updateCreateNotes(event.target.value)} maxLength={4000} className="block w-full rounded-lg border p-2" /></label>
          <div className="flex justify-end"><button type="submit" disabled={!c.canSubmit} className="rounded-lg bg-blue-700 px-4 py-3 font-bold text-white disabled:opacity-40" data-cp13-action-priority="primary">
            {t(c.createSubmitting ? "inventoryTransfers.sending" : "inventoryTransfers.send")}
          </button></div>
        </fieldset>
      </form>}
    </div>
  </Modal>;
}
