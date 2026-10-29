import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Modal } from "@/components/ui/modal";
import { createInventoryTabNavigationState } from "@/features/inventory/navigation";
import { apiErrorRequestId, apiErrorStatus } from "@/lib/apiErrors";
import { useTransferTranslation, formatTransferNumber } from "./i18n";
import type { TransferCreateController } from "./hooks/useTransferCreate";
import type { TransferSourceInventoryItem } from "./types";
import { compareQuantity } from "../quantity";
import { totalDraftQuantity, getErrorMessage } from "./utils";
import { FefoOverrideEditor } from "./FefoOverrideEditor";
import { TransferWarehouseCombobox } from "./TransferWarehouseCombobox";

interface TransferCreateModalProps {
  controller: TransferCreateController;
}

function MeasuredProductBody({
  index,
  onMeasure,
  children,
}: {
  index: number;
  onMeasure: (index: number, height: number) => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLTableSectionElement>(null);
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    const measure = () => onMeasure(index, node.getBoundingClientRect().height);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [index, onMeasure]);
  return <tbody ref={ref} data-transfer-product-page={index}>{children}</tbody>;
}

export function TransferCreateModal({ controller: c }: TransferCreateModalProps) {
  const { t, i18n } = useTransferTranslation();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const productScrollRef = useRef<HTMLDivElement>(null);
  const error = c.sources.error || c.destinations.error || c.sourceProductsError || c.restoreError;
  const unavailable = apiErrorStatus(error) === 403 || apiErrorStatus(error) === 404 ||
    (!!c.source && !c.sources.loading && !c.sources.valid) ||
    (!!c.destination && !c.destinations.loading && !c.destinations.valid);
  const requestId = apiErrorRequestId(error);

  useEffect(() => {
    if (!c.createOpen) setConfirmOpen(false);
  }, [c.createOpen]);

  const selectedProducts = useMemo(
    () => [...new Map(c.draftItems.map((item) => [item.id, item])).values()],
    [c.draftItems],
  );
  const selectedIds = useMemo(
    () => new Set(selectedProducts.map((product) => product.id)),
    [selectedProducts],
  );

  const renderProductRow = (product: TransferSourceInventoryItem) => {
    const lines = c.draftItems.filter((item) => item.id === product.id);
    const invalid = lines.some((item) => {
      try {
        return compareQuantity(totalDraftQuantity(item), product.available_quantity) > 0;
      } catch {
        return item.quantity !== "0";
      }
    });
    return (
      <tr key={product.id} data-product-id={product.id} className="border-t border-slate-100 align-top hover:bg-slate-50/60">
        <td className="p-2.5">
          <strong className="block text-xs text-slate-900">{product.name}</strong>
          {product.sku ? <p className="mt-0.5 text-[10px] font-semibold text-slate-400">{product.sku}</p> : null}
        </td>
        <td className="p-2.5 text-center text-xs font-black text-slate-800">{formatTransferNumber(product.available_quantity)}</td>
        <td className="p-2.5 text-center text-xs font-bold text-slate-600">
          {t(`uom.${product.base_uom_code}`, { defaultValue: product.base_uom_name })}
        </td>
        <td className="p-2.5">
          {(!lines.length || lines.every((line) => line.fefo_mode === "auto")) ? (
            <div className="flex items-center gap-2">
              <input
                aria-label={t("inventoryTransfers.productQuantity", { name: product.name })}
                aria-invalid={invalid}
                inputMode="decimal"
                value={lines[0]?.quantity ?? ""}
                disabled={!c.ready || c.restoring}
                onChange={(event) => c.updateProductQuantity(product, event.target.value)}
                className="h-9 w-28 rounded-lg border border-slate-200 bg-white px-2 text-center text-xs font-black outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
              />
              <button
                type="button"
                disabled={!c.ready || c.restoring}
                onClick={() => c.updateProductQuantity(product, product.available_quantity)}
                className="h-9 rounded-lg border border-blue-200 bg-blue-50 px-3 text-[11px] font-black text-blue-700 hover:bg-blue-100 disabled:opacity-40"
              >
                {t("inventoryTransfers.all")}
              </button>
            </div>
          ) : null}
          {invalid ? <p role="alert" className="mt-1 text-[10px] font-bold text-red-600">{t("inventoryTransfers.quantityExceeds", { name: product.name })}</p> : null}
          {c.canOverride && lines.length > 0 ? (
            <details className="mt-2 rounded-lg border border-slate-100 bg-slate-50/60 p-2">
              <summary className="cursor-pointer text-[10px] font-black text-slate-600">{t("inventoryTransfers.advancedFefo")}</summary>
              {lines.map((item) => (
                <div key={item.draft_key} className="mt-2 rounded-lg border border-slate-200 bg-white p-2">
                  <FefoOverrideEditor
                    canOverride={c.canOverride}
                    item={item}
                    draftItems={c.draftItems}
                    options={c.overrideOptionsByProduct[item.id]}
                    loading={c.overrideLoadingProductIds.includes(item.id)}
                    onModeChange={c.setDraftFefoMode}
                    onBatchChange={c.setOverrideBatch}
                    onReasonChange={c.setOverrideReason}
                    onAddBatchLine={c.addOverrideBatchLine}
                  />
                  {item.fefo_mode === "override" ? (
                    <label className="mt-2 block text-[10px] font-bold">
                      {t("inventoryTransfers.quantity")}
                      <input
                        aria-label={t("inventoryTransfers.productQuantity", { name: product.name })}
                        value={item.quantity}
                        inputMode="decimal"
                        onChange={(event) => c.updateDraftQuantity(item.draft_key, event.target.value)}
                        className="ms-2 h-8 w-24 rounded border border-slate-200 px-2 text-center"
                      />
                    </label>
                  ) : null}
                  <button type="button" onClick={() => c.removeDraftLine(item.draft_key)} className="mt-2 text-[10px] font-black text-red-600">
                    {t("inventoryTransfers.remove")}
                  </button>
                </div>
              ))}
            </details>
          ) : null}
        </td>
      </tr>
    );
  };

  const handleProductScroll = () => {
    const node = productScrollRef.current;
    if (!node || c.sourceProductsLoading || c.sourceProductsLoadingMore) return;
    if (node.scrollTop < 450 && c.hasPreviousSourceProducts) c.loadPreviousSourceProducts();
    if (node.scrollHeight - node.scrollTop - node.clientHeight < 650 && c.hasMoreSourceProducts) c.loadMoreSourceProducts();
  };

  return (
    <Modal
      isOpen={c.createOpen}
      onClose={c.closeCreate}
      title={t(confirmOpen ? "inventoryTransfers.confirmTitle" : "inventoryTransfers.createTitle")}
      maxWidth={confirmOpen ? "max-w-xl" : "max-w-6xl"}
    >
      <div dir={i18n.dir()}>
        {(c.command.pending && !c.command.busy) || c.command.recoveryError ? (
          <div role="alert" className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
            <p>{t("inventoryTransfers.pending")}</p>
            <button type="button" disabled={c.command.busy || !!c.command.recoveryError} onClick={() => void c.retryPendingDispatch()}>
              {t("inventoryTransfers.retry")}
            </button>
          </div>
        ) : confirmOpen ? (
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              void c.handleDispatchTransfer();
            }}
          >
            <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-xs">
              <div className="grid gap-2 sm:grid-cols-2">
                <div><span className="font-bold text-slate-500">{t("inventoryTransfers.source")}:</span> <strong>{c.source?.name}</strong></div>
                <div><span className="font-bold text-slate-500">{t("inventoryTransfers.destination")}:</span> <strong>{c.destination?.name}</strong></div>
              </div>
              <p className="mt-2 font-bold text-slate-600">{t("inventoryTransfers.selectedItemsCount", { count: selectedProducts.length })}</p>
            </div>
            <label className="block text-xs font-black text-slate-700">
              {t("inventoryTransfers.notes")}
              <textarea
                aria-label={t("inventoryTransfers.notes")}
                value={c.createNotes}
                onChange={(event) => c.updateCreateNotes(event.target.value)}
                maxLength={4000}
                placeholder={t("inventoryTransfers.notesOptional")}
                className="mt-1 min-h-24 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
              />
            </label>
            <div className="flex items-center justify-end gap-2">
              <button type="button" disabled={c.createSubmitting} onClick={() => setConfirmOpen(false)} className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-xs font-black text-slate-700">
                {t("inventoryTransfers.back")}
              </button>
              <button type="submit" disabled={!c.canSubmit} className="h-9 rounded-lg bg-blue-700 px-4 text-xs font-black text-white disabled:opacity-40">
                {t(c.createSubmitting ? "inventoryTransfers.sending" : "inventoryTransfers.confirmSend")}
              </button>
            </div>
          </form>
        ) : (
          <form
            className="flex min-h-0 flex-col gap-3"
            data-cp13-create-flow="transfer"
            onSubmit={(event) => {
              event.preventDefault();
              if (c.canSubmit) setConfirmOpen(true);
            }}
          >
            {c.policyBlocked ? <Link to="/inventory" state={createInventoryTabNavigationState("warehouses")}>{t("inventoryTransfers.policySetup")}</Link> : null}

            <fieldset disabled={c.createSubmitting} className="contents">
              <div className="grid gap-3 md:grid-cols-2">
                <TransferWarehouseCombobox
                  label={t("inventoryTransfers.sourceWarehouse")}
                  selected={c.source}
                  options={c.sources.items.filter((item) => item.id !== c.destination?.id)}
                  search={c.sources.search}
                  loading={c.sources.loading}
                  error={c.sources.error}
                  placeholder={t("inventoryTransfers.chooseSourceWarehouse")}
                  emptyLabel={t("inventoryTransfers.noWarehouses")}
                  loadingLabel={t("inventoryTransfers.loading")}
                  retryLabel={t("inventoryTransfers.retry")}
                  clearLabel={t("inventoryTransfers.clearSelection")}
                  onSearchChange={c.sources.setSearch}
                  onSelect={c.updateSource}
                  onRetry={c.sources.retry}
                />
                <TransferWarehouseCombobox
                  label={t("inventoryTransfers.destinationWarehouse")}
                  selected={c.destination}
                  options={c.destinations.items.filter((item) => item.id !== c.source?.id)}
                  search={c.destinations.search}
                  loading={c.destinations.loading}
                  error={c.destinations.error}
                  placeholder={t("inventoryTransfers.chooseDestinationWarehouse")}
                  emptyLabel={t("inventoryTransfers.noWarehouses")}
                  loadingLabel={t("inventoryTransfers.loading")}
                  retryLabel={t("inventoryTransfers.retry")}
                  clearLabel={t("inventoryTransfers.clearSelection")}
                  onSearchChange={c.destinations.setSearch}
                  onSelect={c.updateDestination}
                  onRetry={c.destinations.retry}
                />
              </div>

              {unavailable ? (
                <p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-900">
                  {t("inventoryTransfers.warehouseUnavailable")}{requestId && ` (${requestId})`}
                </p>
              ) : error ? (
                <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-bold text-red-700">
                  {getErrorMessage(error, t("inventoryTransfers.sourceFailure"))}
                </p>
              ) : null}

              {error ? (
                <button type="button" onClick={() => { c.sources.retry(); c.destinations.retry(); c.retryProducts(); c.retryRestore(); }} className="self-start text-xs font-black text-blue-700 underline">
                  {t("inventoryTransfers.retry")}
                </button>
              ) : null}

              <section className="flex min-h-[320px] flex-1 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white">
                <div className="shrink-0 border-b border-slate-100 p-3">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-black text-slate-900">{t("inventoryTransfers.products")}</h3>
                      <p className="mt-0.5 text-[10px] font-semibold text-slate-500">{t("inventoryTransfers.sourceHint")}</p>
                    </div>
                    {selectedProducts.length ? (
                      <span className="rounded-full bg-blue-50 px-2.5 py-1 text-[10px] font-black text-blue-700">
                        {t("inventoryTransfers.selectedItemsCount", { count: selectedProducts.length })}
                      </span>
                    ) : null}
                  </div>
                  <input
                    type="search"
                    aria-label={t("inventoryTransfers.productSearch")}
                    value={c.productSearchInput}
                    onChange={(event) => c.setProductSearchInput(event.target.value)}
                    maxLength={100}
                    disabled={!c.ready}
                    placeholder={c.ready ? t("inventoryTransfers.productSearch") : t("inventoryTransfers.chooseWarehousesFirst")}
                    className="h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-xs font-bold outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50 disabled:text-slate-400"
                  />
                </div>

                {!c.ready ? (
                  <div className="flex min-h-56 flex-1 items-center justify-center px-4 text-center text-sm font-bold text-slate-400">
                    {t("inventoryTransfers.chooseWarehousesFirst")}
                  </div>
                ) : (
                  <div
                    ref={productScrollRef}
                    onScroll={handleProductScroll}
                    className="min-h-0 flex-1 overflow-auto"
                    data-transfer-product-scroll="true"
                  >
                    <table className="w-full min-w-[720px] text-sm" aria-busy={c.sourceProductsLoading || c.sourceProductsLoadingMore || c.restoring}>
                      <thead className="sticky top-0 z-10 border-b border-slate-200 bg-slate-50/95 backdrop-blur">
                        <tr>
                          <th className="p-2.5 text-start text-[11px] font-black text-slate-500">{t("inventoryTransfers.products")}</th>
                          <th className="p-2.5 text-center text-[11px] font-black text-slate-500">{t("inventoryTransfers.availableTransfer")}</th>
                          <th className="p-2.5 text-center text-[11px] font-black text-slate-500">{t("inventoryTransfers.baseUom")}</th>
                          <th className="p-2.5 text-start text-[11px] font-black text-slate-500">{t("inventoryTransfers.quantity")}</th>
                        </tr>
                      </thead>

                      {selectedProducts.length ? <tbody>{selectedProducts.map(renderProductRow)}</tbody> : null}
                      {c.productTopSpacerHeight > 0 ? (
                        <tbody aria-hidden="true"><tr><td colSpan={4} style={{ height: c.productTopSpacerHeight }} /></tr></tbody>
                      ) : null}
                      {c.sourceProductPages.map((page) => (
                        <MeasuredProductBody key={page.index} index={page.index} onMeasure={c.registerProductPageHeight}>
                          {page.items.filter((product) => !selectedIds.has(product.id)).map(renderProductRow)}
                        </MeasuredProductBody>
                      ))}
                      {c.productBottomSpacerHeight > 0 ? (
                        <tbody aria-hidden="true"><tr><td colSpan={4} style={{ height: c.productBottomSpacerHeight }} /></tr></tbody>
                      ) : null}
                    </table>

                    {(c.sourceProductsLoading || c.restoring) ? (
                      <p role="status" className="p-4 text-center text-xs font-bold text-slate-400">
                        {c.restoring ? t("inventoryTransfers.restoringDraft") : t("inventoryTransfers.sourceLoading")}
                      </p>
                    ) : null}
                    {c.sourceProductsLoadingMore ? (
                      <p role="status" className="p-3 text-center text-xs font-bold text-slate-400">{t("inventoryTransfers.moreLoading")}</p>
                    ) : null}
                    {!c.sourceProductsLoading && !c.restoring && !c.products.length ? (
                      <p className="p-6 text-center text-sm font-semibold text-slate-400">{t("inventoryTransfers.sourceEmpty")}</p>
                    ) : null}
                  </div>
                )}
              </section>

              <div className="flex shrink-0 justify-end pt-1">
                <button
                  type="button"
                  disabled={!c.canSubmit}
                  onClick={() => setConfirmOpen(true)}
                  className="h-9 rounded-lg bg-blue-700 px-3.5 text-xs font-black text-white disabled:opacity-40"
                  data-cp13-action-priority="primary"
                >
                  {t("inventoryTransfers.send")}
                </button>
              </div>
            </fieldset>
          </form>
        )}
      </div>
    </Modal>
  );
}
