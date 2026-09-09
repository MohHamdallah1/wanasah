import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import {
  parseOverrideOptions,
  parseSourceInventoryPage,
  parseTransferLocations,
} from "../parsers";
import type {
  FefoMode,
  TransferCreateDirection,
  TransferDraftItem,
  TransferLocationOption,
  TransferOverrideOptions,
  TransferSourceInventoryItem,
} from "../types";
import {
  getErrorMessage,
  getMutationMessage,
  totalDraftPacks,
} from "../utils";

interface UseTransferCreateArgs {
  locationId: number;
  onInventoryChanged: () => void | Promise<void>;
  onCompleted: () => void;
}

export function useTransferCreate({
  locationId,
  onInventoryChanged,
  onCompleted,
}: UseTransferCreateArgs) {
  const authenticatedFetch = useAuthFetch();

  const [createOpen, setCreateOpen] = useState(false);
  const [createDirection, setCreateDirection] =
    useState<TransferCreateDirection>("outgoing");
  const [transferLocations, setTransferLocations] = useState<
    TransferLocationOption[]
  >([]);
  const [transferLocationsLoading, setTransferLocationsLoading] =
    useState(false);
  const [transferLocationSearchInput, setTransferLocationSearchInput] =
    useState("");
  const [transferLocationSearch, setTransferLocationSearch] = useState("");
  const transferLocationsRequestSeq = useRef(0);
  const [counterpartLocationId, setCounterpartLocationId] =
    useState<number | null>(null);
  const [createNotes, setCreateNotes] = useState("");
  const [createRequestId, setCreateRequestId] = useState(() =>
    crypto.randomUUID()
  );
  const [createSubmitting, setCreateSubmitting] = useState(false);

  const [productSearchInput, setProductSearchInput] = useState("");
  const [productSearch, setProductSearch] = useState("");
  const [sourceProducts, setSourceProducts] = useState<
    TransferSourceInventoryItem[]
  >([]);
  const [sourceProductsLoading, setSourceProductsLoading] = useState(false);
  const [sourceProductsLoadingMore, setSourceProductsLoadingMore] =
    useState(false);
  const [sourceProductsNextCursor, setSourceProductsNextCursor] =
    useState<string | null>(null);
  const sourceProductsRequestSeq = useRef(0);
  const [draftItems, setDraftItems] = useState<TransferDraftItem[]>([]);
  const [overrideOptionsByProduct, setOverrideOptionsByProduct] = useState<
    Record<number, TransferOverrideOptions>
  >({});
  const [overrideLoadingProductIds, setOverrideLoadingProductIds] = useState<
    number[]
  >([]);
  const overrideRequestSeq = useRef<Record<number, number>>({});

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = productSearchInput.trim();
      setProductSearch(clean.length >= 2 ? clean : "");
    }, 300);

    return () => window.clearTimeout(timer);
  }, [productSearchInput]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = transferLocationSearchInput.trim();
      setTransferLocationSearch(clean.length >= 2 ? clean : "");
    }, 300);

    return () => window.clearTimeout(timer);
  }, [transferLocationSearchInput]);

  const sourceLocationId =
    createDirection === "outgoing"
      ? locationId
      : counterpartLocationId;
  const destinationLocationId =
    createDirection === "outgoing"
      ? counterpartLocationId
      : locationId;

  const resetCreateRequestId = () => {
    setCreateRequestId(crypto.randomUUID());
  };

  const resetCreateForm = useCallback(() => {
    sourceProductsRequestSeq.current += 1;
    transferLocationsRequestSeq.current += 1;
    overrideRequestSeq.current = {};
    setCreateDirection("outgoing");
    setCounterpartLocationId(null);
    setCreateNotes("");
    setTransferLocations([]);
    setTransferLocationSearchInput("");
    setTransferLocationSearch("");
    setProductSearchInput("");
    setProductSearch("");
    setSourceProducts([]);
    setSourceProductsNextCursor(null);
    setSourceProductsLoadingMore(false);
    setDraftItems([]);
    setOverrideOptionsByProduct({});
    setOverrideLoadingProductIds([]);
    setCreateRequestId(crypto.randomUUID());
  }, []);

  const openCreate = () => {
    resetCreateForm();
    setCreateOpen(true);
  };

  const fetchTransferLocations = useCallback(async () => {
    if (!createOpen) return;

    const seq = ++transferLocationsRequestSeq.current;
    setTransferLocationsLoading(true);

    try {
      const params = new URLSearchParams({ limit: "50" });
      if (transferLocationSearch) {
        params.set("search", transferLocationSearch);
      }

      const raw = await authenticatedFetch(
        `/warehouse/unified/transfer/locations?${params.toString()}`
      );

      if (seq !== transferLocationsRequestSeq.current) return;

      const locations = parseTransferLocations(raw).filter(
        (item) => item.id !== locationId
      );

      setTransferLocations((prev) => {
        const merged = new Map<number, TransferLocationOption>();
        for (const item of prev) merged.set(item.id, item);
        for (const item of locations) merged.set(item.id, item);
        return [...merged.values()];
      });
    } catch (error: unknown) {
      if (seq !== transferLocationsRequestSeq.current) return;
      toast.error(
        "فشل جلب مواقع الحوالة: " + getErrorMessage(error)
      );
    } finally {
      if (seq === transferLocationsRequestSeq.current) {
        setTransferLocationsLoading(false);
      }
    }
  }, [
    authenticatedFetch,
    createOpen,
    locationId,
    transferLocationSearch,
  ]);

  useEffect(() => {
    void fetchTransferLocations();
  }, [fetchTransferLocations]);

  const closeCreate = () => {
    if (createSubmitting) return;
    setCreateOpen(false);
    resetCreateForm();
  };

  const fetchSourceProducts = useCallback(
    async (
      pageCursor: string | null = null,
      append = false
    ) => {
      if (!createOpen || sourceLocationId === null) {
        setSourceProducts([]);
        setSourceProductsNextCursor(null);
        return;
      }

      const seq = ++sourceProductsRequestSeq.current;

      if (append) {
        setSourceProductsLoadingMore(true);
      } else {
        setSourceProductsLoading(true);
        setSourceProductsNextCursor(null);
      }

      try {
        const params = new URLSearchParams({
          location_id: String(sourceLocationId),
          limit: "50",
        });
        if (productSearch) params.set("search", productSearch);
        if (pageCursor) params.set("cursor", pageCursor);

        const raw = await authenticatedFetch(
          `/warehouse/unified/transfer/source-inventory?${params.toString()}`
        );

        if (seq !== sourceProductsRequestSeq.current) return;

        const page = parseSourceInventoryPage(raw);
        const nextItems = page.items.filter(
          (item) => item.available_packs > 0
        );

        setSourceProducts((prev) => {
          if (!append) return nextItems;

          const merged = new Map<number, TransferSourceInventoryItem>();
          for (const item of prev) merged.set(item.id, item);
          for (const item of nextItems) merged.set(item.id, item);
          return [...merged.values()];
        });

        setSourceProductsNextCursor(page.next_cursor);
      } catch (error: unknown) {
        if (seq !== sourceProductsRequestSeq.current) return;

        if (!append) {
          setSourceProducts([]);
          setSourceProductsNextCursor(null);
        }

        toast.error(
          "فشل جلب مخزون مصدر الحوالة: " + getErrorMessage(error)
        );
      } finally {
        if (seq === sourceProductsRequestSeq.current) {
          if (append) {
            setSourceProductsLoadingMore(false);
          } else {
            setSourceProductsLoading(false);
          }
        }
      }
    },
    [
      authenticatedFetch,
      createOpen,
      productSearch,
      sourceLocationId,
    ]
  );

  useEffect(() => {
    sourceProductsRequestSeq.current += 1;
    overrideRequestSeq.current = {};
    setSourceProducts([]);
    setSourceProductsNextCursor(null);
    setSourceProductsLoadingMore(false);
    setDraftItems([]);
    setOverrideOptionsByProduct({});
    setOverrideLoadingProductIds([]);
    setCreateRequestId(crypto.randomUUID());
  }, [createOpen, sourceLocationId]);

  useEffect(() => {
    void fetchSourceProducts(null, false);
  }, [fetchSourceProducts]);

  const addDraftProduct = (product: TransferSourceInventoryItem) => {
    if (
      draftItems.some(
        (item) => item.product_variant_id === product.id
      )
    ) {
      toast.info("الصنف مضاف للحوالة بالفعل.");
      return;
    }

    setDraftItems((prev) => [
      ...prev,
      {
        ...product,
        draft_key: crypto.randomUUID(),
        product_variant_id: product.id,
        cartons: 0,
        loose_packs: 0,
        fefo_mode: "auto",
        override_batch_id: null,
        override_reason_id: null,
        override_batch_available: null,
      },
    ]);
    resetCreateRequestId();
  };

  const removeDraftLine = (draftKey: string) => {
    setDraftItems((prev) =>
      prev.filter((item) => item.draft_key !== draftKey)
    );
    resetCreateRequestId();
  };

  const updateDraftQuantity = (
    draftKey: string,
    field: "cartons" | "loose_packs",
    value: number
  ) => {
    setDraftItems((prev) =>
      prev.map((item) => {
        if (item.draft_key !== draftKey) return item;

        const raw = Math.max(0, Math.floor(Number(value) || 0));
        const normalized =
          field === "loose_packs"
            ? Math.min(raw, Math.max(0, item.packs_per_carton - 1))
            : raw;

        return { ...item, [field]: normalized };
      })
    );
    resetCreateRequestId();
  };

  const loadOverrideOptions = useCallback(
    async (productId: number): Promise<TransferOverrideOptions | null> => {
      if (sourceLocationId === null) {
        toast.error("حدد مصدر الحوالة أولاً.");
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

        if (overrideRequestSeq.current[productId] !== nextSeq) {
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
        if (overrideRequestSeq.current[productId] === nextSeq) {
          toast.error(
            "فشل جلب خيارات تجاوز FEFO: " + getErrorMessage(error)
          );
        }
        return null;
      } finally {
        if (overrideRequestSeq.current[productId] === nextSeq) {
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
    ]
  );

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
        "احذف أسطر الدفعات الإضافية لهذا الصنف قبل العودة إلى FEFO التلقائي."
      );
      return;
    }

    if (mode === "override") {
      const options = await loadOverrideOptions(
        current.product_variant_id
      );
      if (!options) return;
      if (options.batches.length === 0) {
        toast.error("لا توجد دفعات متاحة لهذا الصنف في المصدر.");
        return;
      }
      if (options.reasons.length === 0) {
        toast.error(
          "لا توجد أسباب FEFO فعالة لهذه الشركة. لا يمكن تنفيذ التجاوز."
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
    resetCreateRequestId();
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
      toast.error("خيارات FEFO لم تعد تطابق مصدر الحوالة.");
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
      resetCreateRequestId();
      return;
    }

    const batch = options.batches.find(
      (item) => item.id === batchId
    );
    if (!batch) {
      toast.error("الدفعة المختارة ليست ضمن دفعات المصدر الحالية.");
      return;
    }

    const duplicate = draftItems.some(
      (item) =>
        item.draft_key !== draftKey &&
        item.product_variant_id === current.product_variant_id &&
        item.override_batch_id === batchId
    );
    if (duplicate) {
      toast.error("لا يجوز تكرار نفس الدفعة للصنف في الحوالة.");
      return;
    }

    setDraftItems((prev) =>
      prev.map((item) =>
        item.draft_key === draftKey
          ? {
              ...item,
              override_batch_id: batch.id,
              override_batch_available: batch.available_packs,
            }
          : item
      )
    );
    resetCreateRequestId();
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
      toast.error("سبب التجاوز غير صالح أو لم يعد فعالاً.");
      return;
    }

    setDraftItems((prev) =>
      prev.map((item) =>
        item.draft_key === draftKey
          ? { ...item, override_reason_id: reasonId }
          : item
      )
    );
    resetCreateRequestId();
  };

  const addOverrideBatchLine = async (productId: number) => {
    const existingLines = draftItems.filter(
      (item) => item.product_variant_id === productId
    );
    if (
      existingLines.length === 0 ||
      existingLines.some((item) => item.fefo_mode !== "override")
    ) {
      toast.error("إضافة دفعة أخرى متاحة فقط في وضع تجاوز FEFO.");
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
      toast.info("تمت إضافة كل الدفعات المتاحة لهذا الصنف.");
      return;
    }

    const template = existingLines[0];
    setDraftItems((prev) => [
      ...prev,
      {
        ...template,
        draft_key: crypto.randomUUID(),
        cartons: 0,
        loose_packs: 0,
        fefo_mode: "override",
        override_batch_id: null,
        override_reason_id: null,
        override_batch_available: null,
      },
    ]);
    resetCreateRequestId();
  };

  const updateCreateDirection = (value: string) => {
    if (value === "outgoing" || value === "incoming") {
      setCreateDirection(value);
      setCounterpartLocationId(null);
      resetCreateRequestId();
    }
  };

  const updateCounterpartLocation = (value: string) => {
    const nextId = Number(value);
    if (
      Number.isInteger(nextId) &&
      transferLocations.some(
        (item) => item.id === nextId && item.id !== locationId
      )
    ) {
      setCounterpartLocationId(nextId);
      resetCreateRequestId();
    } else {
      setCounterpartLocationId(null);
    }
  };

  const updateCreateNotes = (value: string) => {
    setCreateNotes(value);
    resetCreateRequestId();
  };

  const loadMoreSourceProducts = () => {
    if (!sourceProductsNextCursor) return;
    void fetchSourceProducts(sourceProductsNextCursor, true);
  };

  const handleDispatchTransfer = async () => {
    if (
      sourceLocationId === null ||
      destinationLocationId === null
    ) {
      toast.error("حدد الطرف الآخر للحوالة.");
      return;
    }

    if (sourceLocationId === destinationLocationId) {
      toast.error("المصدر والوجهة يجب أن يكونا مختلفين.");
      return;
    }

    if (
      counterpartLocationId === null ||
      !transferLocations.some(
        (item) => item.id === counterpartLocationId
      )
    ) {
      toast.error(
        "الطرف الآخر للحوالة غير موجود ضمن مواقع الشركة التي تم تحميلها."
      );
      return;
    }

    if (draftItems.length === 0) {
      toast.error("أضف صنفاً واحداً على الأقل للحوالة.");
      return;
    }

    type DispatchItem = {
      product_variant_id: number;
      quantity: number;
      is_fefo_override?: boolean;
      override_batch_id?: number;
      override_reason_id?: number;
    };

    let items: DispatchItem[];

    try {
      const modesByProduct = new Map<number, Set<FefoMode>>();
      for (const item of draftItems) {
        const modes =
          modesByProduct.get(item.product_variant_id) ??
          new Set<FefoMode>();
        modes.add(item.fefo_mode);
        modesByProduct.set(item.product_variant_id, modes);
      }

      if (
        [...modesByProduct.values()].some(
          (modes) => modes.size > 1
        )
      ) {
        throw new Error(
          "لا يجوز خلط FEFO التلقائي وتجاوز FEFO لنفس الصنف."
        );
      }

      const seenKeys = new Set<string>();

      items = draftItems.map((item) => {
        const quantity = totalDraftPacks(item);
        if (quantity <= 0) {
          throw new Error(`حدد كمية للصنف ${item.name}.`);
        }

        if (item.fefo_mode === "auto") {
          const key = `${item.product_variant_id}:auto`;
          if (seenKeys.has(key)) {
            throw new Error(
              `لا يجوز تكرار FEFO التلقائي للصنف ${item.name}.`
            );
          }
          seenKeys.add(key);

          if (quantity > item.available_packs) {
            throw new Error(
              `كمية ${item.name} تتجاوز المتاح في المصدر.`
            );
          }

          return {
            product_variant_id: item.product_variant_id,
            quantity,
            is_fefo_override: false,
          };
        }

        if (
          item.override_batch_id === null ||
          item.override_reason_id === null ||
          item.override_batch_available === null
        ) {
          throw new Error(
            `حدد الدفعة وسبب تجاوز FEFO للصنف ${item.name}.`
          );
        }

        const options =
          overrideOptionsByProduct[item.product_variant_id];
        if (
          !options ||
          options.location_id !== sourceLocationId ||
          options.product_variant_id !== item.product_variant_id
        ) {
          throw new Error(
            `خيارات FEFO للصنف ${item.name} لا تطابق مصدر الحوالة الحالي.`
          );
        }

        const batch = options.batches.find(
          (candidate) =>
            candidate.id === item.override_batch_id
        );
        const reason = options.reasons.find(
          (candidate) =>
            candidate.id === item.override_reason_id
        );
        if (!batch || !reason) {
          throw new Error(
            `دفعة أو سبب تجاوز FEFO للصنف ${item.name} لم يعد صالحاً.`
          );
        }

        if (quantity > batch.available_packs) {
          throw new Error(
            `كمية ${item.name} تتجاوز المتاح في الدفعة ${batch.batch_number}.`
          );
        }

        const key =
          `${item.product_variant_id}:${item.override_batch_id}`;
        if (seenKeys.has(key)) {
          throw new Error(
            `لا يجوز تكرار نفس الدفعة للصنف ${item.name}.`
          );
        }
        seenKeys.add(key);

        return {
          product_variant_id: item.product_variant_id,
          quantity,
          is_fefo_override: true,
          override_batch_id: item.override_batch_id,
          override_reason_id: item.override_reason_id,
        };
      });
    } catch (error: unknown) {
      toast.error(getErrorMessage(error));
      return;
    }

    if (createNotes.trim().length > 4000) {
      toast.error("ملاحظات الحوالة لا يجوز أن تتجاوز 4000 حرف.");
      return;
    }

    setCreateSubmitting(true);

    try {
      const raw = await authenticatedFetch(
        "/warehouse/unified/transfer/dispatch",
        {
          method: "POST",
          body: JSON.stringify({
            request_id: createRequestId,
            source_location_id: sourceLocationId,
            destination_location_id: destinationLocationId,
            items,
            notes: createNotes.trim(),
          }),
        }
      );

      toast.success(getMutationMessage(raw));
      setCreateOpen(false);
      resetCreateForm();
      onCompleted();
      await onInventoryChanged();
    } catch (error: unknown) {
      toast.error(getErrorMessage(error));
    } finally {
      setCreateSubmitting(false);
    }
  };

  return {
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
    openCreate,
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
  };
}

export type TransferCreateController = ReturnType<typeof useTransferCreate>;
