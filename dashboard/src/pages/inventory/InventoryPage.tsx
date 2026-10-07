import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { inventoryWorkspaceFocus } from "@/features/inventory/workspaceFocusNavigation";
import {
  createInventoryOwnerFocusState,
  createInventoryTabNavigationState,
  parseInventoryNavigationState,
} from "@/features/inventory/navigation";
import { createDispatchReservationFocusState } from "@/features/dispatch/navigation";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseInventoryLocationCapabilities } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import { BatchFocusWorkspace } from "./batches/BatchFocusWorkspace";
import type { BatchSpecialTransferResult } from "./batches/batchSpecialTransferContract";
import type { ReservationOwner } from "./batches/batchStockSourcesContract";
import MainInventory from "./MainInventory";

/** Exact batch-quality focus bypasses warehouse-shell initialization, not authority. */
export default function InventoryPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const authFetch = useAuthFetch();
  const { t } = useTranslation();
  const [focus, setFocus] = useState(() => inventoryWorkspaceFocus(location.state));
  const batchId = focus?.kind === "batch" ? focus.batchId : null;
  const followRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    const next = inventoryWorkspaceFocus(location.state);
    if (next) setFocus(next);
    else if (parseInventoryNavigationState(location.state)) setFocus(null);
  }, [location.key, location.state]);

  useEffect(
    () => () => followRequest.current?.abort(),
    [batchId, focus?.kind, focus?.variantId],
  );

  const consume = useCallback(() => {
    navigate(`${location.pathname}${location.search}`, {
      replace: true,
      state: null,
    });
  }, [location.pathname, location.search, navigate]);

  const close = () => {
    consume();
    setFocus(null);
  };

  const openTransfers = async (transfer: BatchSpecialTransferResult) => {
    if (!focus) return;
    followRequest.current?.abort();
    const controller = new AbortController();
    followRequest.current = controller;
    const ids = [
      ...new Set([
        transfer.source_location_id,
        transfer.destination_location_id,
      ]),
    ];
    try {
      const capabilities = parseInventoryLocationCapabilities(
        await authFetch("/inventory/access/locations/capabilities", {
          method: "POST",
          signal: controller.signal,
          body: JSON.stringify({ location_ids: ids }),
        }),
        ids,
      );
      if (controller.signal.aborted) return;
      const locationId = ids.find(
        (id) =>
          capabilities[id]?.includes("transfer.read") &&
          capabilities[id]?.includes("location.read"),
      );
      if (locationId === undefined) {
        throw new Error(
          t("inventoryBatches.quantityActions.errors.followUnavailable", {
            reference: transfer.transfer_reference,
          }),
        );
      }
      navigate("/inventory", {
        state: createInventoryOwnerFocusState({
          flow: "transfer",
          variantId: focus.variantId,
          operationId: transfer.header_id,
          locationId,
          reference: transfer.transfer_reference,
        }),
      });
      setFocus(null);
    } catch (error: unknown) {
      if (!controller.signal.aborted) {
        toast.error(
          apiErrorMessage(
            error,
            t("inventoryBatches.quantityActions.errors.followUnavailable", {
              reference: transfer.transfer_reference,
            }),
          ),
        );
      }
    }
  };

  const openReservationOwner = (owner: ReservationOwner) => {
    navigate("/dispatch", {
      state: createDispatchReservationFocusState({
        routeId: owner.route_id,
        transferId: owner.transfer_id,
        openCancel: owner.action === "FORCE_CANCEL_HANDSHAKE",
      }),
    });
  };

  const openQualitySettings = () => {
    navigate("/inventory", {
      state: createInventoryTabNavigationState("warehouses"),
    });
    setFocus(null);
  };

  if (focus?.kind === "batch") {
    return (
      <BatchFocusWorkspace
        key={`${focus.batchId}:${focus.variantId}`}
        identity={focus}
        onConsumed={consume}
        onClose={close}
        onOpenTransfers={openTransfers}
        onOpenReservationOwner={openReservationOwner}
        onConfigureQualityDestinations={openQualitySettings}
      />
    );
  }

  return <MainInventory />;
}
