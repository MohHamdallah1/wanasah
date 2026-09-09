import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  Ban,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Eye,
  Plus,
  RefreshCcw,
  Search,
  Trash2,
  Truck,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";

type TransferStatus =
  | "DRAFT"
  | "PENDING"
  | "IN_TRANSIT"
  | "ACCEPTED"
  | "REJECTED"
  | "POSTED"
  | "CANCELLED";

type TransferDirection = "all" | "source" | "destination";
type TransferAction = "receive" | "reject" | "cancel";

interface WarehouseTransferListItem {
  id: number;
  reference_number: string;
  source_location_id: number;
  source_location_name: string;
  destination_location_id: number;
  destination_location_name: string;
  status: TransferStatus;
  dispatched_by: number;
  dispatched_by_name: string;
  received_by: number | null;
  received_by_name: string | null;
  cancelled_by: number | null;
  cancelled_by_name: string | null;
  line_count: number;
  total_quantity: number;
  notes: string | null;
  decision_reason: string | null;
  created_at: string;
  updated_at: string;
  accepted_at: string | null;
  rejected_at: string | null;
  cancelled_at: string | null;
  posted_at: string | null;
}

interface WarehouseTransferCursorPage {
  items: WarehouseTransferListItem[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
}

interface WarehouseTransferLine {
  id: number;
  product_variant_id: number;
  product_name: string;
  batch_id: number;
  batch_number: string;
  expiry_date: string;
  quantity: number;
  fefo_override_reason_id: number | null;
  fefo_overridden_by: number | null;
  fefo_override_note: string | null;
}

interface WarehouseTransferDetail {
  transfer: WarehouseTransferListItem;
  lines: WarehouseTransferLine[];
}

interface Props {
  locationId: number;
  onInventoryChanged: () => void | Promise<void>;
}


type TransferCreateDirection = "outgoing" | "incoming";

interface TransferLocationOption {
  id: number;
  name: string;
  code: string;
  location_type: "WAREHOUSE" | "VEHICLE";
  vehicle_id: number | null;
}

interface TransferSourceInventoryItem {
  id: number;
  name: string;
  sku: string | null;
  packs_per_carton: number;
  available_packs: number;
}

interface TransferSourceInventoryPage {
  items: TransferSourceInventoryItem[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
}

type FefoMode = "auto" | "override";

interface TransferOverrideReason {
  id: number;
  code: string;
  description: string;
}

interface TransferOverrideBatch {
  id: number;
  batch_number: string;
  production_date: string | null;
  expiry_date: string;
  available_packs: number;
  is_fefo_head: boolean;
}

interface TransferOverrideOptions {
  location_id: number;
  product_variant_id: number;
  fefo_batch_id: number | null;
  batches: TransferOverrideBatch[];
  reasons: TransferOverrideReason[];
}

interface TransferDraftItem extends TransferSourceInventoryItem {
  draft_key: string;
  product_variant_id: number;
  cartons: number;
  loose_packs: number;
  fefo_mode: FefoMode;
  override_batch_id: number | null;
  override_reason_id: number | null;
  override_batch_available: number | null;
}

const TRANSFER_STATUSES: TransferStatus[] = [
  "DRAFT",
  "PENDING",
  "IN_TRANSIT",
  "ACCEPTED",
  "REJECTED",
  "POSTED",
  "CANCELLED",
];

const STATUS_META: Record<
  TransferStatus,
  { label: string; className: string }
> = {
  DRAFT: { label: "مسودة", className: "bg-slate-100 text-slate-600" },
  PENDING: { label: "معلقة", className: "bg-amber-50 text-amber-700" },
  IN_TRANSIT: { label: "في الطريق", className: "bg-blue-50 text-blue-700" },
  ACCEPTED: { label: "مقبولة", className: "bg-cyan-50 text-cyan-700" },
  REJECTED: { label: "مرفوضة", className: "bg-red-50 text-red-700" },
  POSTED: { label: "مستلمة", className: "bg-emerald-50 text-emerald-700" },
  CANCELLED: { label: "ملغاة", className: "bg-slate-100 text-slate-500" },
};

const isTransferStatus = (value: unknown): value is TransferStatus =>
  typeof value === "string" &&
  TRANSFER_STATUSES.includes(value as TransferStatus);

const positiveInt = (value: unknown, field: string): number => {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value <= 0
  ) {
    throw new Error(`حقل ${field} غير صالح.`);
  }
  return value;
};

const nonNegativeInt = (value: unknown, field: string): number => {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 0
  ) {
    throw new Error(`حقل ${field} غير صالح.`);
  }
  return value;
};

