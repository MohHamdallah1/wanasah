import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorCode } from "@/lib/apiErrors";
import { useTransferTranslation } from "../i18n";
import { useTransferFefo } from "./useTransferFefo";
import { useTransferBatchSelection } from "./useTransferBatchSelection";
import { buildDispatchItems } from "../buildDispatchItems";
import { useTransferCommand, transferCommandScope } from "./useTransferCommand";
import { readTransferDraft, writeTransferDraft, clearTransferDraft, type TransferWarehouse } from "../draftStorage";
import { useTransferQueries } from "./useTransferQueries";
import { restoreDraftItems } from "../restoreDraftItems";
import type { TransferDraftItem, TransferSourceInventoryItem } from "../types";
import { transferCreateError } from "../createErrors";
import { getErrorMessage, getMutationMessage } from "../utils";
import { compareQuantity, validateVariantQuantity } from "../../quantity";
import { findTransferDraftSubmitBlocker, type TransferSubmitBlocker } from "../submitValidation";

interface UseTransferCreateArgs {
  active?: boolean;
  onInventoryChanged: () => void | Promise<void>;
  onCompleted: () => void;
}

export function useTransferCreate({ active = true, onInventoryChanged, onCompleted }: UseTransferCreateArgs) {
  const { t } = useTransferTranslation();
  const command = useTransferCommand("TRANSFER_DISPATCH", "workspace");
  const scope = (() => {
    try {
      return transferCommandScope("TRANSFER_DRAFT", "workspace");
    } catch {
      return null;
    }
  })();
  const currentScope = useRef(scope);
  currentScope.current = scope;
  const [openedScope, setOpenedScope] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  // Keep the persisted form/durable command, but suspend hidden modal readers.
  const createOpen = active && open && scope === openedScope;
  const [source, setSource] = useState<TransferWarehouse | null>(null);
  const [destination, setDestination] = useState<TransferWarehouse | null>(null);
  const [createNotes, setCreateNotes] = useState("");
  const [draftItems, setDraftItems] = useState<TransferDraftItem[]>([]);
  const [restored, setRestored] = useState<TransferDraftItem[] | null>(null);
  const [restoreError, setRestoreError] = useState<unknown>(null);
  const [restoreRevision, setRestoreRevision] = useState(0);
  const [policyBlocked, setPolicyBlocked] = useState(false);
  const pair = JSON.stringify([source?.id, destination?.id]);
  const pairRef = useRef(pair);
  pairRef.current = pair;

  const queries = useTransferQueries(createOpen && !command.pending, source, destination);
  const access = useInventoryAccess();
  const sourceAccess = useInventoryAccess(queries.sources.valid ? source?.id ?? null : null);
  const destinationAccess = useInventoryAccess(queries.destinations.valid ? destination?.id ?? null : null);
  const canOpen = access.canAny("transfer.send") && access.canAny("transfer.destination");
  const canOverride = queries.sources.valid && sourceAccess.can("inventory.fefo_override");
  const sourceLocationId = queries.sources.valid ? source?.id ?? null : null;
  const fefo = useTransferFefo(sourceLocationId, canOverride, draftItems, setDraftItems);
  const batchSelection = useTransferBatchSelection(
    sourceLocationId,
    draftItems,
    setDraftItems,
  );
  const { resetFefo } = fefo;
  const { resetBatchSelection } = batchSelection;
  const { resetProductSearch, readSourcePage, ready } = queries;
  const { setSearch: setSourceSearch } = queries.sources;
  const { setSearch: setDestinationSearch } = queries.destinations;

  const resetCreateForm = useCallback(() => {
    setSource(null);
    setDestination(null);
    setCreateNotes("");
    setDraftItems([]);
    setRestored(null);
    setRestoreError(null);
    setPolicyBlocked(false);
    resetFefo();
    resetBatchSelection();
    resetProductSearch();
    setSourceSearch("");
    setDestinationSearch("");
  }, [resetBatchSelection, resetFefo, resetProductSearch, setDestinationSearch, setSourceSearch]);

  useEffect(() => {
    setOpen(false);
    resetCreateForm();
  }, [scope, resetCreateForm]);

  const openCreate = () => {
    if (!scope || !canOpen) return;
    resetCreateForm();
    try {
      const draft = readTransferDraft(scope);
      if (draft) {
        setSource(draft.source);
        setDestination(draft.destination);
        setCreateNotes(draft.notes);
        setRestored(draft.items.length ? draft.items : null);
      }
      setOpenedScope(scope);
      setOpen(true);
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  const closeCreate = () => {
    if (command.busy) return;
    if (scope) clearTransferDraft(scope);
    setOpen(false);
    resetCreateForm();
  };

  useEffect(() => {
    if (!createOpen || restored === null || command.pending) return;
    if (queries.sources.loading || queries.destinations.loading) return;
    const invalidSource = !!source && !queries.sources.valid;
    const invalidDestination = !!destination && !queries.destinations.valid;
    if (!invalidSource && !invalidDestination) return;
    if (scope) clearTransferDraft(scope);
    setSource(invalidSource ? null : source);
    setDestination(invalidDestination ? null : destination);
    setDraftItems([]);
    setRestored(null);
    setRestoreError(null);
  }, [
    command.pending,
    createOpen,
    destination,
    queries.destinations.loading,
    queries.destinations.valid,
    queries.sources.loading,
    queries.sources.valid,
    restored,
    scope,
    source,
  ]);

  useEffect(() => {
    if (!createOpen || !ready || restored === null || command.pending) return;
    const controller = new AbortController();
    void restoreDraftItems(
      restored,
      (search, cursor) => readSourcePage(search, cursor, controller.signal),
      controller.signal,
    )
      .then((items) => {
        if (!controller.signal.aborted) {
          setDraftItems(items);
          setRestored(null);
          setRestoreError(null);
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) setRestoreError(error);
      });
    return () => controller.abort();
  }, [command.pending, createOpen, readSourcePage, ready, restoreRevision, restored]);

  useEffect(() => {
    if (!createOpen || !scope || restored !== null || command.pending) return;
    try {
      writeTransferDraft(scope, {
        schema_version: 3,
        source,
        destination,
        notes: createNotes,
        items: draftItems.filter((item) => {
          try {
            return compareQuantity(
              validateVariantQuantity(item.quantity, item.quantity_scale, item.quantity_step),
              item.available_quantity,
            ) <= 0;
          } catch {
            return false;
          }
        }),
      });
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }, [command.pending, createNotes, createOpen, destination, draftItems, restored, scope, source]);

  useEffect(() => {
    setDraftItems((items) => items.map((item) => {
      const fresh = queries.sourceProducts.find((product) => product.id === item.product_variant_id);
      return fresh ? { ...item, ...fresh } : item;
    }));
  }, [queries.sourceProducts]);

  const resetWarehouseDependentState = () => {
    setDraftItems([]);
    setRestored(null);
    setRestoreError(null);
    fefo.resetFefo();
    batchSelection.resetBatchSelection();
    resetProductSearch();
  };

  const changeWarehouse = (value: string, purpose: "source" | "destination") => {
    if (command.pending || command.busy) return;
    const options = purpose === "source" ? queries.sources.items : queries.destinations.items;
    const next = options.find((item) => item.id === Number(value)) ?? null;
    if (!next) return;
    if (next.id === (purpose === "source" ? destination?.id : source?.id)) return;
    if ((purpose === "source" ? source?.id : destination?.id) === next.id) return;
    resetWarehouseDependentState();
    if (purpose === "source") setSource(next);
    else setDestination(next);
  };

  const clearWarehouse = (purpose: "source" | "destination") => {
    if (command.pending || command.busy) return;
    const current = purpose === "source" ? source : destination;
    if (!current) return;
    resetWarehouseDependentState();
    if (purpose === "source") setSource(null);
    else setDestination(null);
  };

  const canSwapWarehouses = Boolean(
    source &&
    destination &&
    queries.sources.items.some((item) => item.id === destination.id) &&
    queries.destinations.items.some((item) => item.id === source.id) &&
    !command.pending &&
    !command.busy,
  );

  const swapWarehouses = () => {
    if (!canSwapWarehouses || !source || !destination) return;
    resetWarehouseDependentState();
    setSourceSearch("");
    setDestinationSearch("");
    setSource(destination);
    setDestination(source);
  };

  const updateDraftQuantity = (draftKey: string, value: string) => {
    if (command.pending || command.busy) return;
    setDraftItems((items) => {
      let zero = !value.trim();
      try {
        zero ||= compareQuantity(value, "0") === 0;
      } catch {
        // Keep invalid text visible; submission remains blocked.
      }
      return zero
        ? items.filter((item) => item.draft_key !== draftKey)
        : items.map((item) => item.draft_key === draftKey ? { ...item, quantity: value } : item);
    });
  };

  const updateProductQuantity = (product: TransferSourceInventoryItem, value: string) => {
    if (!queries.ready || command.pending || command.busy || restored !== null) return;
    const existing = draftItems.find((item) => item.id === product.id);
    if (existing) {
      updateDraftQuantity(existing.draft_key, value);
      return;
    }
    let zero = !value.trim();
    try {
      zero ||= compareQuantity(value, "0") === 0;
    } catch {
      // Shared validation below blocks invalid values.
    }
    if (zero) return;
    setDraftItems((items) => [
      ...items,
      {
        ...product,
        draft_key: crypto.randomUUID(),
        product_variant_id: product.id,
        quantity: value,
        batch_mode: "auto",
        batch_id: null,
        batch_available: null,
        fefo_mode: "auto",
        override_batch_id: null,
        override_reason_id: null,
        override_batch_available: null,
      },
    ]);
  };

  const draftSubmitBlocker = useMemo<TransferSubmitBlocker | null>(() => {
    if (!source) {
      return {
        message: t("inventoryTransfers.chooseSource"),
        field: "source",
      };
    }
    if (!destination) {
      return {
        message: t("inventoryTransfers.chooseDestination"),
        field: "destination",
      };
    }
    if (restored !== null) {
      return { message: t("inventoryTransfers.restoringDraft") };
    }
    if (restoreError) {
      return { message: getErrorMessage(restoreError) };
    }
    if (queries.sourceProductsLoading) {
      return { message: t("inventoryTransfers.waitSourceLoading") };
    }
    if (queries.sourceProductsError) {
      return {
        message: getErrorMessage(
          queries.sourceProductsError,
          t("inventoryTransfers.sourceFailure"),
        ),
      };
    }
    if (!queries.ready) {
      return { message: t("inventoryTransfers.chooseWarehousesFirst") };
    }
    if (!sourceAccess.can("transfer.send")) {
      return {
        message: t("inventoryTransfers.sourcePermissionMissing"),
        field: "source",
      };
    }
    if (!destinationAccess.can("transfer.destination")) {
      return {
        message: t("inventoryTransfers.destinationPermissionMissing"),
        field: "destination",
      };
    }
    if (draftItems.some((item) => item.fefo_mode === "override") && !canOverride) {
      return { message: t("inventoryTransfers.overridePermissionMissing") };
    }
    if (createNotes.trim().length > 4000) {
      return { message: t("inventoryTransfers.notesLength") };
    }
    if (command.recoveryError) {
      return { message: getErrorMessage(command.recoveryError) };
    }
    if (command.pending) {
      return { message: t("inventoryTransfers.pending") };
    }
    if (command.busy) {
      return { message: t("inventoryTransfers.sending") };
    }
    return findTransferDraftSubmitBlocker(
      draftItems,
      batchSelection.batchOptionsByProduct,
      fefo.overrideOptionsByProduct,
      source.id,
      t,
    );
  }, [
    batchSelection.batchOptionsByProduct,
    canOverride,
    command.busy,
    command.pending,
    command.recoveryError,
    createNotes,
    destination,
    destinationAccess,
    draftItems,
    fefo.overrideOptionsByProduct,
    queries.ready,
    queries.sourceProductsError,
    queries.sourceProductsLoading,
    restoreError,
    restored,
    source,
    sourceAccess,
    t,
  ]);

  const built = useMemo(() => {
    try {
      if (draftSubmitBlocker || !source || !draftItems.length) return null;
      return buildDispatchItems(
        draftItems.filter((item) => item.quantity && compareQuantity(item.quantity, "0") !== 0),
        batchSelection.batchOptionsByProduct,
        fefo.overrideOptionsByProduct,
        source.id,
        t,
      );
    } catch {
      return null;
    }
  }, [
    batchSelection.batchOptionsByProduct,
    draftItems,
    draftSubmitBlocker,
    fefo.overrideOptionsByProduct,
    source,
    t,
  ]);

  const submitBlocker: TransferSubmitBlocker | null =
    draftSubmitBlocker ??
    (!built?.length
      ? { message: t("inventoryTransfers.draftInvalid") }
      : null);

  const canSubmit = submitBlocker === null && !!built?.length;

  const complete = async (raw: unknown, requestPair: { source_location_id?: unknown; destination_location_id?: unknown }) => {
    if (scope) {
      const saved = readTransferDraft(scope);
      if (saved?.source?.id === requestPair.source_location_id && saved?.destination?.id === requestPair.destination_location_id) {
        clearTransferDraft(scope);
      }
    }
    if (currentScope.current !== scope) return;
    toast.success(getMutationMessage(raw));
    setOpen(false);
    resetCreateForm();
    onCompleted();
    await onInventoryChanged();
  };

  const handleDispatchTransfer = async () => {
    if (!canSubmit || !source || !destination || !built) return;
    const body = {
      source_location_id: source.id,
      destination_location_id: destination.id,
      transfer_purpose: "WAREHOUSE_BALANCING",
      items: built,
      notes: createNotes.trim(),
    };
    try {
      const raw = await command.execute({
        path: "/warehouse/unified/transfer/dispatch",
        method: "POST",
        body,
      }, getMutationMessage);
      if (raw !== undefined) await complete(raw, body);
    } catch (error) {
      if (currentScope.current !== scope || pairRef.current !== pair) return;
      setPolicyBlocked(
        (apiErrorCode(error) ?? "").startsWith("TRANSFER_POLICY_") ||
        apiErrorCode(error) === "RETIRING_WAREHOUSE_BALANCING_POLICY_REQUIRED",
      );
      toast.error(transferCreateError(error));
    }
  };

  const retryPendingDispatch = async () => {
    const body = command.pending?.payload.body ?? {};
    try {
      const raw = await command.execute(undefined, getMutationMessage);
      if (raw !== undefined) await complete(raw, body);
    } catch (error) {
      toast.error(transferCreateError(error));
    }
  };

  const products = [...new Map(
    [...draftItems, ...queries.sourceProducts]
      .filter((item) => compareQuantity(item.available_quantity, "0") > 0)
      .map((item) => [item.id, item]),
  ).values()];

  return {
    ...queries,
    ...fefo,
    ...batchSelection,
    command,
    canOpen,
    canSubmit,
    submitBlocker,
    canOverride,
    createOpen,
    createNotes,
    createSubmitting: command.busy,
    source,
    destination,
    sourceLocationId: source?.id ?? null,
    destinationLocationId: destination?.id ?? null,
    draftItems,
    products,
    restoring: restored !== null,
    restoreError,
    retryRestore: () => setRestoreRevision((n) => n + 1),
    policyBlocked,
    openCreate,
    closeCreate,
    updateSource: (value: string) => changeWarehouse(value, "source"),
    updateDestination: (value: string) => changeWarehouse(value, "destination"),
    clearSource: () => clearWarehouse("source"),
    clearDestination: () => clearWarehouse("destination"),
    canSwapWarehouses,
    swapWarehouses,
    updateCreateNotes: setCreateNotes,
    updateProductQuantity,
    updateDraftQuantity,
    clearDraftItems: () => {
      if (command.pending || command.busy) return;
      setDraftItems([]);
      fefo.resetFefo();
      batchSelection.resetBatchSelection();
    },
    removeDraftLine: (draftKey: string) => setDraftItems((items) => items.filter((item) => item.draft_key !== draftKey)),
    handleDispatchTransfer,
    retryPendingDispatch,
  };
}

export type TransferCreateController = ReturnType<typeof useTransferCreate>;
