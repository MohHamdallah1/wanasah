import type { TFunction } from "i18next";
import type { FefoMode, TransferDraftItem, TransferOverrideOptions } from "./types";
import { compareQuantity, type Quantity } from "../quantity";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import { totalDraftQuantity } from "./utils";
type DispatchItem = {
  product_variant_id: number;
  quantity: Quantity;
  uom_id: number;
  is_fefo_override?: boolean;
  override_batch_id?: number;
  override_reason_id?: number;
};


export function buildDispatchItems(draftItems: TransferDraftItem[], overrideOptionsByProduct: Record<number, TransferOverrideOptions>, sourceLocationId: number, t: TFunction): DispatchItem[] {
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
      t("inventoryTransfers.mixedFefo")
    );
  }

  const seenKeys = new Set<string>();

  return draftItems.map((item) => {
    const quantity = totalDraftQuantity(item);

    if (item.fefo_mode === "auto") {
      const key = `${item.product_variant_id}:auto`;
      if (seenKeys.has(key)) {
        throw new Error(
          t("inventoryTransfers.duplicateAuto", { name: item.name })
        );
      }
      seenKeys.add(key);

      if (compareQuantity(quantity, item.available_quantity) > 0) {
        throw new Error(
          t("inventoryTransfers.quantityExceeds", { name: item.name })
        );
      }

      return {
        product_variant_id: item.product_variant_id,
        quantity,
        uom_id: item.base_uom_id,
        is_fefo_override: false,
      };
    }

    if (
      item.override_batch_id === null ||
      item.override_reason_id === null ||
      item.override_batch_available === null
    ) {
      throw new Error(
        t("inventoryTransfers.overrideRequired", { name: item.name })
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
        t("inventoryTransfers.itemOptionsStale", { name: item.name })
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
        t("inventoryTransfers.batchReasonStale", { name: item.name })
      );
    }

    if (compareQuantity(quantity, batch.available_quantity) > 0) {
      throw new Error(
        t("inventoryTransfers.batchQuantityExceeds", { name: item.name, batch: formatPublicBatchNumber(batch.batch_number, t("inventoryLive.noLotSupplied")) })
      );
    }

    const key =
      `${item.product_variant_id}:${item.override_batch_id}`;
    if (seenKeys.has(key)) {
      throw new Error(
        t("inventoryTransfers.itemBatchDuplicate", { name: item.name })
      );
    }
    seenKeys.add(key);

    return {
      product_variant_id: item.product_variant_id,
      quantity,
      uom_id: item.base_uom_id,
      is_fefo_override: true,
      override_batch_id: item.override_batch_id,
      override_reason_id: item.override_reason_id,
    };
  });

}