const requiredString = (value: unknown, field: string): string => {
  if (typeof value !== "string" || !value) {
    throw new Error(`حقل ${field} غير صالح.`);
  }
  return value;
};

const optionalString = (value: unknown): string | null =>
  typeof value === "string" ? value : null;

const optionalPositiveInt = (value: unknown): number | null =>
  typeof value === "number" &&
  Number.isInteger(value) &&
  value > 0
    ? value
    : null;

const parseTransfer = (raw: unknown): WarehouseTransferListItem => {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("بيانات الحوالة غير صالحة.");
  }

  const row = raw as Record<string, unknown>;
  if (!isTransferStatus(row.status)) {
    throw new Error("حالة الحوالة غير معروفة.");
  }

  return {
    id: positiveInt(row.id, "id"),
    reference_number: requiredString(
      row.reference_number,
      "reference_number"
    ),
    source_location_id: positiveInt(
      row.source_location_id,
      "source_location_id"
    ),
    source_location_name: requiredString(
      row.source_location_name,
      "source_location_name"
    ),
    destination_location_id: positiveInt(
      row.destination_location_id,
      "destination_location_id"
    ),
    destination_location_name: requiredString(
      row.destination_location_name,
      "destination_location_name"
    ),
    status: row.status,
    dispatched_by: positiveInt(row.dispatched_by, "dispatched_by"),
    dispatched_by_name: requiredString(
      row.dispatched_by_name,
      "dispatched_by_name"
    ),
    received_by: optionalPositiveInt(row.received_by),
    received_by_name: optionalString(row.received_by_name),
    cancelled_by: optionalPositiveInt(row.cancelled_by),
    cancelled_by_name: optionalString(row.cancelled_by_name),
    line_count: nonNegativeInt(row.line_count, "line_count"),
    total_quantity: nonNegativeInt(
      row.total_quantity,
      "total_quantity"
    ),
    notes: optionalString(row.notes),
    decision_reason: optionalString(row.decision_reason),
    created_at: requiredString(row.created_at, "created_at"),
    updated_at: requiredString(row.updated_at, "updated_at"),
    accepted_at: optionalString(row.accepted_at),
    rejected_at: optionalString(row.rejected_at),
    cancelled_at: optionalString(row.cancelled_at),
    posted_at: optionalString(row.posted_at),
  };
};

const parseTransferPage = (raw: unknown): WarehouseTransferCursorPage => {
  if (
    typeof raw !== "object" ||
    raw === null ||
    !Array.isArray((raw as { items?: unknown }).items)
  ) {
    throw new Error("تنسيق صفحة الحوالات غير صالح.");
  }

  const page = raw as Record<string, unknown>;

  return {
    items: (page.items as unknown[]).map(parseTransfer),
    next_cursor:
      typeof page.next_cursor === "string" ? page.next_cursor : null,
    has_more: page.has_more === true,
    total: typeof page.total === "number" ? page.total : null,
  };
};

const parseTransferLine = (raw: unknown): WarehouseTransferLine => {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("سطر حوالة غير صالح.");
  }

  const row = raw as Record<string, unknown>;

  return {
    id: positiveInt(row.id, "line.id"),
    product_variant_id: positiveInt(
      row.product_variant_id,
      "product_variant_id"
    ),
    product_name: requiredString(row.product_name, "product_name"),
    batch_id: positiveInt(row.batch_id, "batch_id"),
    batch_number: requiredString(row.batch_number, "batch_number"),
    expiry_date: requiredString(row.expiry_date, "expiry_date"),
    quantity: positiveInt(row.quantity, "quantity"),
    fefo_override_reason_id: optionalPositiveInt(
      row.fefo_override_reason_id
    ),
    fefo_overridden_by: optionalPositiveInt(row.fefo_overridden_by),
    fefo_override_note: optionalString(row.fefo_override_note),
  };
};

