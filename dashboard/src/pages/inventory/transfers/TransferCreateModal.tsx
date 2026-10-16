import { Link } from "react-router-dom";
import { createInventoryTabNavigationState } from "@/features/inventory/navigation";
import { Search, Trash2 } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { useTransferTranslation as useTranslation, formatTransferNumber } from "./i18n";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import type { TransferCreateController } from "./hooks/useTransferCreate";
import { compareQuantity } from "../quantity";
import { FefoOverrideEditor } from "./FefoOverrideEditor";

interface TransferCreateModalProps {
  locationId: number;
  controller: TransferCreateController;
}

export function TransferCreateModal({
  locationId,
  controller,
}: TransferCreateModalProps) {
  const { t } = useTranslation();
  const {
    canOutgoing, canIncoming, canSubmit, canOverride,
    createOpen,
    createDirection,
    transferLocations,
    transferLocationsLoading,
    transferLocationSearchInput,
    counterpartLocationId,
    createNotes,
    createSubmitting,
    productSearchInput,
    sourceProducts,
    sourceProductsLoading,
    sourceProductsLoadingMore,
    sourceProductsNextCursor,
    sourceLocationId,
    draftItems,
    overrideOptionsByProduct,
    overrideLoadingProductIds,
    closeCreate,
    setTransferLocationSearchInput,
    setProductSearchInput,
    updateCreateDirection,
    updateCounterpartLocation,
    updateCreateNotes,
    loadMoreSourceProducts,
    addDraftProduct,
    removeDraftLine,
    updateDraftQuantity,
    setDraftFefoMode,
    setOverrideBatch,
    setOverrideReason,
    addOverrideBatchLine,
    handleDispatchTransfer,
  } = controller;

  return (
    <Modal
      isOpen={createOpen}
      onClose={closeCreate}
      title={t("inventoryTransfers.createTitle")}
      maxWidth="max-w-6xl"
    >
      {controller.command.pending ? (
        <div role="alert" className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-900">
          <p>{t("inventoryTransfers.pending")}</p>
          <button type="button" disabled={controller.command.busy} onClick={() => void controller.retryPendingDispatch()} className="rounded-lg border border-amber-200 bg-white px-2.5 py-1.5 outline-none focus-visible:ring-2 focus-visible:ring-amber-300">
            {t("inventoryTransfers.retry")}
          </button>
        </div>
      ) : null}
      {controller.policyBlocked ? (
        <Link
          to="/inventory"
          state={createInventoryTabNavigationState("warehouses")}
          className="mb-3 block rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-black text-amber-900 underline outline-none focus-visible:ring-2 focus-visible:ring-amber-300"
        >
          {t("inventoryTransfers.policySetup")}
        </Link>
      ) : null}

      <form
        className="space-y-3"
        data-cp13-create-flow="transfer"
        onSubmit={(event) => {
          event.preventDefault();
          void handleDispatchTransfer();
        }}
      >
        <fieldset disabled={createSubmitting || Boolean(controller.command.pending) || controller.command.busy} className="min-w-0 space-y-3">
          <div className="grid grid-cols-1 gap-2 rounded-xl border border-slate-200 bg-slate-50/70 p-3 md:grid-cols-[minmax(160px,0.8fr)_minmax(220px,1fr)_minmax(220px,1fr)]">
            <label className="block text-xs font-bold text-slate-700">
              {t("inventoryTransfers.purpose")}
              <select
                aria-label={t("inventoryTransfers.purpose")}
                value={controller.transferPurpose}
                onChange={(event) => controller.setTransferPurpose(event.target.value as "REPLENISHMENT" | "WAREHOUSE_BALANCING")}
                className="mt-1 h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-bold outline-none focus-visible:ring-2 focus-visible:ring-blue-300"
                data-cp13-transfer-purpose="required"
              >
                <option value="WAREHOUSE_BALANCING">{t("inventoryTransfers.WAREHOUSE_BALANCING")}</option>
                <option value="REPLENISHMENT">{t("inventoryTransfers.REPLENISHMENT")}</option>
              </select>
            </label>

            <div>
              <label className="text-xs font-bold text-slate-700">{t("inventoryTransfers.direction")}</label>
              <select
                aria-label={t("inventoryTransfers.direction")}
                value={createDirection}
                onChange={(event) => updateCreateDirection(event.target.value)}
                className="mt-1 h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-bold outline-none focus-visible:ring-2 focus-visible:ring-blue-300"
              >
                <option value="outgoing" disabled={!canOutgoing}>{t("inventoryTransfers.outgoingSelected")}</option>
                <option value="incoming" disabled={!canIncoming}>{t("inventoryTransfers.incomingSelected")}</option>
              </select>
            </div>

            <div className="min-w-0">
              <label className="text-xs font-bold text-slate-700">
                {createDirection === "outgoing" ? t("inventoryTransfers.destination") : t("inventoryTransfers.source")}
              </label>
              <div className="mt-1 grid grid-cols-1 gap-1.5 sm:grid-cols-2 md:grid-cols-1 xl:grid-cols-2">
                <input
                  aria-label={t("inventoryTransfers.locationSearch")}
                  value={transferLocationSearchInput}
                  onChange={(event) => setTransferLocationSearchInput(event.target.value)}
                  placeholder={t("inventoryTransfers.locationSearch")}
                  maxLength={100}
                  className="h-9 min-w-0 rounded-lg border border-slate-200 bg-white px-2.5 text-xs outline-none focus-visible:ring-2 focus-visible:ring-blue-300"
                />
                <select
                  aria-label={t(createDirection === "outgoing" ? "inventoryTransfers.destination" : "inventoryTransfers.source")}
                  value={counterpartLocationId ?? ""}
                  disabled={transferLocationsLoading}
                  onChange={(event) => updateCounterpartLocation(event.target.value)}
                  className="h-9 min-w-0 rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-bold outline-none disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-blue-300"
                >
                  <option value="" disabled>{t("inventoryTransfers.chooseLocation")}</option>
                  {transferLocations
                    .filter((item) => item.id !== locationId)
                    .map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.location_type === "WAREHOUSE"
                          ? t("inventoryTransfers.warehouse")
                          : t("inventoryTransfers.vehicle")} — {item.name} ({item.code})
                      </option>
                    ))}
                </select>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-blue-100 bg-blue-50/60 px-3 py-2 text-[11px] font-bold text-blue-950" data-cp13-route-context="true">
            <span>{t("inventoryTransfers.selectedLocation")}: #{formatTransferNumber(locationId)}</span>
            <span>{createDirection === "outgoing" ? t("inventoryTransfers.source") : t("inventoryTransfers.destination")}</span>
            <span>{t("inventoryTransfers.fefoHint")}</span>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <section className="min-w-0 rounded-xl border border-slate-200 bg-white p-3">
              <div className="flex items-end justify-between gap-2">
                <div>
                  <h3 className="text-sm font-black text-slate-900">{t("inventoryTransfers.sourceInventory")}</h3>
                  <p className="mt-0.5 text-[11px] text-slate-500">{t("inventoryTransfers.sourceHint")}</p>
                </div>
              </div>

              <div className="relative mt-2">
                <Search className="pointer-events-none absolute start-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" aria-hidden="true" />
                <input
                  type="search"
                  aria-label={t("inventoryTransfers.productSearch")}
                  value={productSearchInput}
                  onChange={(event) => setProductSearchInput(event.target.value)}
                  placeholder={t("inventoryTransfers.productSearch")}
                  maxLength={100}
                  className="h-9 w-full rounded-lg border border-slate-200 bg-white ps-9 pe-3 text-xs outline-none focus-visible:ring-2 focus-visible:ring-blue-300"
                />
              </div>

              <div className="mt-2 max-h-72 overflow-auto rounded-lg border border-slate-100 divide-y divide-slate-100">
                {sourceProducts.map((product) => {
                  const added = draftItems.some((item) => item.id === product.id);
                  return (
                    <button
                      key={product.id}
                      type="button"
                      disabled={added}
                      onClick={() => addDraftProduct(product)}
                      className="w-full px-3 py-2 text-start outline-none hover:bg-slate-50 disabled:opacity-40 focus-visible:bg-blue-50"
                    >
                      <div className="truncate text-xs font-black text-slate-800">{product.name}</div>
                      <div className="mt-0.5 truncate text-[10px] text-slate-500">
                        {product.sku || "—"} · {t("inventoryTransfers.available")}: {formatTransferNumber(product.available_quantity)} {product.base_uom_name}
                      </div>
                    </button>
                  );
                })}

                {sourceProductsNextCursor ? (
                  <div className="border-t border-slate-100 p-2">
                    <button
                      type="button"
                      onClick={loadMoreSourceProducts}
                      disabled={sourceProductsLoading || sourceProductsLoadingMore}
                      className="w-full rounded-lg border border-blue-200 bg-blue-50 py-2 text-xs font-bold text-blue-700 outline-none hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-blue-300"
                    >
                      {sourceProductsLoadingMore ? t("inventoryTransfers.moreLoading") : t("inventoryTransfers.more")}
                    </button>
                  </div>
                ) : null}

                {!sourceProductsLoading && sourceLocationId !== null && sourceProducts.length === 0 ? (
                  <div className="p-6 text-center text-sm text-slate-400">{t("inventoryTransfers.sourceEmpty")}</div>
                ) : null}

                {sourceProductsLoading ? (
                  <div className="p-6 text-center text-sm text-slate-400" role="status">{t("inventoryTransfers.sourceLoading")}</div>
                ) : null}
              </div>
            </section>

            <section className="min-w-0 rounded-xl border border-slate-200 bg-white p-3">
              <div>
                <h3 className="text-sm font-black text-slate-900">{t("inventoryTransfers.draftItems")}</h3>
                <p className="mt-0.5 text-[11px] font-semibold text-slate-500">{t("inventoryTransfers.fefoHint")}</p>
              </div>

              <div className="mt-2 max-h-72 space-y-2 overflow-auto">
                {draftItems.map((item) => {
                  const options = overrideOptionsByProduct[item.product_variant_id];
                  const overrideLoading = overrideLoadingProductIds.includes(item.product_variant_id);
                  const selectedBatch = item.override_batch_id !== null
                    ? options?.batches.find((batch) => batch.id === item.override_batch_id) ?? null
                    : null;
                  const availableLimit = item.fefo_mode === "override"
                    ? selectedBatch?.available_quantity ?? "0"
                    : item.available_quantity;
                  let invalid = false;
                  try {
                    invalid = compareQuantity(item.quantity || "0", availableLimit) > 0;
                  } catch {
                    invalid = Boolean(item.quantity);
                  }

                  return (
                    <article
                      key={item.draft_key}
                      className={`rounded-xl border p-2.5 ${
                        invalid
                          ? "border-red-300 bg-red-50"
                          : item.fefo_mode === "override"
                            ? "border-amber-300 bg-amber-50/30"
                            : "border-slate-200"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-xs font-black text-slate-800">{item.name}</div>
                          <div className="mt-0.5 text-[10px] text-slate-500">
                            {t("inventoryTransfers.sourceAvailable")}: {formatTransferNumber(item.available_quantity)} {item.base_uom_name}
                          </div>
                        </div>

                        <button
                          type="button"
                          onClick={() => removeDraftLine(item.draft_key)}
                          aria-label={t("inventoryTransfers.remove")}
                          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-red-600 outline-none hover:bg-red-50 focus-visible:ring-2 focus-visible:ring-red-300"
                        >
                          <Trash2 className="h-4 w-4" aria-hidden="true" />
                        </button>
                      </div>

                      <FefoOverrideEditor
                        canOverride={canOverride}
                        item={item}
                        draftItems={draftItems}
                        options={options}
                        loading={overrideLoading}
                        onModeChange={setDraftFefoMode}
                        onBatchChange={setOverrideBatch}
                        onReasonChange={setOverrideReason}
                        onAddBatchLine={addOverrideBatchLine}
                      />

                      <div className="mt-2">
                        <label className="text-[10px] font-bold text-slate-500">
                          {t("inventoryTransfers.quantityLabel", { unit: item.base_uom_name })}
                        </label>
                        <input
                          aria-label={t("inventoryTransfers.quantityLabel", { unit: item.base_uom_name })}
                          inputMode="decimal"
                          value={item.quantity}
                          onChange={(event) => updateDraftQuantity(item.draft_key, event.target.value)}
                          className="mt-1 h-9 w-full rounded-lg border border-slate-200 px-2 text-center text-xs font-black outline-none focus-visible:ring-2 focus-visible:ring-blue-300"
                        />
                        <p className="mt-1 text-[10px] text-slate-400">
                          {t("inventoryTransfers.precision", { scale: formatTransferNumber(item.quantity_scale), step: formatTransferNumber(item.quantity_step) })}
                        </p>
                      </div>

                      <div className={`mt-1.5 text-[10px] font-bold ${invalid ? "text-red-600" : "text-slate-500"}`}>
                        {t("inventoryTransfers.total")}: {formatTransferNumber(item.quantity || "0")} {item.base_uom_name}
                        {item.fefo_mode === "override" && selectedBatch
                          ? t("inventoryTransfers.fromBatch", { batch: formatPublicBatchNumber(selectedBatch.batch_number, t("inventoryLive.noLotSupplied")) })
                          : ""}
                        {invalid ? t("inventoryTransfers.exceeds") : ""}
                      </div>
                    </article>
                  );
                })}

                {draftItems.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-slate-200 p-6 text-center text-sm text-slate-400">{t("inventoryTransfers.addItems")}</div>
                ) : null}
              </div>
            </section>
          </div>

          <label className="block text-xs font-bold text-slate-600">
            {t("inventoryTransfers.notes")}
            <textarea
              aria-label={t("inventoryTransfers.notes")}
              value={createNotes}
              onChange={(event) => updateCreateNotes(event.target.value)}
              maxLength={4000}
              className="mt-1 min-h-20 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-blue-300"
            />
          </label>

          <div className="flex justify-end border-t border-slate-100 pt-3">
            <button
              type="submit"
              disabled={
                !canSubmit || createSubmitting ||
                transferLocationsLoading ||
                counterpartLocationId === null ||
                draftItems.length === 0
              }
              className="inline-flex min-h-10 min-w-40 items-center justify-center rounded-lg bg-blue-700 px-4 text-xs font-black text-white outline-none disabled:cursor-not-allowed disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-blue-300"
              data-cp13-action-priority="primary"
            >
              {createSubmitting ? t("inventoryTransfers.sending") : t("inventoryTransfers.send")}
            </button>
          </div>
        </fieldset>
      </form>
    </Modal>
  );
}
