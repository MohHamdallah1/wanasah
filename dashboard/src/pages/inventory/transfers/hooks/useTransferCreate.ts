import { useCallback, useEffect, useRef, useState } from "react";
import { useTransferTranslation as useTranslation } from "../i18n";
import { useTransferFefo } from "./useTransferFefo";
import { buildDispatchItems } from "../buildDispatchItems";
import { useTransferCommand, transferCommandScope } from "./useTransferCommand";
import { readTransferDraft, writeTransferDraft, clearTransferDraft } from "../draftStorage";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import {
  parseSourceInventoryPage,
  parseTransferLocations,
} from "../parsers";
import type {
  TransferCreateDirection,
  TransferDraftItem,
  TransferLocationOption,
  TransferSourceInventoryItem,
} from "../types";
import {
  getErrorMessage,
  getMutationMessage,
} from "../utils";
import { compareQuantity } from "../../quantity";
import { apiErrorCode } from "@/lib/apiErrors";

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
  const { t } = useTranslation();
  const authenticatedFetch = useAuthFetch();
  const command = useTransferCommand("TRANSFER_DISPATCH", locationId);
  const currentLocation = useRef(locationId);
  currentLocation.current = locationId;
  const [policyBlocked, setPolicyBlocked] = useState(false);
  const restoringDraft = useRef(false);
  const draftScope = useRef<string | null>(null);
  const [transferPurpose, setTransferPurpose] = useState<"REPLENISHMENT" | "WAREHOUSE_BALANCING">("WAREHOUSE_BALANCING");

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

  const selectedAccess = useInventoryAccess(locationId);
  const sourceAccess = useInventoryAccess(sourceLocationId);
  const destinationAccess = useInventoryAccess(destinationLocationId);
  const canOutgoing = selectedAccess.can('transfer.send');
  const canIncoming = selectedAccess.can('transfer.destination') && selectedAccess.canAny('transfer.send');
  const canSubmit = sourceLocationId !== null && destinationLocationId !== null &&
    sourceAccess.can('transfer.send') && destinationAccess.can('transfer.destination');
  const canOverride = sourceLocationId !== null && sourceAccess.can('inventory.fefo_override');


  const { overrideOptionsByProduct, overrideLoadingProductIds, resetFefo, setDraftFefoMode,
    setOverrideBatch, setOverrideReason, addOverrideBatchLine } =
    useTransferFefo(sourceLocationId, canOverride, draftItems, setDraftItems);

  const resetCreateForm = useCallback(() => {
    sourceProductsRequestSeq.current += 1;
    transferLocationsRequestSeq.current += 1;
    resetFefo();
    setTransferPurpose("WAREHOUSE_BALANCING");
    setCreateDirection("outgoing");
    setCounterpartLocationId(null);
    setCreateNotes("");
    setPolicyBlocked(false);
    setTransferLocations([]);
    setTransferLocationSearchInput("");
    setTransferLocationSearch("");
    setProductSearchInput("");
    setProductSearch("");
    setSourceProducts([]);
    setSourceProductsNextCursor(null);
    setSourceProductsLoadingMore(false);
    setDraftItems([]);
  }, [resetFefo]);

  const openCreate = () => {
    if (!canOutgoing && !canIncoming) return;
    resetCreateForm();
    try {
      const scope = transferCommandScope("TRANSFER_DRAFT", locationId);
      draftScope.current = scope;
      const draft = readTransferDraft(scope);
      if (draft) {
        restoringDraft.current = true;
        setCreateDirection(draft.direction);
        setCounterpartLocationId(draft.counterpart);
        setCreateNotes(draft.notes);
        setTransferPurpose(draft.purpose);
        setDraftItems(draft.items);
        setTransferLocations(draft.locations);
      } else setCreateDirection(canOutgoing ? "outgoing" : "incoming");
      setCreateOpen(true);
    } catch (error) { toast.error(getErrorMessage(error)); }
  };

  const fetchTransferLocations = useCallback(async () => {
    if (!createOpen) return;

    const seq = ++transferLocationsRequestSeq.current;
    setTransferLocationsLoading(true);

    try {
      const params = new URLSearchParams({ limit: "50", purpose: createDirection === "outgoing" ? "destination" : "source" });
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
        for (const item of prev) if (item.id === counterpartLocationId) merged.set(item.id, item);
        for (const item of locations) merged.set(item.id, item);
        return [...merged.values()];
      });
    } catch (error: unknown) {
      if (seq !== transferLocationsRequestSeq.current) return;
      toast.error(
        getErrorMessage(error, t("inventoryTransfers.locationsFailure"))
      );
    } finally {
      if (seq === transferLocationsRequestSeq.current) {
        setTransferLocationsLoading(false);
      }
    }
  }, [
    authenticatedFetch,
    createOpen,
    createDirection,
    locationId,
    counterpartLocationId,
    t,
    transferLocationSearch,
  ]);

  useEffect(() => {
    void fetchTransferLocations();
  }, [fetchTransferLocations]);

  useEffect(() => {
    setCreateOpen(false);
    resetCreateForm();
    return () => { ++sourceProductsRequestSeq.current; ++transferLocationsRequestSeq.current; resetFefo(); };
  }, [locationId, resetCreateForm, resetFefo]);

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
          (item) => compareQuantity(item.available_quantity, "0") > 0
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
          getErrorMessage(error, t("inventoryTransfers.sourceFailure"))
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
      t,
    ]
  );

  useEffect(() => {
    sourceProductsRequestSeq.current += 1;
    resetFefo();
    setSourceProducts([]);
    setSourceProductsNextCursor(null);
    setSourceProductsLoadingMore(false);
    if (restoringDraft.current) restoringDraft.current = false;
    else setDraftItems([]);
  }, [createOpen, sourceLocationId, resetFefo]);

  useEffect(() => {
    void fetchSourceProducts(null, false);
  }, [fetchSourceProducts]);

  useEffect(() => {
    if (!createOpen || !draftScope.current) return;
    try {
      writeTransferDraft(draftScope.current, { direction: createDirection, counterpart: counterpartLocationId,
        notes: createNotes, purpose: transferPurpose, items: draftItems, locations: transferLocations });
    } catch (error) { toast.error(getErrorMessage(error)); }
  }, [createOpen, createDirection, counterpartLocationId, createNotes, transferPurpose, draftItems, transferLocations]);

  const addDraftProduct = (product: TransferSourceInventoryItem) => {
    if (
      draftItems.some(
        (item) => item.product_variant_id === product.id
      )
    ) {
      toast.info(t("inventoryTransfers.duplicateProduct"));
      return;
    }

    setDraftItems((prev) => [
      ...prev,
      {
        ...product,
        draft_key: crypto.randomUUID(),
        product_variant_id: product.id,
        quantity: "0",
        fefo_mode: "auto",
        override_batch_id: null,
        override_reason_id: null,
        override_batch_available: null,
      },
    ]);
  };

  const removeDraftLine = (draftKey: string) => {
    setDraftItems((prev) =>
      prev.filter((item) => item.draft_key !== draftKey)
    );
  };

  const updateDraftQuantity = (
    draftKey: string,
    value: string
  ) => {
    setDraftItems((prev) =>
      prev.map((item) => {
        if (item.draft_key !== draftKey) return item;

        return { ...item, quantity: value.replace(/[^0-9.]/g, "") };
      })
    );
  };

  const updateCreateDirection = (value: string) => {
    if ((value === "outgoing" && canOutgoing) || (value === "incoming" && canIncoming)) {
      setTransferLocations([]);
      transferLocationsRequestSeq.current += 1;
      setCreateDirection(value);
      setCounterpartLocationId(null);
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
      } else {
      setCounterpartLocationId(null);
    }
  };

  const updateCreateNotes = (value: string) => {
    setCreateNotes(value);
  };

  const loadMoreSourceProducts = () => {
    if (!sourceProductsNextCursor) return;
    void fetchSourceProducts(sourceProductsNextCursor, true);
  };

  const handleDispatchTransfer = async () => {
    if (!canSubmit || (draftItems.some(item => item.fefo_mode === 'override') && !canOverride)) {
      toast.error(t("inventoryTransfers.permissions"));
      return;
    }
    if (
      sourceLocationId === null ||
      destinationLocationId === null
    ) {
      toast.error(t("inventoryTransfers.chooseCounterpart"));
      return;
    }

    if (sourceLocationId === destinationLocationId) {
      toast.error(t("inventoryTransfers.differentLocations"));
      return;
    }

    if (
      counterpartLocationId === null ||
      !transferLocations.some(
        (item) => item.id === counterpartLocationId
      )
    ) {
      toast.error(
        t("inventoryTransfers.invalidCounterpart")
      );
      return;
    }

    if (draftItems.length === 0) {
      toast.error(t("inventoryTransfers.atLeastOne"));
      return;
    }

    let items: ReturnType<typeof buildDispatchItems>;
    try {
      items = buildDispatchItems(draftItems, overrideOptionsByProduct, sourceLocationId, t);
    } catch (error) {
      toast.error(getErrorMessage(error));
      return;
    }

    if (createNotes.trim().length > 4000) {
      toast.error(t("inventoryTransfers.notesLength"));
      return;
    }

    setCreateSubmitting(true);

    try {
      const raw = await command.execute({
        path: "/warehouse/unified/transfer/dispatch", method: "POST",
        body: { source_location_id: sourceLocationId, destination_location_id: destinationLocationId,
          transfer_purpose: transferPurpose, items, notes: createNotes.trim() },
      }, getMutationMessage);
      if (raw === undefined) return;
      clearTransferDraft(transferCommandScope("TRANSFER_DRAFT", locationId));
      if (currentLocation.current !== locationId) return;

      toast.success(getMutationMessage(raw));
      if (draftScope.current) clearTransferDraft(draftScope.current);
      setCreateOpen(false);
      resetCreateForm();
      onCompleted();
      await onInventoryChanged();
    } catch (error: unknown) {
      if (currentLocation.current !== locationId) return;
      setPolicyBlocked((apiErrorCode(error) ?? "").startsWith("TRANSFER_POLICY_") || apiErrorCode(error) === "RETIRING_WAREHOUSE_BALANCING_POLICY_REQUIRED");
      toast.error(getErrorMessage(error));
    } finally {
      if (currentLocation.current === locationId) setCreateSubmitting(false);
    }
  };

  const retryPendingDispatch = async () => {
    try {
      const raw = await command.execute(undefined, getMutationMessage);
      if (raw === undefined) return;
      clearTransferDraft(transferCommandScope("TRANSFER_DRAFT", locationId));
      if (currentLocation.current !== locationId) return;
      toast.success(getMutationMessage(raw));
      if (draftScope.current) clearTransferDraft(draftScope.current);
      setCreateOpen(false);
      resetCreateForm();
      onCompleted();
      await onInventoryChanged();
    } catch (error) { toast.error(getErrorMessage(error)); }
  };

  return {
    command, retryPendingDispatch, transferPurpose, setTransferPurpose, policyBlocked,
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