const parseTransferDetail = (
  raw: unknown,
  expectedLocationId: number
): WarehouseTransferDetail => {
  if (
    typeof raw !== "object" ||
    raw === null ||
    !("transfer" in raw) ||
    !("lines" in raw) ||
    !Array.isArray((raw as { lines?: unknown }).lines)
  ) {
    throw new Error("تنسيق تفاصيل الحوالة غير صالح.");
  }

  const record = raw as Record<string, unknown>;
  const transfer = parseTransfer(record.transfer);

  if (
    transfer.source_location_id !== expectedLocationId &&
    transfer.destination_location_id !== expectedLocationId
  ) {
    throw new Error(
      "مرفوض: تفاصيل الحوالة لا تطابق المستودع المحدد حالياً."
    );
  }

  const lines = (record.lines as unknown[]).map(parseTransferLine);
  if (lines.length === 0) {
    throw new Error("الحوالة لا تحتوي على أسطر مخزون.");
  }

  return { transfer, lines };
};


const parseTransferLocation = (raw: unknown): TransferLocationOption => {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("موقع حوالة غير صالح.");
  }

  const row = raw as Record<string, unknown>;
  const locationType = row.location_type;
  if (locationType !== "WAREHOUSE" && locationType !== "VEHICLE") {
    throw new Error("نوع موقع الحوالة غير صالح.");
  }

  return {
    id: positiveInt(row.id, "location.id"),
    name: requiredString(row.name, "location.name"),
    code: requiredString(row.code, "location.code"),
    location_type: locationType,
    vehicle_id: optionalPositiveInt(row.vehicle_id),
  };
};

const parseTransferLocations = (raw: unknown): TransferLocationOption[] => {
  if (!Array.isArray(raw)) {
    throw new Error("تنسيق مواقع الحوالة غير صالح.");
  }

  return raw.map(parseTransferLocation);
};

const parseSourceInventoryItem = (
  raw: unknown
): TransferSourceInventoryItem => {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("صنف مصدر الحوالة غير صالح.");
  }

  const row = raw as Record<string, unknown>;

  return {
    id: positiveInt(row.id, "product.id"),
    name: requiredString(row.name, "product.name"),
    sku: optionalString(row.sku),
    packs_per_carton: positiveInt(
      row.packs_per_carton,
      "packs_per_carton"
    ),
    available_packs: nonNegativeInt(
      row.available_packs,
      "available_packs"
    ),
  };
};

const parseSourceInventoryPage = (
  raw: unknown
): TransferSourceInventoryPage => {
  if (
    typeof raw !== "object" ||
    raw === null ||
    !Array.isArray((raw as { items?: unknown }).items)
  ) {
    throw new Error("تنسيق مخزون مصدر الحوالة غير صالح.");
  }

  const page = raw as Record<string, unknown>;

  return {
    items: (page.items as unknown[]).map(parseSourceInventoryItem),
    next_cursor:
      typeof page.next_cursor === "string" ? page.next_cursor : null,
    has_more: page.has_more === true,
    total: typeof page.total === "number" ? page.total : null,
  };
};

const parseOverrideReason = (raw: unknown): TransferOverrideReason => {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("سبب تجاوز FEFO غير صالح.");
  }

  const row = raw as Record<string, unknown>;
  return {
    id: positiveInt(row.id, "override_reason.id"),
    code: requiredString(row.code, "override_reason.code"),
    description: requiredString(
      row.description,
      "override_reason.description"
    ),
  };
};

