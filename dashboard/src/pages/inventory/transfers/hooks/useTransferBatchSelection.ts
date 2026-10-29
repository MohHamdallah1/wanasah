import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseBatchOptions } from "../parsers";
import { useTransferTranslation } from "../i18n";
import { getErrorMessage } from "../utils";
import type {
  TransferBatchMode,
  TransferBatchOptions,
  TransferDraftItem,
} from "../types";

export function useTransferBatchSelection(
  sourceLocationId: number | null,
  draftItems: TransferDraftItem[],
  setDraftItems: Dispatch<SetStateAction<TransferDraftItem[]>>,
) {
  const authenticatedFetch = useAuthFetch();
  const { t } = useTransferTranslation();
  const generation = useRef(0);
  const currentSource = useRef(sourceLocationId);
  currentSource.current = sourceLocationId;
  const requestSeq = useRef<Record<number, number>>({});
  const restoredProducts = useRef(new Set<number>());
  const [batchOptionsByProduct, setBatchOptionsByProduct] = useState<
    Record<number, TransferBatchOptions>
  >({});
  const [batchLoadingProductIds, setBatchLoadingProductIds] = useState<number[]>([]);

  const resetBatchSelection = useCallback(() => {
    ++generation.current;
    requestSeq.current = {};
    restoredProducts.current = new Set();
    setBatchOptionsByProduct({});
    setBatchLoadingProductIds([]);
  }, []);

  const invalidate = useCallback(() => {
    ++generation.current;
  }, []);

  useEffect(() => {
    resetBatchSelection();
    return invalidate;
  }, [sourceLocationId, resetBatchSelection, invalidate]);

  const loadBatchOptions = useCallback(async (
    productId: number,
  ): Promise<TransferBatchOptions | null> => {
    if (sourceLocationId === null) {
      toast.error(t("inventoryTransfers.chooseSource"));
      return null;
    }

    const cached = batchOptionsByProduct[productId];
    if (
      cached &&
      cached.location_id === sourceLocationId &&
      cached.product_variant_id === productId
    ) {
      return cached;
    }

    const epoch = generation.current;
    const nextSeq = (requestSeq.current[productId] || 0) + 1;
    requestSeq.current[productId] = nextSeq;
    setBatchLoadingProductIds((prev) =>
      prev.includes(productId) ? prev : [...prev, productId]
    );

    try {
      const params = new URLSearchParams({
        location_id: String(sourceLocationId),
        product_variant_id: String(productId),
      });
      const raw = await authenticatedFetch(
        `/warehouse/unified/transfer/batch-options?${params.toString()}`
      );

      if (
        currentSource.current !== sourceLocationId ||
        generation.current !== epoch ||
        requestSeq.current[productId] !== nextSeq
      ) {
        return null;
      }

      const parsed = parseBatchOptions(
        raw,
        sourceLocationId,
        productId,
      );
      setBatchOptionsByProduct((prev) => ({
        ...prev,
        [productId]: parsed,
      }));
      return parsed;
    } catch (error: unknown) {
      if (
        currentSource.current === sourceLocationId &&
        generation.current === epoch &&
        requestSeq.current[productId] === nextSeq
      ) {
        toast.error(
          getErrorMessage(
            error,
            t("inventoryTransfers.batchOptionsFailure"),
          ),
        );
      }
      return null;
    } finally {
      if (
        currentSource.current === sourceLocationId &&
        generation.current === epoch &&
        requestSeq.current[productId] === nextSeq
      ) {
        setBatchLoadingProductIds((prev) =>
          prev.filter((id) => id !== productId)
        );
      }
    }
  }, [
    authenticatedFetch,
    batchOptionsByProduct,
    sourceLocationId,
    t,
  ]);

  useEffect(() => {
    for (const item of draftItems) {
      if (
        item.batch_mode === "exact" &&
        !batchOptionsByProduct[item.product_variant_id] &&
        !restoredProducts.current.has(item.product_variant_id)
      ) {
        restoredProducts.current.add(item.product_variant_id);
        void loadBatchOptions(item.product_variant_id);
      }
    }
  }, [batchOptionsByProduct, draftItems, loadBatchOptions]);

  const setDraftBatchMode = async (
    draftKey: string,
    mode: TransferBatchMode,
  ) => {
    const current = draftItems.find(
      (item) => item.draft_key === draftKey,
    );
    if (!current || current.batch_mode === mode) return;

    const siblingLines = draftItems.filter(
      (item) =>
        item.product_variant_id === current.product_variant_id &&
        item.draft_key !== draftKey,
    );

    if (mode === "auto" && siblingLines.length > 0) {
      toast.error(t("inventoryTransfers.removeBatchSplits"));
      return;
    }

    let singleBatch: TransferBatchOptions["batches"][number] | null = null;
    if (mode === "exact") {
      const options = await loadBatchOptions(
        current.product_variant_id,
      );
      if (!options) return;
      if (options.batches.length === 0) {
        toast.error(t("inventoryTransfers.noBatches"));
        return;
      }
      singleBatch =
        options.batches.length === 1 ? options.batches[0] : null;
    }

    setDraftItems((prev) =>
      prev.map((item) =>
        item.draft_key === draftKey
          ? {
              ...item,
              batch_mode: mode,
              batch_id:
                mode === "exact" ? singleBatch?.id ?? null : null,
              batch_available:
                mode === "exact"
                  ? singleBatch?.available_quantity ?? null
                  : null,
              fefo_mode: "auto",
              override_batch_id: null,
              override_reason_id: null,
              override_batch_available: null,
            }
          : item,
      ),
    );
  };

  const setSelectedBatch = (
    draftKey: string,
    batchId: number | null,
  ) => {
    const current = draftItems.find(
      (item) => item.draft_key === draftKey,
    );
    if (!current || current.batch_mode !== "exact") return;

    const options =
      batchOptionsByProduct[current.product_variant_id];
    if (
      !options ||
      options.location_id !== sourceLocationId
    ) {
      toast.error(t("inventoryTransfers.staleBatchOptions"));
      return;
    }

    if (batchId === null) {
      setDraftItems((prev) =>
        prev.map((item) =>
          item.draft_key === draftKey
            ? {
                ...item,
                batch_id: null,
                batch_available: null,
              }
            : item,
        ),
      );
      return;
    }

    const batch = options.batches.find(
      (candidate) => candidate.id === batchId,
    );
    if (!batch) {
      toast.error(t("inventoryTransfers.invalidBatch"));
      return;
    }

    const duplicate = draftItems.some(
      (item) =>
        item.draft_key !== draftKey &&
        item.product_variant_id === current.product_variant_id &&
        item.batch_id === batchId,
    );
    if (duplicate) {
      toast.error(t("inventoryTransfers.duplicateBatch"));
      return;
    }

    setDraftItems((prev) =>
      prev.map((item) =>
        item.draft_key === draftKey
          ? {
              ...item,
              batch_id: batch.id,
              batch_available: batch.available_quantity,
            }
          : item,
      ),
    );
  };

  const addSelectedBatchLine = async (productId: number) => {
    const existingLines = draftItems.filter(
      (item) => item.product_variant_id === productId,
    );
    if (
      existingLines.length === 0 ||
      existingLines.some(
        (item) => item.batch_mode !== "exact",
      )
    ) {
      return;
    }

    const options = await loadBatchOptions(productId);
    if (!options) return;
    if (existingLines.some((item) => item.batch_id === null)) {
      toast.info(t("inventoryTransfers.selectBatchBeforeSplit"));
      return;
    }

    const selectedIds = new Set(
      existingLines
        .map((item) => item.batch_id)
        .filter((id): id is number => id !== null),
    );
    if (
      !options.batches.some(
        (batch) => !selectedIds.has(batch.id),
      )
    ) {
      toast.info(t("inventoryTransfers.allBatches"));
      return;
    }

    const template = existingLines[0];
    setDraftItems((prev) => [
      ...prev,
      {
        ...template,
        draft_key: crypto.randomUUID(),
        quantity: "0",
        batch_mode: "exact",
        batch_id: null,
        batch_available: null,
        fefo_mode: "auto",
        override_batch_id: null,
        override_reason_id: null,
        override_batch_available: null,
      },
    ]);
  };

  return {
    batchOptionsByProduct,
    batchLoadingProductIds,
    resetBatchSelection,
    loadBatchOptions,
    setDraftBatchMode,
    setSelectedBatch,
    addSelectedBatchLine,
  };
}
