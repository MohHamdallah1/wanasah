import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Modal } from "@/components/ui/modal";
import { createInventoryTabNavigationState } from "@/features/inventory/navigation";
import { apiErrorRequestId, apiErrorStatus } from "@/lib/apiErrors";
import { useTransferTranslation, formatTransferNumber } from "./i18n";
import type { TransferCreateController } from "./hooks/useTransferCreate";
import type { TransferSourceInventoryItem } from "./types";
import { addQuantity, compareQuantity, type Quantity } from "../quantity";
import { totalDraftQuantity, getErrorMessage } from "./utils";
import {
  composeTransferQuantity,
  splitTransferQuantity,
  supportsMixedTransferQuantity,
} from "./transferQuantity";
import { TransferBatchSelectionEditor } from "./TransferBatchSelectionEditor";
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
  const createBlockedByPending =
    (c.command.pending && !c.command.busy) || Boolean(c.command.recoveryError);

  useEffect(() => {
    if (!c.createOpen) setConfirmOpen(false);
  }, [c.createOpen]);

  const handleQuantityArrowNavigation = (
    event: KeyboardEvent<HTMLInputElement>,
  ) => {
    if (
      event.key !== "ArrowUp" &&
      event.key !== "ArrowDown"
    ) {
      return;
    }
    const inputs = Array.from(
      productScrollRef.current?.querySelectorAll<HTMLInputElement>(
        '[data-transfer-quantity-input="true"]:not(:disabled)',
      ) ?? [],
    );
    const currentIndex = inputs.indexOf(event.currentTarget);
    if (currentIndex < 0) return;
    const nextIndex =
      event.key === "ArrowDown"
        ? currentIndex + 1
        : currentIndex - 1;
    const next = inputs[nextIndex];
    if (!next) return;
    event.preventDefault();
    next.focus();
    next.select();
  };

  const selectedProducts = useMemo(
    () => [...new Map(c.draftItems.map((item) => [item.id, item])).values()],
    [c.draftItems],
  );

  const selectedSummary = useMemo(() => {
    if (!confirmOpen) return [];
    return selectedProducts.map((product) => {
      let quantity: Quantity = "0";
      for (const line of c.draftItems.filter((item) => item.id === product.id)) {
        quantity = addQuantity(quantity, totalDraftQuantity(line));
      }
      return { product, quantity };
    });
  }, [c.draftItems, confirmOpen, selectedProducts]);

  const uomName = (code: string, fallback: string) =>
    t(`uom.${code}`, { defaultValue: fallback });

  const formatProductQuantity = (
    product: TransferSourceInventoryItem,
    quantity: Quantity,
  ) => {
    const baseName = uomName(product.base_uom_code, product.base_uom_name);
    const displayName = uomName(product.display_uom_code, product.display_uom_name);
    const parts = splitTransferQuantity(product, quantity);
    if (!parts) return `${formatTransferNumber(quantity)} ${baseName}`;
    const display = compareQuantity(parts.displayQuantity, "0") > 0
      ? `${formatTransferNumber(parts.displayQuantity)} ${displayName}`
      : "";
    const remainder = compareQuantity(parts.baseRemainder, "0") > 0
      ? `${formatTransferNumber(parts.baseRemainder)} ${baseName}`
      : "";
    return [display, remainder].filter(Boolean).join(" + ") || `0 ${baseName}`;
  };

  const renderProductRow = (product: TransferSourceInventoryItem) => {
    const lines = c.draftItems.filter(
      (item) => item.id === product.id,
    );
    const autoLine =
      lines.length === 1 &&
      lines[0].batch_mode === "auto" &&
      lines[0].fefo_mode === "auto"
        ? lines[0]
        : null;
    const mixedQuantity = supportsMixedTransferQuantity(product);
    const baseName = uomName(
      product.base_uom_code,
      product.base_uom_name,
    );
    const displayName = uomName(
      product.display_uom_code,
      product.display_uom_name,
    );
    const invalid = lines.some((item) => {
      try {
        return compareQuantity(
          totalDraftQuantity(item),
          product.available_quantity,
        ) > 0;
      } catch {
        return item.quantity !== "0";
      }
    });

    const renderQuantityInputs = (
      value: string,
      onChange: (quantity: string) => void,
      ariaName: string,
    ) => {
      const normalized = value.trim() || "0";
      const parts = mixedQuantity
        ? splitTransferQuantity(
            product,
            normalized as Quantity,
          )
        : null;

      const updateMixedQuantity = (
        displayValue: string,
        baseValue: string,
      ) => {
        try {
          onChange(
            composeTransferQuantity(
              product,
              displayValue,
              baseValue,
            ),
          );
        } catch {
          // Keep the last valid canonical quantity visible.
        }
      };

      if (mixedQuantity && parts) {
        return (
          <>
            <label className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-slate-200 bg-white px-1.5">
              <input
                type="text"
                inputMode="decimal"
                data-transfer-quantity-input="true"
                aria-label={t(
                  "inventoryTransfers.productDisplayQuantity",
                  {
                    name: ariaName,
                    unit: displayName,
                  },
                )}
                value={
                  parts.displayQuantity === "0"
                    ? ""
                    : parts.displayQuantity
                }
                disabled={!c.ready || c.restoring}
                onKeyDown={handleQuantityArrowNavigation}
                onChange={(event) =>
                  updateMixedQuantity(
                    event.target.value,
                    parts.baseRemainder,
                  )
                }
                className="h-8 w-14 bg-transparent text-center text-xs font-black outline-none"
              />
              <span className="whitespace-nowrap text-[10px] font-bold text-slate-500">
                {displayName}
              </span>
            </label>
            <span className="text-xs font-black text-slate-300">
              +
            </span>
            <label className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-slate-200 bg-white px-1.5">
              <input
                type="text"
                inputMode="decimal"
                data-transfer-quantity-input="true"
                aria-label={t(
                  "inventoryTransfers.productBaseRemainder",
                  {
                    name: ariaName,
                    unit: baseName,
                  },
                )}
                value={
                  parts.baseRemainder === "0"
                    ? ""
                    : parts.baseRemainder
                }
                disabled={!c.ready || c.restoring}
                onKeyDown={handleQuantityArrowNavigation}
                onChange={(event) =>
                  updateMixedQuantity(
                    parts.displayQuantity,
                    event.target.value,
                  )
                }
                className="h-8 w-14 bg-transparent text-center text-xs font-black outline-none"
              />
              <span className="whitespace-nowrap text-[10px] font-bold text-slate-500">
                {baseName}
              </span>
            </label>
          </>
        );
      }

      return (
        <label className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-slate-200 bg-white px-1.5">
          <input
            type="text"
            inputMode="decimal"
            data-transfer-quantity-input="true"
            aria-label={t(
              "inventoryTransfers.productQuantity",
              { name: ariaName },
            )}
            aria-invalid={invalid}
            value={value}
            disabled={!c.ready || c.restoring}
            onKeyDown={handleQuantityArrowNavigation}
            onChange={(event) =>
              onChange(event.target.value)
            }
            className="h-8 w-20 bg-transparent text-center text-xs font-black outline-none"
          />
          <span className="whitespace-nowrap text-[10px] font-bold text-slate-500">
            {baseName}
          </span>
        </label>
      );
    };

    return (
      <tr
        key={product.id}
        data-product-id={product.id}
        className="border-t border-slate-100 align-middle hover:bg-slate-50/60"
      >
        <td className="px-2.5 py-2">
          <strong className="block truncate text-xs text-slate-900">
            {product.name}
          </strong>
        </td>
        <td className="px-2.5 py-2 text-center text-xs font-black text-slate-800">
          {formatProductQuantity(
            product,
            product.available_quantity,
          )}
        </td>
        <td className="px-2.5 py-2 text-center text-xs font-bold text-slate-600">
          {mixedQuantity
            ? `${displayName} + ${baseName}`
            : baseName}
        </td>
        <td className="px-2 py-1.5">
          {(
            !lines.length ||
            lines.every(
              (line) =>
                line.batch_mode === "auto" &&
                line.fefo_mode === "auto",
            )
          ) ? (
            <div className="flex flex-nowrap items-center justify-center gap-1.5 whitespace-nowrap">
              {renderQuantityInputs(
                autoLine?.quantity ?? "",
                (quantity) =>
                  c.updateProductQuantity(
                    product,
                    quantity,
                  ),
                product.name,
              )}
              <button
                type="button"
                disabled={!c.ready || c.restoring}
                onClick={() =>
                  c.updateProductQuantity(
                    product,
                    product.available_quantity,
                  )
                }
                title={t(
                  "inventoryTransfers.allTooltip",
                )}
                className="h-8 shrink-0 rounded-lg border border-blue-200 bg-blue-50 px-2.5 text-[11px] font-black text-blue-700 hover:bg-blue-100 disabled:opacity-40"
              >
                {t("inventoryTransfers.all")}
              </button>
              {lines.length > 0 ? (
                <button
                  type="button"
                  disabled={c.batchLoadingProductIds.includes(
                    product.id,
                  )}
                  title={t(
                    "inventoryTransfers.exactBatchButtonHint",
                  )}
                  onClick={() =>
                    void c.setDraftBatchMode(
                      lines[0].draft_key,
                      "exact",
                    )
                  }
                  className="h-8 shrink-0 rounded-lg border border-slate-200 bg-white px-2 text-[10px] font-black text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                >
                  {t(
                    "inventoryTransfers.selectExactBatch",
                  )}
                </button>
              ) : null}
            </div>
          ) : null}

          {invalid ? (
            <p
              role="alert"
              className="mt-1 text-center text-[10px] font-bold text-red-600"
            >
              {t(
                "inventoryTransfers.quantityExceeds",
                { name: product.name },
              )}
            </p>
          ) : null}

          {lines.some(
            (line) => line.batch_mode === "exact",
          ) ? (
            <div className="mt-1.5 space-y-2">
              {lines.map((item, index) => (
                <div
                  key={item.draft_key}
                  className="rounded-lg border border-slate-100 bg-slate-50/50 p-2"
                >
                  <TransferBatchSelectionEditor
                    item={item}
                    draftItems={c.draftItems}
                    options={
                      c.batchOptionsByProduct[item.id]
                    }
                    loading={c.batchLoadingProductIds.includes(
                      item.id,
                    )}
                    onModeChange={c.setDraftBatchMode}
                    onBatchChange={c.setSelectedBatch}
                    onAddBatchLine={
                      c.addSelectedBatchLine
                    }
                  />
                  <div className="mt-2 flex flex-nowrap items-center justify-end gap-1.5">
                    {renderQuantityInputs(
                      item.quantity,
                      (quantity) =>
                        c.updateDraftQuantity(
                          item.draft_key,
                          quantity,
                        ),
                      `${product.name} ${index + 1}`,
                    )}
                    <button
                      type="button"
                      onClick={() =>
                        c.removeDraftLine(
                          item.draft_key,
                        )
                      }
                      className="h-8 rounded-lg border border-red-100 bg-white px-2 text-[10px] font-black text-red-600"
                    >
                      {t("inventoryTransfers.remove")}
                    </button>
                  </div>
                </div>
              ))}
            </div>
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
      titleAside={confirmOpen ? undefined : t("inventoryTransfers.sourceHint")}
      compactHeader={!confirmOpen}
      bodyOverflow={confirmOpen ? "auto" : "hidden"}
      bodyClassName={confirmOpen ? "p-4 sm:p-5" : "flex min-h-0 p-2.5 sm:p-3"}
      maxWidth={confirmOpen ? "max-w-xl" : "max-w-6xl"}
      footer={!confirmOpen && !createBlockedByPending ? (
        <div dir={i18n.dir()} className="flex w-full flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            {selectedProducts.length ? (
              <span className="rounded-full bg-blue-50 px-2.5 py-1 text-[10px] font-black text-blue-700">
                {t("inventoryTransfers.selectedItemsCount", { count: selectedProducts.length })}
              </span>
            ) : null}
            <button
              type="button"
              disabled={!selectedProducts.length || c.createSubmitting}
              onClick={c.clearDraftItems}
              title={t("inventoryTransfers.clearQuantitiesHint")}
              className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-[11px] font-black text-slate-600 hover:bg-slate-50 disabled:opacity-40"
            >
              {t("inventoryTransfers.clearQuantities")}
            </button>
          </div>
          <button
            type="button"
            disabled={!c.canSubmit}
            onClick={() => setConfirmOpen(true)}
            className="h-9 rounded-lg bg-blue-700 px-4 text-xs font-black text-white disabled:opacity-40"
            data-cp13-action-priority="primary"
          >
            {t("inventoryTransfers.send")}
          </button>
        </div>
      ) : undefined}
    >
      <div dir={i18n.dir()} className={confirmOpen ? undefined : "flex h-full min-h-0 flex-1 flex-col"}>
        {createBlockedByPending ? (
          <div role="alert" className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
            <p>{t("inventoryTransfers.pending")}</p>
            <button type="button" disabled={c.command.busy || !!c.command.recoveryError} onClick={() => void c.retryPendingDispatch()}>
              {t("inventoryTransfers.retry")}
            </button>
          </div>
        ) : confirmOpen ? (
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              void c.handleDispatchTransfer();
            }}
          >
            <div className="grid gap-2 rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-xs sm:grid-cols-2">
              <div><span className="font-bold text-slate-500">{t("inventoryTransfers.source")}:</span> <strong>{c.source?.name}</strong></div>
              <div><span className="font-bold text-slate-500">{t("inventoryTransfers.destination")}:</span> <strong>{c.destination?.name}</strong></div>
            </div>

            <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
              <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/70 px-3 py-2">
                <h4 className="text-xs font-black text-slate-700">{t("inventoryTransfers.selectedProductsSummary")}</h4>
                <span className="text-[10px] font-black text-blue-700">{t("inventoryTransfers.selectedItemsCount", { count: selectedSummary.length })}</span>
              </div>
              <div className="max-h-64 divide-y divide-slate-100 overflow-y-auto">
                {selectedSummary.map(({ product, quantity }) => (
                  <div key={product.id} className="flex items-center justify-between gap-4 px-3 py-2.5 text-xs">
                    <span className="min-w-0 flex-1 truncate font-bold text-slate-800">{product.name}</span>
                    <strong className="shrink-0 text-slate-700">{formatProductQuantity(product, quantity)}</strong>
                  </div>
                ))}
              </div>
            </section>

            <details className="rounded-lg border border-slate-100 bg-slate-50/50 px-3 py-2">
              <summary className="cursor-pointer text-[11px] font-bold text-slate-500">{t("inventoryTransfers.addOptionalNote")}</summary>
              <textarea
                aria-label={t("inventoryTransfers.notes")}
                value={c.createNotes}
                onChange={(event) => c.updateCreateNotes(event.target.value)}
                maxLength={4000}
                placeholder={t("inventoryTransfers.notesOptional")}
                className="mt-2 min-h-20 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
              />
            </details>

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
            className="flex min-h-0 flex-1 flex-col gap-2"
            data-cp13-create-flow="transfer"
            onSubmit={(event) => {
              event.preventDefault();
              if (c.canSubmit) setConfirmOpen(true);
            }}
          >
            {c.policyBlocked ? <Link to="/inventory" state={createInventoryTabNavigationState("warehouses")}>{t("inventoryTransfers.policySetup")}</Link> : null}

            <fieldset disabled={c.createSubmitting} className="contents">
              <div className="grid gap-2 md:grid-cols-2">
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

              <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white">
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
                    <table className="w-full min-w-[900px] table-fixed text-sm" aria-busy={c.sourceProductsLoading || c.sourceProductsLoadingMore || c.restoring}>
                      <thead className="sticky top-0 z-10 border-b border-slate-200 bg-slate-50/95 backdrop-blur">
                        <tr>
                          <th className="w-[34%] p-2 text-start">
                            <input
                              type="search"
                              aria-label={t("inventoryTransfers.productSearch")}
                              value={c.productSearchInput}
                              onChange={(event) => c.setProductSearchInput(event.target.value)}
                              maxLength={100}
                              placeholder={t("inventoryTransfers.productSearch")}
                              className="h-8 w-full max-w-sm rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-bold text-slate-700 outline-none placeholder:text-slate-400 focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
                            />
                          </th>
                          <th className="w-[18%] p-2.5 text-center text-[11px] font-black text-slate-500">{t("inventoryTransfers.availableTransfer")}</th>
                          <th className="w-[14%] p-2.5 text-center text-[11px] font-black text-slate-500">{t("inventoryTransfers.unit")}</th>
                          <th className="w-[34%] p-2.5 text-center text-[11px] font-black text-slate-500">{t("inventoryTransfers.quantity")}</th>
                        </tr>
                      </thead>

                      {c.productTopSpacerHeight > 0 ? (
                        <tbody aria-hidden="true"><tr><td colSpan={4} style={{ height: c.productTopSpacerHeight }} /></tr></tbody>
                      ) : null}
                      {c.sourceProductPages.map((page) => (
                        <MeasuredProductBody key={page.index} index={page.index} onMeasure={c.registerProductPageHeight}>
                          {page.items.map(renderProductRow)}
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


            </fieldset>
          </form>
        )}
      </div>
    </Modal>
  );
}