const parseOverrideBatch = (raw: unknown): TransferOverrideBatch => {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("دفعة تجاوز FEFO غير صالحة.");
  }

  const row = raw as Record<string, unknown>;
  if (typeof row.is_fefo_head !== "boolean") {
    throw new Error("حالة FEFO للدفعة غير صالحة.");
  }

  return {
    id: positiveInt(row.id, "batch.id"),
    batch_number: requiredString(row.batch_number, "batch.batch_number"),
    production_date: optionalString(row.production_date),
    expiry_date: requiredString(row.expiry_date, "batch.expiry_date"),
    available_packs: nonNegativeInt(
      row.available_packs,
      "batch.available_packs"
    ),
    is_fefo_head: row.is_fefo_head,
  };
};

const parseOverrideOptions = (
  raw: unknown,
  expectedLocationId: number,
  expectedProductId: number
): TransferOverrideOptions => {
  if (
    typeof raw !== "object" ||
    raw === null ||
    !Array.isArray((raw as { batches?: unknown }).batches) ||
    !Array.isArray((raw as { reasons?: unknown }).reasons)
  ) {
    throw new Error("تنسيق خيارات تجاوز FEFO غير صالح.");
  }

  const row = raw as Record<string, unknown>;
  const locationId = positiveInt(row.location_id, "location_id");
  const productId = positiveInt(
    row.product_variant_id,
    "product_variant_id"
  );

  if (
    locationId !== expectedLocationId ||
    productId !== expectedProductId
  ) {
    throw new Error(
      "مرفوض: خيارات FEFO لا تطابق مصدر الحوالة أو الصنف المحدد."
    );
  }

  const batches = (row.batches as unknown[]).map(parseOverrideBatch);
  const reasons = (row.reasons as unknown[]).map(parseOverrideReason);
  const fefoBatchId = optionalPositiveInt(row.fefo_batch_id);

  if (
    fefoBatchId !== null &&
    !batches.some((batch) => batch.id === fefoBatchId)
  ) {
    throw new Error("دفعة FEFO المرجعية غير موجودة ضمن الخيارات.");
  }

  return {
    location_id: locationId,
    product_variant_id: productId,
    fefo_batch_id: fefoBatchId,
    batches,
    reasons,
  };
};

const totalDraftPacks = (item: TransferDraftItem): number =>
  item.cartons * item.packs_per_carton + item.loose_packs;

const getErrorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : "حدث خطأ غير متوقع";

const getMutationMessage = (raw: unknown): string => {
  if (
    typeof raw !== "object" ||
    raw === null ||
    typeof (raw as { message?: unknown }).message !== "string"
  ) {
    throw new Error("استجابة عملية الحوالة غير صالحة.");
  }

  return (raw as { message: string }).message;
};

const formatDate = (value: string | null): string =>
  value ? new Date(value).toLocaleString("ar-EG") : "—";

