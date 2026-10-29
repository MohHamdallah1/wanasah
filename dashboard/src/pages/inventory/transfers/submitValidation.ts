import type { TFunction } from "i18next";
import type {
  TransferBatchOptions,
  TransferDraftItem,
  TransferOverrideOptions,
} from "./types";
import { addQuantity, compareQuantity, type Quantity } from "../quantity";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import { totalDraftQuantity } from "./utils";

export type TransferSubmitBlocker = {
  message: string;
  field?: "source" | "destination";
  productId?: number;
  draftKey?: string;
};

export function findTransferDraftSubmitBlocker(
  draftItems: TransferDraftItem[],
  batchOptionsByProduct: Record<number, TransferBatchOptions>,
  overrideOptionsByProduct: Record<number, TransferOverrideOptions>,
  sourceLocationId: number,
  t: TFunction,
): TransferSubmitBlocker | null {
  if (draftItems.length === 0) {
    return { message: t("inventoryTransfers.atLeastOne") };
  }

  const byProduct = new Map<number, TransferDraftItem[]>();
  for (const item of draftItems) {
    const lines = byProduct.get(item.product_variant_id) ?? [];
    lines.push(item);
    byProduct.set(item.product_variant_id, lines);
  }

  for (const lines of byProduct.values()) {
    const first = lines[0];
    let productTotal: Quantity = "0";
    const modes = new Set<string>();
    const seenBatchKeys = new Set<string>();

    for (const item of lines) {
      let quantity: Quantity;
      try {
        quantity = totalDraftQuantity(item);
      } catch {
        return {
          message: t("inventoryTransfers.quantityInvalid", { name: item.name }),
          productId: item.product_variant_id,
          draftKey: item.draft_key,
        };
      }

      productTotal = addQuantity(productTotal, quantity);
      const mode =
        item.fefo_mode === "override"
          ? "override"
          : item.batch_mode === "exact"
            ? "exact"
            : "auto";
      modes.add(mode);

      if (mode === "exact") {
        if (item.batch_id === null || item.batch_available === null) {
          return {
            message: t("inventoryTransfers.batchRequired", { name: item.name }),
            productId: item.product_variant_id,
            draftKey: item.draft_key,
          };
        }
        const options = batchOptionsByProduct[item.product_variant_id];
        if (
          !options ||
          options.location_id !== sourceLocationId ||
          options.product_variant_id !== item.product_variant_id
        ) {
          return {
            message: t("inventoryTransfers.staleBatchOptions"),
            productId: item.product_variant_id,
            draftKey: item.draft_key,
          };
        }
        const batch = options.batches.find((candidate) => candidate.id === item.batch_id);
        if (!batch) {
          return {
            message: t("inventoryTransfers.invalidBatch"),
            productId: item.product_variant_id,
            draftKey: item.draft_key,
          };
        }
        if (compareQuantity(quantity, batch.available_quantity) > 0) {
          return {
            message: t("inventoryTransfers.batchQuantityExceeds", {
              name: item.name,
              batch: formatPublicBatchNumber(
                batch.batch_number,
                t("inventoryLive.noLotSupplied"),
              ),
            }),
            productId: item.product_variant_id,
            draftKey: item.draft_key,
          };
        }
        const key = `exact:${item.batch_id}`;
        if (seenBatchKeys.has(key)) {
          return {
            message: t("inventoryTransfers.itemBatchDuplicate", { name: item.name }),
            productId: item.product_variant_id,
            draftKey: item.draft_key,
          };
        }
        seenBatchKeys.add(key);
      }

      if (mode === "override") {
        if (
          item.override_batch_id === null ||
          item.override_reason_id === null ||
          item.override_batch_available === null
        ) {
          return {
            message: t("inventoryTransfers.overrideRequired", { name: item.name }),
            productId: item.product_variant_id,
            draftKey: item.draft_key,
          };
        }
        const options = overrideOptionsByProduct[item.product_variant_id];
        if (
          !options ||
          options.location_id !== sourceLocationId ||
          options.product_variant_id !== item.product_variant_id
        ) {
          return {
            message: t("inventoryTransfers.itemOptionsStale", { name: item.name }),
            productId: item.product_variant_id,
            draftKey: item.draft_key,
          };
        }
        const batch = options.batches.find(
          (candidate) => candidate.id === item.override_batch_id,
        );
        const reason = options.reasons.find(
          (candidate) => candidate.id === item.override_reason_id,
        );
        if (!batch || !reason) {
          return {
            message: t("inventoryTransfers.batchReasonStale", { name: item.name }),
            productId: item.product_variant_id,
            draftKey: item.draft_key,
          };
        }
        if (compareQuantity(quantity, batch.available_quantity) > 0) {
          return {
            message: t("inventoryTransfers.batchQuantityExceeds", {
              name: item.name,
              batch: formatPublicBatchNumber(
                batch.batch_number,
                t("inventoryLive.noLotSupplied"),
              ),
            }),
            productId: item.product_variant_id,
            draftKey: item.draft_key,
          };
        }
        const key = `override:${item.override_batch_id}`;
        if (seenBatchKeys.has(key)) {
          return {
            message: t("inventoryTransfers.itemBatchDuplicate", { name: item.name }),
            productId: item.product_variant_id,
            draftKey: item.draft_key,
          };
        }
        seenBatchKeys.add(key);
      }
    }

    if (modes.size > 1) {
      return {
        message: t("inventoryTransfers.mixedBatchSelection"),
        productId: first.product_variant_id,
      };
    }

    if (compareQuantity(productTotal, first.available_quantity) > 0) {
      return {
        message: lines.length > 1
          ? t("inventoryTransfers.splitTotalExceeds", { name: first.name })
          : t("inventoryTransfers.quantityExceeds", { name: first.name }),
        productId: first.product_variant_id,
        draftKey:
          lines.length > 1
            ? lines[lines.length - 1].draft_key
            : undefined,
      };
    }
  }

  return null;
}
