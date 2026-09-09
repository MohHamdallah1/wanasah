import { useCallback, useEffect, useRef, useState } from "react";
import {
  Plus,
  RefreshCcw,
  Search,
  Trash2,
  Truck,
} from "lucide-react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";

import {
  TRANSFER_STATUSES,
  isTransferStatus,
  STATUS_META,
} from "./transfers/constants";
import {
  parseOverrideOptions,
  parseSourceInventoryPage,
  parseTransferLocations,
} from "./transfers/parsers";
import type {
  FefoMode,
  Props,
  TransferCreateDirection,
  TransferDraftItem,
  TransferLocationOption,
  TransferOverrideOptions,
  TransferSourceInventoryItem,
} from "./transfers/types";
import {
  getErrorMessage,
  getMutationMessage,
  totalDraftPacks,
} from "./transfers/utils";
import { TransferTable } from "./transfers/TransferTable";
import { TransferDetailModal } from "./transfers/TransferDetailModal";
import { TransferDecisionModal } from "./transfers/TransferDecisionModal";
import { useTransferList } from "./transfers/hooks/useTransferList";
import { useTransferActions } from "./transfers/hooks/useTransferActions";

export function TabTransfers({
  locationId,
  onInventoryChanged,
}: Props) {
  const authenticatedFetch = useAuthFetch();

  const transferList = useTransferList(locationId);
  const {
    items,
    status,
    setStatus,
    direction,
    setDirection,
    searchInput,
    setSearchInput,
    total,
    loading,
    cursorHistory,
    nextCursor,
    detail,
    detailLoading,
    inTransitCount,
    openDetail,
    closeDetail,
    resetDetail,
    refreshTransfers,
    handleNext,
    handlePrevious,
  } = transferList;

  const handleTransferActionCompleted = useCallback(() => {
    resetDetail();
    refreshTransfers();
  }, [refreshTransfers, resetDetail]);

  const transferActions = useTransferActions({
    locationId,
    onInventoryChanged,
    onCompleted: handleTransferActionCompleted,
  });
  const {
    action,
    actionTransfer,
    decisionReason,
    actionSubmitting,
    openAction,
    closeAction,
    updateDecisionReason,
    handleAction,
  } = transferActions;

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
      refreshTransfers();
      await onInventoryChanged();
    } catch (error: unknown) {
      toast.error(getErrorMessage(error));
    } finally {
      setCreateSubmitting(false);
    }
  };


  return (
    <div className="flex flex-col gap-4 min-h-0 flex-1">
      <div className="glass-card rounded-2xl p-4 flex items-center justify-between gap-4">
        <div>
          <h2 className="font-black text-slate-800 flex items-center gap-2">
            <Truck className="w-5 h-5 text-blue-600" />
            الحوالات الموحّدة
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            الموقع #{locationId} ·{" "}
            {total !== null ? `${total} حوالة` : "—"} ·{" "}
            {inTransitCount} في الطريق بهذه الصفحة
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={openCreate}
            className="px-4 py-2 rounded-xl bg-blue-600 text-white font-bold text-sm flex items-center gap-2"
          >
            <Plus className="w-4 h-4" />
            حوالة جديدة
          </button>

          <button
            onClick={refreshTransfers}
            disabled={loading}
            className="px-3 py-2 rounded-xl border border-slate-200 bg-white text-slate-600 font-bold text-xs disabled:opacity-50"
            title="تحديث"
          >
            <RefreshCcw
              className={`w-4 h-4 ${loading ? "animate-spin" : ""}`}
            />
          </button>
        </div>
      </div>

      <div className="glass-card rounded-2xl p-4 grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="relative">
          <Search className="w-4 h-4 absolute right-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="بحث برقم الحوالة"
            maxLength={100}
            className="w-full pr-10 pl-3 py-2.5 rounded-xl border border-slate-200 bg-white text-sm outline-none focus:ring-2 focus:ring-blue-500/20"
          />
        </div>

        <select
          value={status}
          onChange={(event) => {
            const value = event.target.value;
            setStatus(value && isTransferStatus(value) ? value : "");
          }}
          className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none"
        >
          <option value="">كل الحالات</option>
          {TRANSFER_STATUSES.map((value) => (
            <option key={value} value={value}>
              {STATUS_META[value].label}
            </option>
          ))}
        </select>

        <select
          value={direction}
          onChange={(event) => {
            const value = event.target.value;
            if (
              value === "all" ||
              value === "source" ||
              value === "destination"
            ) {
              setDirection(value);
            }
          }}
          className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none"
        >
          <option value="all">كل الاتجاهات</option>
          <option value="source">صادرة من المستودع</option>
          <option value="destination">واردة إلى المستودع</option>
        </select>
      </div>

      <TransferTable
        items={items}
        locationId={locationId}
        loading={loading}
        cursorHistoryLength={cursorHistory.length}
        nextCursor={nextCursor}
        onOpenDetail={openDetail}
        onOpenAction={openAction}
        onPrevious={handlePrevious}
        onNext={handleNext}
      />

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
                onChange={(event) => {
                  const value = event.target.value;
                  if (value === "outgoing" || value === "incoming") {
                    setCreateDirection(value);
                    setCounterpartLocationId(null);
                    resetCreateRequestId();
                  }
                }}
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none"
              >
                <option value="outgoing">
                  صادرة من المستودع المحدد
                </option>
                <option value="incoming">
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
                onChange={(event) => {
                  const nextId = Number(event.target.value);
                  if (
                    Number.isInteger(nextId) &&
                    transferLocations.some(
                      (item) =>
                        item.id === nextId && item.id !== locationId
                    )
                  ) {
                    setCounterpartLocationId(nextId);
                    resetCreateRequestId();
                  } else {
                    setCounterpartLocationId(null);
                  }
                }}
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
                      onClick={() =>
                        void fetchSourceProducts(
                          sourceProductsNextCursor,
                          true
                        )
                      }
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
                  const firstProductLineKey = draftItems.find(
                    (candidate) =>
                      candidate.product_variant_id ===
                      item.product_variant_id
                  )?.draft_key;

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

                      <div className="mt-3">
                        <label className="text-[10px] font-bold text-slate-500">
                          سياسة اختيار الدفعة
                        </label>
                        <select
                          value={item.fefo_mode}
                          onChange={(event) => {
                            const mode = event.target.value;
                            if (
                              mode === "auto" ||
                              mode === "override"
                            ) {
                              void setDraftFefoMode(
                                item.draft_key,
                                mode
                              );
                            }
                          }}
                          className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs"
                        >
                          <option value="auto">
                            FEFO تلقائي — الموصى به
                          </option>
                          <option value="override">
                            تجاوز FEFO موثّق
                          </option>
                        </select>
                      </div>

                      {item.fefo_mode === "override" && (
                        <div className="mt-3 rounded-xl border border-amber-200 bg-white p-3 space-y-3">
                          <div className="text-[11px] font-bold text-amber-800">
                            تجاوز FEFO استثناء رقابي. يجب تحديد
                            دفعة وسبب معتمد، وسيتم تسجيل المشرف
                            والسبب في سجل التدقيق.
                          </div>

                          {overrideLoading && (
                            <div className="text-xs text-slate-400">
                              جاري جلب دفعات المصدر وأسباب التجاوز...
                            </div>
                          )}

                          {!overrideLoading && options && (
                            <>
                              <div>
                                <label className="text-[10px] font-bold text-slate-500">
                                  الدفعة المختارة
                                </label>
                                <select
                                  value={item.override_batch_id ?? ""}
                                  onChange={(event) => {
                                    const value = event.target.value;
                                    setOverrideBatch(
                                      item.draft_key,
                                      value
                                        ? Number(value)
                                        : null
                                    );
                                  }}
                                  className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs"
                                >
                                  <option value="">
                                    اختر دفعة
                                  </option>
                                  {options.batches
                                    .filter(
                                      (batch) =>
                                        batch.id ===
                                          item.override_batch_id ||
                                        !draftItems.some(
                                          (candidate) =>
                                            candidate.draft_key !==
                                              item.draft_key &&
                                            candidate.product_variant_id ===
                                              item.product_variant_id &&
                                            candidate.override_batch_id ===
                                              batch.id
                                        )
                                    )
                                    .map((batch) => (
                                      <option
                                        key={batch.id}
                                        value={batch.id}
                                      >
                                        {batch.batch_number} — صلاحية{" "}
                                        {batch.expiry_date} — متاح{" "}
                                        {batch.available_packs}
                                        {batch.is_fefo_head
                                          ? " — FEFO الحالي"
                                          : ""}
                                      </option>
                                    ))}
                                </select>
                              </div>

                              <div>
                                <label className="text-[10px] font-bold text-slate-500">
                                  سبب التجاوز
                                </label>
                                <select
                                  value={item.override_reason_id ?? ""}
                                  onChange={(event) => {
                                    const value = event.target.value;
                                    setOverrideReason(
                                      item.draft_key,
                                      value
                                        ? Number(value)
                                        : null
                                    );
                                  }}
                                  className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs"
                                >
                                  <option value="">
                                    اختر سبباً معتمداً
                                  </option>
                                  {options.reasons.map((reason) => (
                                    <option
                                      key={reason.id}
                                      value={reason.id}
                                    >
                                      {reason.code} —{" "}
                                      {reason.description}
                                    </option>
                                  ))}
                                </select>
                              </div>

                              {selectedBatch && (
                                <div className="text-[10px] text-slate-500">
                                  المتاح في الدفعة المختارة:{" "}
                                  <span className="font-bold">
                                    {selectedBatch.available_packs} حبة
                                  </span>
                                  {selectedBatch.is_fefo_head && (
                                    <span className="text-amber-700">
                                      {" "}
                                      — هذه الدفعة هي FEFO الحالية؛
                                      التجاوز غير ضروري عادةً.
                                    </span>
                                  )}
                                </div>
                              )}

                              {item.draft_key ===
                                firstProductLineKey && (
                                <button
                                  type="button"
                                  onClick={() =>
                                    void addOverrideBatchLine(
                                      item.product_variant_id
                                    )
                                  }
                                  className="text-xs font-bold text-amber-700 hover:text-amber-900"
                                >
                                  + تقسيم نفس الصنف على دفعة أخرى
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      )}

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
              onChange={(event) => {
                setCreateNotes(event.target.value);
                resetCreateRequestId();
              }}
              maxLength={4000}
              className="mt-1 w-full min-h-24 rounded-xl border border-slate-200 px-3 py-2.5 outline-none"
            />
          </div>

          <button
            onClick={() => void handleDispatchTransfer()}
            disabled={
              createSubmitting ||
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

      <TransferDetailModal
        detail={detail}
        loading={detailLoading}
        onClose={closeDetail}
      />

      <TransferDecisionModal
        action={action}
        transfer={actionTransfer}
        decisionReason={decisionReason}
        submitting={actionSubmitting}
        onClose={closeAction}
        onDecisionReasonChange={updateDecisionReason}
        onSubmit={handleAction}
      />
    </div>
  );
}
