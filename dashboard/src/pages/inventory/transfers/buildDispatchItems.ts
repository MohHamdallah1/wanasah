import type { TFunction } from "i18next";
import type {
  TransferBatchOptions,
  TransferDraftItem,
  TransferOverrideOptions,
} from "./types";
import { addQuantity, compareQuantity, type Quantity } from "../quantity";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import { totalDraftQuantity } from "./utils";
type DispatchItem = {
  product_variant_id: number;
  quantity: Quantity;
  uom_id: number;
  batch_id?: number;
  is_fefo_override?: boolean;
  override_batch_id?: number;
  override_reason_id?: number;
};


export function buildDispatchItems(
  draftItems: TransferDraftItem[],
  batchOptionsByProduct: Record<number, TransferBatchOptions>,
  overrideOptionsByProduct: Record<number, TransferOverrideOptions>,
  sourceLocationId: number,
  t: TFunction,
): DispatchItem[] {
  const totals = new Map<number, Quantity>();
  for (const item of draftItems) {
    const total = addQuantity(
      totals.get(item.product_variant_id) ?? "0",
      totalDraftQuantity(item),
    );
    if (compareQuantity(total, item.available_quantity) > 0) {
      throw new Error(
        t("inventoryTransfers.quantityExceeds", {
          name: item.name,
        }),
      );
    }
    totals.set(item.product_variant_id, total);
  }

  const modesByProduct = new Map<number, Set<string>>();
  for (const item of draftItems) {
    const mode = item.fefo_mode === "override"
      ? "override"
      : item.batch_mode === "exact"
        ? "exact"
        : "auto";
    const modes =
      modesByProduct.get(item.product_variant_id) ??
      new Set<string>();
    modes.add(mode);
    modesByProduct.set(item.product_variant_id, modes);
  }

  if (
    [...modesByProduct.values()].some(
      (modes) => modes.size > 1,
    )
  ) {
    throw new Error(
      t("inventoryTransfers.mixedBatchSelection"),
    );
  }

  const seenKeys = new Set<string>();

  return draftItems.map((item) => {
    const quantity = totalDraftQuantity(item);

    if (
      item.fefo_mode === "auto" &&
      item.batch_mode === "auto"
    ) {
      const key = `${item.product_variant_id}:auto`;
      if (seenKeys.has(key)) {
        throw new Error(
          t("inventoryTransfers.duplicateAuto", {
            name: item.name,
          }),
        );
      }
      seenKeys.add(key);

      if (
        compareQuantity(
          quantity,
          item.available_quantity,
        ) > 0
      ) {
        throw new Error(
          t("inventoryTransfers.quantityExceeds", {
            name: item.name,
          }),
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
      item.fefo_mode === "auto" &&
      item.batch_mode === "exact"
    ) {
      if (
        item.batch_id === null ||
        item.batch_available === null
      ) {
        throw new Error(
          t("inventoryTransfers.batchRequired", {
            name: item.name,
          }),
        );
      }

      const options =
        batchOptionsByProduct[item.product_variant_id];
      if (
        !options ||
        options.location_id !== sourceLocationId ||
        options.product_variant_id
          !== item.product_variant_id
      ) {
        throw new Error(
          t("inventoryTransfers.staleBatchOptions"),
        );
      }

      const batch = options.batches.find(
        (candidate) =>
          candidate.id === item.batch_id,
      );
      if (!batch) {
        throw new Error(
          t("inventoryTransfers.invalidBatch"),
        );
      }

      if (
        compareQuantity(
          quantity,
          batch.available_quantity,
        ) > 0
      ) {
        throw new Error(
          t("inventoryTransfers.batchQuantityExceeds", {
            name: item.name,
            batch: formatPublicBatchNumber(
              batch.batch_number,
              t("inventoryLive.noLotSupplied"),
            ),
          }),
        );
      }

      const key =
        `${item.product_variant_id}:batch:${item.batch_id}`;
      if (seenKeys.has(key)) {
        throw new Error(
          t("inventoryTransfers.itemBatchDuplicate", {
            name: item.name,
          }),
        );
      }
      seenKeys.add(key);

      return {
        product_variant_id: item.product_variant_id,
        quantity,
        uom_id: item.base_uom_id,
        batch_id: item.batch_id,
        is_fefo_override: false,
      };
    }

    if (
      item.override_batch_id === null ||
      item.override_reason_id === null ||
      item.override_batch_available === null
    ) {
      throw new Error(
        t("inventoryTransfers.overrideRequired", {
          name: item.name,
        }),
      );
    }

    const options =
      overrideOptionsByProduct[item.product_variant_id];
    if (
      !options ||
      options.location_id !== sourceLocationId ||
      options.product_variant_id
        !== item.product_variant_id
    ) {
      throw new Error(
        t("inventoryTransfers.itemOptionsStale", {
          name: item.name,
        }),
      );
    }

    const batch = options.batches.find(
      (candidate) =>
        candidate.id === item.override_batch_id,
    );
    const reason = options.reasons.find(
      (candidate) =>
        candidate.id === item.override_reason_id,
    );
    if (!batch || !reason) {
      throw new Error(
        t("inventoryTransfers.batchReasonStale", {
          name: item.name,
        }),
      );
    }

    if (
      compareQuantity(
        quantity,
        batch.available_quantity,
      ) > 0
    ) {
      throw new Error(
        t("inventoryTransfers.batchQuantityExceeds", {
          name: item.name,
          batch: formatPublicBatchNumber(
            batch.batch_number,
            t("inventoryLive.noLotSupplied"),
          ),
        }),
      );
    }

    const key =
      `${item.product_variant_id}:override:${item.override_batch_id}`;
    if (seenKeys.has(key)) {
      throw new Error(
        t("inventoryTransfers.itemBatchDuplicate", {
          name: item.name,
        }),
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
