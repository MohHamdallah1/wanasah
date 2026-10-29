import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseOverrideOptions } from "../parsers";
import { useTransferTranslation } from "../i18n";
import { getErrorMessage } from "../utils";
import type { FefoMode, TransferDraftItem, TransferOverrideOptions } from "../types";

export function useTransferFefo(sourceLocationId: number | null, canOverride: boolean, draftItems: TransferDraftItem[], setDraftItems: Dispatch<SetStateAction<TransferDraftItem[]>>) {
  const authenticatedFetch = useAuthFetch();
  const { t } = useTransferTranslation();
  const generation = useRef(0);
  const currentSource = useRef(sourceLocationId);
  currentSource.current = sourceLocationId;
  const [overrideOptionsByProduct, setOverrideOptionsByProduct] = useState<
    Record<number, TransferOverrideOptions>
  >({});
  const [overrideLoadingProductIds, setOverrideLoadingProductIds] = useState<
    number[]
  >([]);
  const overrideRequestSeq = useRef<Record<number, number>>({});
  const restoredProducts = useRef(new Set<number>());
  const resetFefo = useCallback(() => {
    ++generation.current;
    overrideRequestSeq.current = {};
    restoredProducts.current = new Set();
    setOverrideOptionsByProduct({});
    setOverrideLoadingProductIds([]);
  }, []);
  const invalidate = useCallback(() => { ++generation.current; }, []);
  useEffect(() => { resetFefo(); return invalidate; }, [sourceLocationId, resetFefo, invalidate]);
  const loadOverrideOptions = useCallback(
    async (productId: number): Promise<TransferOverrideOptions | null> => {
      if (sourceLocationId === null) {
        toast.error(t("inventoryTransfers.chooseSource"));
        return null;
      }

      const cached = overrideOptionsByProduct[productId];
      if (
        cached &&
        cached.location_id === sourceLocationId &&
        cached.product_variant_id === productId
      ) {
        return cached;
      }

      const epoch = generation.current;
      const nextSeq =
        (overrideRequestSeq.current[productId] || 0) + 1;
      overrideRequestSeq.current[productId] = nextSeq;
      setOverrideLoadingProductIds((prev) =>
        prev.includes(productId) ? prev : [...prev, productId]
      );

      try {
        const params = new URLSearchParams({
          location_id: String(sourceLocationId),
          product_variant_id: String(productId),
        });

        const raw = await authenticatedFetch(
          `/warehouse/unified/transfer/override-options?${params.toString()}`
        );

        if ((currentSource.current !== sourceLocationId || generation.current !== epoch || overrideRequestSeq.current[productId] !== nextSeq)) {
          return null;
        }

        const parsed = parseOverrideOptions(
          raw,
          sourceLocationId,
          productId
        );

        setOverrideOptionsByProduct((prev) => ({
          ...prev,
          [productId]: parsed,
        }));
        return parsed;
      } catch (error: unknown) {
        if (currentSource.current === sourceLocationId && generation.current === epoch && overrideRequestSeq.current[productId] === nextSeq) {
          toast.error(
            getErrorMessage(error, t("inventoryTransfers.overrideFailure"))
          );
        }
        return null;
      } finally {
        if (currentSource.current === sourceLocationId && generation.current === epoch && overrideRequestSeq.current[productId] === nextSeq) {
          setOverrideLoadingProductIds((prev) =>
            prev.filter((id) => id !== productId)
          );
        }
      }
    },
    [
      authenticatedFetch,
      overrideOptionsByProduct,
      sourceLocationId,
      t,
    ]
  );

  useEffect(() => {
    if (!canOverride) return;
    for (const item of draftItems) {
      if (item.fefo_mode === "override" && !overrideOptionsByProduct[item.product_variant_id] && !restoredProducts.current.has(item.product_variant_id)) {
        restoredProducts.current.add(item.product_variant_id);
        void loadOverrideOptions(item.product_variant_id);
      }
    }
  }, [canOverride, draftItems, overrideOptionsByProduct, loadOverrideOptions]);

  const setDraftFefoMode = async (
    draftKey: string,
    mode: FefoMode
  ) => {
    const current = draftItems.find(
      (item) => item.draft_key === draftKey
    );
    if (!current || current.fefo_mode === mode) return;

    const siblingLines = draftItems.filter(
      (item) =>
        item.product_variant_id === current.product_variant_id &&
        item.draft_key !== draftKey
    );

    if (mode === "auto" && siblingLines.length > 0) {
      toast.error(
        t("inventoryTransfers.removeSplits")
      );
      return;
    }

    if (mode === "override") {
      if (!canOverride) return;
      const options = await loadOverrideOptions(
        current.product_variant_id
      );
      if (!options) return;
      if (options.batches.length === 0) {
        toast.error(t("inventoryTransfers.noBatches"));
        return;
      }
      if (options.reasons.length === 0) {
        toast.info(
          t("inventoryTransfers.noReasons")
        );
        return;
      }
    }

    setDraftItems((prev) =>
      prev.map((item) =>
        item.draft_key === draftKey
          ? {
              ...item,
              fefo_mode: mode,
              override_batch_id: null,
              override_reason_id: null,
              override_batch_available: null,
            }
          : item
      )
    );
  };

  const setOverrideBatch = (
    draftKey: string,
    batchId: number | null
  ) => {
    const current = draftItems.find(
      (item) => item.draft_key === draftKey
    );
    if (!current || current.fefo_mode !== "override") return;

    const options =
      overrideOptionsByProduct[current.product_variant_id];
    if (
      !options ||
      options.location_id !== sourceLocationId
    ) {
      toast.error(t("inventoryTransfers.staleOptions"));
      return;
    }

    if (batchId === null) {
      setDraftItems((prev) =>
        prev.map((item) =>
          item.draft_key === draftKey
            ? {
                ...item,
                override_batch_id: null,
                override_batch_available: null,
              }
            : item
        )
      );
        return;
    }

    const batch = options.batches.find(
      (item) => item.id === batchId
    );
    if (!batch) {
      toast.error(t("inventoryTransfers.invalidBatch"));
      return;
    }

    const duplicate = draftItems.some(
      (item) =>
        item.draft_key !== draftKey &&
        item.product_variant_id === current.product_variant_id &&
        item.override_batch_id === batchId
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
              override_batch_id: batch.id,
              override_batch_available: batch.available_quantity,
            }
          : item
      )
    );
  };

  const setOverrideReason = (
    draftKey: string,
    reasonId: number | null
  ) => {
    const current = draftItems.find(
      (item) => item.draft_key === draftKey
    );
    if (!current || current.fefo_mode !== "override") return;

    const options =
      overrideOptionsByProduct[current.product_variant_id];
    if (
      reasonId !== null &&
      (!options ||
        !options.reasons.some((reason) => reason.id === reasonId))
    ) {
      toast.error(t("inventoryTransfers.invalidReason"));
      return;
    }

    setDraftItems((prev) =>
      prev.map((item) =>
        item.draft_key === draftKey
          ? { ...item, override_reason_id: reasonId }
          : item
      )
    );
  };

  const addOverrideBatchLine = async (productId: number) => {
    const existingLines = draftItems.filter(
      (item) => item.product_variant_id === productId
    );
    if (
      existingLines.length === 0 ||
      existingLines.some((item) => item.fefo_mode !== "override")
    ) {
      toast.error(t("inventoryTransfers.overrideOnly"));
      return;
    }

    const options = await loadOverrideOptions(productId);
    if (!options) return;

    const selectedBatchIds = new Set(
      existingLines
        .map((item) => item.override_batch_id)
        .filter((id): id is number => id !== null)
    );
    const hasAnotherBatch = options.batches.some(
      (batch) => !selectedBatchIds.has(batch.id)
    );
    if (!hasAnotherBatch) {
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
        fefo_mode: "override",
        override_batch_id: null,
        override_reason_id: null,
        override_batch_available: null,
      },
    ]);
  };


  return { overrideOptionsByProduct, overrideLoadingProductIds, resetFefo, setDraftFefoMode, setOverrideBatch, setOverrideReason, addOverrideBatchLine };
}