export function TabTransfers({
  locationId,
  onInventoryChanged,
}: Props) {
  const authenticatedFetch = useAuthFetch();

  const [items, setItems] = useState<WarehouseTransferListItem[]>([]);
  const [status, setStatus] = useState<TransferStatus | "">("");
  const [direction, setDirection] =
    useState<TransferDirection>("all");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>(
    []
  );
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const requestSeq = useRef(0);

  const [detail, setDetail] = useState<WarehouseTransferDetail | null>(
    null
  );
  const [detailLoading, setDetailLoading] = useState(false);
  const detailRequestSeq = useRef(0);

  const [action, setAction] = useState<TransferAction | null>(null);
  const [actionTransfer, setActionTransfer] =
    useState<WarehouseTransferListItem | null>(null);
  const [decisionReason, setDecisionReason] = useState("");
  const [actionRequestId, setActionRequestId] = useState(() =>
    crypto.randomUUID()
  );
  const [actionSubmitting, setActionSubmitting] = useState(false);

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
      const clean = searchInput.trim();
      setSearch(clean.length >= 2 ? clean : "");
      setCursor(null);
      setCursorHistory([]);
      setNextCursor(null);
      setTotal(null);
    }, 300);

    return () => window.clearTimeout(timer);
  }, [searchInput]);

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

  useEffect(() => {
    setCursor(null);
    setCursorHistory([]);
    setNextCursor(null);
    setTotal(null);
    setDetail(null);
  }, [locationId, status, direction]);

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
      setRefreshKey((value) => value + 1);
      await onInventoryChanged();
    } catch (error: unknown) {
      toast.error(getErrorMessage(error));
    } finally {
      setCreateSubmitting(false);
    }
  };


  const fetchTransfers = useCallback(async () => {
    const seq = ++requestSeq.current;
    setLoading(true);

    try {
      const params = new URLSearchParams({
        location_id: String(locationId),
        direction,
        limit: "50",
      });
      if (status) params.set("status", status);
      if (search) params.set("search", search);
      if (cursor) params.set("cursor", cursor);

      const raw = await authenticatedFetch(
        `/warehouse/unified/transfers?${params.toString()}`
      );

      if (seq !== requestSeq.current) return;

      const page = parseTransferPage(raw);
      const invalid = page.items.find(
        (transfer) =>
          transfer.source_location_id !== locationId &&
          transfer.destination_location_id !== locationId
      );

      if (invalid) {
        throw new Error(
          "مرفوض: السيرفر أعاد حوالة خارج نطاق المستودع المحدد."
        );
      }

      setItems(page.items);
      setNextCursor(page.next_cursor);
      if (page.total !== null) setTotal(page.total);
    } catch (error: unknown) {
      if (seq !== requestSeq.current) return;
      setItems([]);
      setNextCursor(null);
      toast.error("فشل جلب الحوالات: " + getErrorMessage(error));
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [
    authenticatedFetch,
    cursor,
    direction,
    locationId,
    search,
    status,
  ]);

  useEffect(() => {
    void fetchTransfers();
  }, [fetchTransfers, refreshKey]);

  const openDetail = async (transfer: WarehouseTransferListItem) => {
    const seq = ++detailRequestSeq.current;
    setDetailLoading(true);
    setDetail(null);

    try {
      const raw = await authenticatedFetch(
        `/warehouse/unified/transfers/${transfer.id}`
      );

      if (seq !== detailRequestSeq.current) return;

      setDetail(parseTransferDetail(raw, locationId));
    } catch (error: unknown) {
      if (seq !== detailRequestSeq.current) return;
      toast.error(
        "فشل جلب تفاصيل الحوالة: " + getErrorMessage(error)
      );
    } finally {
      if (seq === detailRequestSeq.current) setDetailLoading(false);
    }
  };

  const openAction = (
    transfer: WarehouseTransferListItem,
    nextAction: TransferAction
  ) => {
    if (transfer.status !== "IN_TRANSIT") {
      toast.error("هذه العملية متاحة فقط للحوالات الموجودة في الطريق.");
      return;
    }

    const isSource = transfer.source_location_id === locationId;
    const isDestination =
      transfer.destination_location_id === locationId;

    if (nextAction === "cancel" && !isSource) {
      toast.error("الإلغاء متاح من جهة مصدر الحوالة فقط.");
      return;
    }
    if (
      (nextAction === "receive" || nextAction === "reject") &&
      !isDestination
    ) {
      toast.error("الاستلام/الرفض متاحان من جهة وجهة الحوالة فقط.");
      return;
    }

    setActionTransfer(transfer);
    setAction(nextAction);
    setDecisionReason("");
    setActionRequestId(crypto.randomUUID());
  };

  const closeAction = () => {
    if (actionSubmitting) return;
    setAction(null);
    setActionTransfer(null);
    setDecisionReason("");
  };

  const handleAction = async () => {
    if (!action || !actionTransfer) return;

    const reason = decisionReason.trim();
    if ((action === "reject" || action === "cancel") && !reason) {
      toast.error("سبب القرار مطلوب.");
      return;
    }
    if (reason.length > 2000) {
      toast.error("سبب القرار لا يجوز أن يتجاوز 2000 حرف.");
      return;
    }

    setActionSubmitting(true);

    try {
      let raw: unknown;

      if (action === "receive") {
        raw = await authenticatedFetch(
          "/warehouse/unified/transfer/receive",
          {
            method: "POST",
            body: JSON.stringify({
              request_id: actionRequestId,
              transfer_header_id: actionTransfer.id,
              destination_location_id:
                actionTransfer.destination_location_id,
            }),
          }
        );
      } else {
        raw = await authenticatedFetch(
          `/warehouse/unified/transfer/${actionTransfer.id}/${action}`,
          {
            method: "POST",
            body: JSON.stringify({
              request_id: actionRequestId,
              decision_reason: reason,
            }),
          }
        );
      }

      toast.success(getMutationMessage(raw));
      setAction(null);
      setActionTransfer(null);
      setDecisionReason("");
      setDetail(null);
      setRefreshKey((value) => value + 1);
      await onInventoryChanged();
    } catch (error: unknown) {
      // Keep the same request_id for an unchanged safe retry.
      toast.error(getErrorMessage(error));
    } finally {
      setActionSubmitting(false);
    }
  };

  const handleNext = () => {
    if (!nextCursor) return;
    setCursorHistory((prev) => [...prev, cursor]);
    setCursor(nextCursor);
  };

  const handlePrevious = () => {
    if (cursorHistory.length === 0) return;
    const previous = cursorHistory[cursorHistory.length - 1] ?? null;
    setCursorHistory((prev) => prev.slice(0, -1));
    setCursor(previous);
  };

  const inTransitCount = useMemo(
    () => items.filter((item) => item.status === "IN_TRANSIT").length,
    [items]
  );

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
            onClick={() => setRefreshKey((value) => value + 1)}
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

      <div className="glass-card rounded-2xl overflow-hidden min-h-0 flex-1">
        <div className="overflow-auto h-full">
          <table className="w-full text-sm text-right">
            <thead className="bg-slate-50 sticky top-0 z-10">
              <tr>
                <th className="p-3">الحوالة</th>
                <th className="p-3">المصدر</th>
                <th className="p-3">الوجهة</th>
                <th className="p-3">الحالة</th>
                <th className="p-3">الأصناف</th>
                <th className="p-3">إجمالي العبوات</th>
                <th className="p-3">أنشأها</th>
                <th className="p-3">التاريخ</th>
                <th className="p-3 text-center">إجراءات</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-slate-100">
              {items.map((transfer) => {
                const isSource =
                  transfer.source_location_id === locationId;
                const isDestination =
                  transfer.destination_location_id === locationId;
                const inTransit = transfer.status === "IN_TRANSIT";

                return (
                  <tr key={transfer.id} className="hover:bg-slate-50/70">
                    <td className="p-3">
                      <div className="font-bold text-slate-800">
                        {transfer.reference_number}
                      </div>
                      <div className="text-[10px] text-slate-400">
                        ID: {transfer.id}
                      </div>
                    </td>
                    <td className="p-3">
                      <div className="flex items-center gap-1.5">
                        <ArrowUpFromLine className="w-3.5 h-3.5 text-slate-400" />
                        <span className={isSource ? "font-bold text-blue-700" : "text-slate-600"}>
                          {transfer.source_location_name}
                        </span>
                      </div>
                    </td>
                    <td className="p-3">
                      <div className="flex items-center gap-1.5">
                        <ArrowDownToLine className="w-3.5 h-3.5 text-slate-400" />
                        <span className={isDestination ? "font-bold text-emerald-700" : "text-slate-600"}>
                          {transfer.destination_location_name}
                        </span>
                      </div>
                    </td>
                    <td className="p-3">
                      <span className={`px-2 py-1 rounded-lg text-xs font-bold ${STATUS_META[transfer.status].className}`}>
                        {STATUS_META[transfer.status].label}
                      </span>
                    </td>
                    <td className="p-3 text-slate-600">
                      {transfer.line_count}
                    </td>
                    <td className="p-3 font-bold text-slate-700">
                      {transfer.total_quantity}
                    </td>
                    <td className="p-3 text-slate-600">
                      {transfer.dispatched_by_name}
                    </td>
                    <td className="p-3 text-xs text-slate-500">
                      {formatDate(transfer.created_at)}
                    </td>
                    <td className="p-3">
                      <div className="flex justify-center gap-1.5">
                        <button
                          onClick={() => void openDetail(transfer)}
                          className="p-2 rounded-lg border border-slate-200 text-slate-600 hover:text-blue-600"
                          title="التفاصيل"
                        >
                          <Eye className="w-4 h-4" />
                        </button>

                        {inTransit && isDestination && (
                          <>
                            <button
                              onClick={() => openAction(transfer, "receive")}
                              className="p-2 rounded-lg border border-emerald-200 text-emerald-600 hover:bg-emerald-50"
                              title="استلام"
                            >
                              <CheckCircle2 className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => openAction(transfer, "reject")}
                              className="p-2 rounded-lg border border-red-200 text-red-600 hover:bg-red-50"
                              title="رفض"
                            >
                              <XCircle className="w-4 h-4" />
                            </button>
                          </>
                        )}

                        {inTransit && isSource && (
                          <button
                            onClick={() => openAction(transfer, "cancel")}
                            className="p-2 rounded-lg border border-amber-200 text-amber-600 hover:bg-amber-50"
                            title="إلغاء"
                          >
                            <Ban className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}

              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={9} className="p-12 text-center text-slate-400">
                    لا توجد حوالات ضمن النطاق المحدد.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-500">
          الصفحة {cursorHistory.length + 1}
        </span>

        <div className="flex gap-2">
          <button
            onClick={handlePrevious}
            disabled={cursorHistory.length === 0 || loading}
            className="px-3 py-2 rounded-xl border border-slate-200 bg-white disabled:opacity-40"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
          <button
            onClick={handleNext}
            disabled={!nextCursor || loading}
            className="px-3 py-2 rounded-xl border border-slate-200 bg-white disabled:opacity-40"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
        </div>
      </div>

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

      <Modal
        isOpen={detail !== null || detailLoading}
        onClose={() => {
          if (!detailLoading) setDetail(null);
        }}
        title="تفاصيل الحوالة"
        maxWidth="max-w-5xl"
      >
        {detailLoading && (
          <div className="p-12 text-center text-slate-500 font-bold">
            جاري جلب التفاصيل...
          </div>
        )}

        {!detailLoading && detail && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="rounded-xl bg-slate-50 p-3">
                <div className="text-[10px] text-slate-400">المرجع</div>
                <div className="font-bold text-slate-800">
                  {detail.transfer.reference_number}
                </div>
              </div>
              <div className="rounded-xl bg-slate-50 p-3">
                <div className="text-[10px] text-slate-400">المصدر</div>
                <div className="font-bold text-slate-800">
                  {detail.transfer.source_location_name}
                </div>
              </div>
              <div className="rounded-xl bg-slate-50 p-3">
                <div className="text-[10px] text-slate-400">الوجهة</div>
                <div className="font-bold text-slate-800">
                  {detail.transfer.destination_location_name}
                </div>
              </div>
              <div className="rounded-xl bg-slate-50 p-3">
                <div className="text-[10px] text-slate-400">الحالة</div>
                <div className="font-bold text-slate-800">
                  {STATUS_META[detail.transfer.status].label}
                </div>
              </div>
            </div>

            {(detail.transfer.notes || detail.transfer.decision_reason) && (
              <div className="rounded-xl border border-slate-200 p-4 text-sm">
                {detail.transfer.notes && (
                  <p>
                    <span className="font-bold">ملاحظات:</span>{" "}
                    {detail.transfer.notes}
                  </p>
                )}
                {detail.transfer.decision_reason && (
                  <p className="mt-2">
                    <span className="font-bold">سبب القرار:</span>{" "}
                    {detail.transfer.decision_reason}
                  </p>
                )}
              </div>
            )}

            <div className="border border-slate-200 rounded-xl overflow-auto max-h-[45vh]">
              <table className="w-full text-sm text-right">
                <thead className="bg-slate-50 sticky top-0">
                  <tr>
                    <th className="p-3">المنتج</th>
                    <th className="p-3">الدفعة</th>
                    <th className="p-3">الصلاحية</th>
                    <th className="p-3">الكمية</th>
                    <th className="p-3">FEFO</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {detail.lines.map((line) => (
                    <tr key={line.id}>
                      <td className="p-3 font-bold text-slate-800">
                        {line.product_name}
                      </td>
                      <td className="p-3 font-mono text-xs">
                        {line.batch_number}
                      </td>
                      <td className="p-3 text-xs text-slate-600">
                        {line.expiry_date}
                      </td>
                      <td className="p-3 font-bold">{line.quantity}</td>
                      <td className="p-3 text-xs">
                        {line.fefo_override_reason_id
                          ? `تجاوز موثّق: ${line.fefo_override_note || "بدون وصف"}`
                          : "FEFO تلقائي"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs text-slate-500">
              <div>
                المرسل:{" "}
                <span className="font-bold text-slate-700">
                  {detail.transfer.dispatched_by_name}
                </span>
              </div>
              <div>
                المستلم:{" "}
                <span className="font-bold text-slate-700">
                  {detail.transfer.received_by_name || "—"}
                </span>
              </div>
              <div>
                الإنشاء:{" "}
                <span className="font-bold text-slate-700">
                  {formatDate(detail.transfer.created_at)}
                </span>
              </div>
              <div>
                الترحيل:{" "}
                <span className="font-bold text-slate-700">
                  {formatDate(detail.transfer.posted_at)}
                </span>
              </div>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        isOpen={action !== null && actionTransfer !== null}
        onClose={closeAction}
        title={
          action === "receive"
            ? "تأكيد استلام الحوالة"
            : action === "reject"
              ? "رفض الحوالة"
              : "إلغاء الحوالة"
        }
      >
        <div className="space-y-4">
          <div className="rounded-xl bg-slate-50 border border-slate-200 p-3 text-sm">
            <div className="font-bold text-slate-800">
              {actionTransfer?.reference_number}
            </div>
            <div className="text-xs text-slate-500 mt-1">
              {actionTransfer?.source_location_name} ←{" "}
              {actionTransfer?.destination_location_name}
            </div>
          </div>

          {action !== "receive" && (
            <div>
              <label className="text-xs font-bold text-slate-600">
                سبب {action === "reject" ? "الرفض" : "الإلغاء"}
              </label>
              <textarea
                value={decisionReason}
                onChange={(event) => {
                  setDecisionReason(event.target.value);
                  setActionRequestId(crypto.randomUUID());
                }}
                maxLength={2000}
                className="mt-1 w-full min-h-28 rounded-xl border border-slate-200 px-3 py-2.5 outline-none focus:ring-2 focus:ring-blue-500/20"
              />
            </div>
          )}

          {action === "receive" && (
            <div className="rounded-xl bg-emerald-50 border border-emerald-200 p-3 text-xs text-emerald-800 font-bold">
              سيتم نقل كامل أسطر الحوالة من IN_TRANSIT إلى وجهتها الأصلية.
              السيرفر يمنع المُرسل من تأكيد استلام حوالته بنفسه.
            </div>
          )}

          <button
            onClick={handleAction}
            disabled={actionSubmitting}
            className={`w-full py-3 rounded-xl text-white font-bold disabled:opacity-50 ${
              action === "receive"
                ? "bg-emerald-600"
                : action === "reject"
                  ? "bg-red-600"
                  : "bg-amber-600"
            }`}
          >
            {actionSubmitting
              ? "جاري التنفيذ..."
              : action === "receive"
                ? "تأكيد الاستلام"
                : action === "reject"
                  ? "تأكيد الرفض"
                  : "تأكيد الإلغاء"}
          </button>
        </div>
      </Modal>
    </div>
  );
}
