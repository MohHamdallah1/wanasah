import { Search, Trash2 } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import type { TransferCreateController } from "./hooks/useTransferCreate";
import { totalDraftPacks } from "./utils";
import { FefoOverrideEditor } from "./FefoOverrideEditor";

interface TransferCreateModalProps {
  locationId: number;
  controller: TransferCreateController;
}

export function TransferCreateModal({
  locationId,
  controller,
}: TransferCreateModalProps) {
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
      title="إنشاء حوالة موحّدة"
      maxWidth="max-w-6xl"
    >
      <div className="space-y-5">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="text-xs font-bold text-slate-600">
              اتجاه الحوالة
            </label>
            <select
              value={createDirection}
              onChange={(event) =>
                updateCreateDirection(event.target.value)
              }
              className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none"
            >
              <option value="outgoing" disabled={!canOutgoing}>
                صادرة من المستودع المحدد
              </option>
              <option value="incoming" disabled={!canIncoming}>
                واردة إلى المستودع المحدد
              </option>
            </select>
          </div>

          <div>
            <label className="text-xs font-bold text-slate-600">
              {createDirection === "outgoing" ? "الوجهة" : "المصدر"}
            </label>
            <input
              value={transferLocationSearchInput}
              onChange={(event) =>
                setTransferLocationSearchInput(event.target.value)
              }
              placeholder="ابحث باسم أو كود المستودع/السيارة"
              maxLength={100}
              className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none"
            />
            <select
              value={counterpartLocationId ?? ""}
              disabled={transferLocationsLoading}
              onChange={(event) =>
                updateCounterpartLocation(event.target.value)
              }
              className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none disabled:opacity-50"
            >
              <option value="" disabled>
                اختر موقعاً
              </option>
              {transferLocations
                .filter((item) => item.id !== locationId)
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.location_type === "WAREHOUSE"
                      ? "مستودع"
                      : "سيارة"}{" "}
                    — {item.name} ({item.code})
                  </option>
                ))}
            </select>
          </div>

          <div className="rounded-xl bg-slate-50 border border-slate-200 p-3 text-xs text-slate-600">
            <div className="font-bold text-slate-800 mb-1">
              الموقع المحدد
            </div>
            ID #{locationId} —{" "}
            {createDirection === "outgoing" ? "المصدر" : "الوجهة"}
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="rounded-2xl border border-slate-200 p-4 space-y-3">
            <div>
              <h3 className="font-black text-slate-800">
                مخزون المصدر
              </h3>
              <p className="text-xs text-slate-500 mt-1">
                البحث مرتبط بـ source location_id الفعلي.
              </p>
            </div>

            <div className="relative">
              <Search className="w-4 h-4 absolute right-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                value={productSearchInput}
                onChange={(event) =>
                  setProductSearchInput(event.target.value)
                }
                placeholder="بحث بالصنف أو SKU"
                maxLength={100}
                className="w-full pr-10 pl-3 py-2.5 rounded-xl border border-slate-200 bg-white text-sm outline-none"
              />
            </div>

            <div className="max-h-72 overflow-auto divide-y divide-slate-100 border border-slate-100 rounded-xl">
              {sourceProducts.map((product) => {
                const added = draftItems.some(
                  (item) => item.id === product.id
                );
                return (
                  <button
                    key={product.id}
                    type="button"
                    disabled={added}
                    onClick={() => addDraftProduct(product)}
                    className="w-full p-3 text-right hover:bg-slate-50 disabled:opacity-40"
                  >
                    <div className="font-bold text-slate-800">
                      {product.name}
                    </div>
                    <div className="text-[11px] text-slate-500 mt-1">
                      SKU: {product.sku || "—"} · المتاح:{" "}
                      {product.available_packs} حبة
                    </div>
                  </button>
                );
              })}

              {sourceProductsNextCursor && (
                <div className="p-2 border-t border-slate-100">
                  <button
                    type="button"
                    onClick={loadMoreSourceProducts}
                    disabled={
                      sourceProductsLoading ||
                      sourceProductsLoadingMore
                    }
                    className="w-full py-2.5 rounded-lg border border-blue-200 text-blue-700 bg-blue-50 hover:bg-blue-100 text-xs font-bold disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {sourceProductsLoadingMore
                      ? "جاري تحميل المزيد..."
                      : "تحميل المزيد"}
                  </button>
                </div>
              )}

              {!sourceProductsLoading &&
                sourceLocationId !== null &&
                sourceProducts.length === 0 && (
                  <div className="p-8 text-center text-slate-400 text-sm">
                    لا يوجد مخزون متاح مطابق.
                  </div>
                )}

              {sourceProductsLoading && (
                <div className="p-8 text-center text-slate-400 text-sm">
                  جاري جلب مخزون المصدر...
                </div>
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 p-4 space-y-3">
            <div>
              <h3 className="font-black text-slate-800">
                أصناف الحوالة
              </h3>
              <p className="text-xs text-slate-500 mt-1">
                FEFO تلقائي افتراضياً، مع تجاوز موثّق عند الحاجة.
              </p>
            </div>

            <div className="max-h-72 overflow-auto space-y-2">
              {draftItems.map((item) => {
                const total = totalDraftPacks(item);
                const options =
                  overrideOptionsByProduct[item.product_variant_id];
                const overrideLoading =
                  overrideLoadingProductIds.includes(
                    item.product_variant_id
                  );
                const selectedBatch =
                  item.override_batch_id !== null
                    ? options?.batches.find(
                        (batch) =>
                          batch.id === item.override_batch_id
                      ) ?? null
                    : null;
                const availableLimit =
                  item.fefo_mode === "override"
                    ? selectedBatch?.available_packs ?? 0
                    : item.available_packs;
                const invalid =
                  total > 0 && total > availableLimit;

                return (
                  <div
                    key={item.draft_key}
                    className={`rounded-xl border p-3 ${
                      invalid
                        ? "border-red-300 bg-red-50"
                        : item.fefo_mode === "override"
                          ? "border-amber-300 bg-amber-50/40"
                          : "border-slate-200"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <div className="font-bold text-slate-800">
                          {item.name}
                        </div>
                        <div className="text-[10px] text-slate-400">
                          إجمالي المتاح في المصدر:{" "}
                          {item.available_packs} حبة
                        </div>
                      </div>

                      <button
                        type="button"
                        onClick={() =>
                          removeDraftLine(item.draft_key)
                        }
                        className="p-2 rounded-lg text-red-500 hover:bg-red-50"
                      >
                        <Trash2 className="w-4 h-4" />
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

                    <div className="grid grid-cols-2 gap-2 mt-3">
                      <div>
                        <label className="text-[10px] font-bold text-slate-500">
                          كراتين
                        </label>
                        <input
                          type="number"
                          min="0"
                          step="1"
                          value={item.cartons}
                          onChange={(event) =>
                            updateDraftQuantity(
                              item.draft_key,
                              "cartons",
                              Number(event.target.value)
                            )
                          }
                          className="mt-1 w-full rounded-lg border border-slate-200 px-2 py-2 text-center"
                        />
                      </div>
                      <div>
                        <label className="text-[10px] font-bold text-slate-500">
                          حبات
                        </label>
                        <input
                          type="number"
                          min="0"
                          max={Math.max(
                            0,
                            item.packs_per_carton - 1
                          )}
                          step="1"
                          value={item.loose_packs}
                          onChange={(event) =>
                            updateDraftQuantity(
                              item.draft_key,
                              "loose_packs",
                              Number(event.target.value)
                            )
                          }
                          className="mt-1 w-full rounded-lg border border-slate-200 px-2 py-2 text-center"
                        />
                      </div>
                    </div>

                    <div
                      className={`text-[11px] mt-2 font-bold ${
                        invalid ? "text-red-600" : "text-slate-500"
                      }`}
                    >
                      الإجمالي: {total} حبة
                      {item.fefo_mode === "override" &&
                      selectedBatch
                        ? ` من الدفعة ${selectedBatch.batch_number}`
                        : ""}
                      {invalid ? " — يتجاوز المتاح" : ""}
                    </div>
                  </div>
                );
              })}

              {draftItems.length === 0 && (
                <div className="p-8 text-center text-slate-400 text-sm border border-dashed border-slate-200 rounded-xl">
                  أضف أصنافاً من مخزون المصدر.
                </div>
              )}
            </div>
          </div>
        </div>

        <div>
          <label className="text-xs font-bold text-slate-600">
            ملاحظات الحوالة
          </label>
          <textarea
            value={createNotes}
            onChange={(event) =>
              updateCreateNotes(event.target.value)
            }
            maxLength={4000}
            className="mt-1 w-full min-h-24 rounded-xl border border-slate-200 px-3 py-2.5 outline-none"
          />
        </div>

        <button
          onClick={() => void handleDispatchTransfer()}
          disabled={
            !canSubmit || createSubmitting ||
            transferLocationsLoading ||
            counterpartLocationId === null ||
            draftItems.length === 0
          }
          className="w-full py-3 rounded-xl bg-blue-600 text-white font-bold disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {createSubmitting
            ? "جاري تحويل البضاعة إلى IN_TRANSIT..."
            : "إرسال الحوالة"}
        </button>
      </div>
    </Modal>
  );
}
