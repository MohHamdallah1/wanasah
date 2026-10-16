import type { CatalogVariant } from "@/features/catalog/contracts";
import type { InboundBatchDraft } from "./contracts";

type TrackingModes = Pick<
  CatalogVariant,
  "lot_control_mode" | "expiry_control_mode"
>;

export interface InboundTrackingFieldPolicy {
  visible: boolean;
  required: boolean;
  clearHiddenValue: boolean;
}

export interface InboundTrackingPolicy {
  lot: InboundTrackingFieldPolicy;
  expiry: InboundTrackingFieldPolicy;
  production: InboundTrackingFieldPolicy;
}

const fieldPolicy = (
  visible: boolean,
  required = false,
): InboundTrackingFieldPolicy => ({
  visible,
  required: visible && required,
  clearHiddenValue: !visible,
});

export const inboundTrackingPolicy = (
  variant: TrackingModes,
): InboundTrackingPolicy => {
  const lotVisible =
    variant.lot_control_mode !== "NONE";
  const expiryVisible =
    variant.expiry_control_mode !== "NONE";
  const productionVisible =
    lotVisible || expiryVisible;

  return {
    lot: fieldPolicy(
      lotVisible,
      variant.lot_control_mode === "REQUIRED",
    ),
    expiry: fieldPolicy(
      expiryVisible,
      variant.expiry_control_mode === "REQUIRED",
    ),
    production: fieldPolicy(productionVisible),
  };
};

export const clearHiddenInboundTrackingValues = (
  row: InboundBatchDraft,
  variant: TrackingModes,
): InboundBatchDraft => {
  const policy = inboundTrackingPolicy(variant);
  return {
    ...row,
    batch_number: policy.lot.clearHiddenValue
      ? ""
      : row.batch_number,
    expiry_date: policy.expiry.clearHiddenValue
      ? ""
      : row.expiry_date,
    production_date:
      policy.production.clearHiddenValue
        ? ""
        : row.production_date,
  };
};
