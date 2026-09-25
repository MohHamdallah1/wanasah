import type {
  ProductImportState,
  ProductTrackingDefaults,
  ProductTrackingMode,
} from "@/pages/products/contracts";

export function usesCompanyImportTrackingDefaults(
  defaults: ProductTrackingDefaults | undefined,
  lotControlMode: ProductTrackingMode | null,
  expiryControlMode: ProductTrackingMode | null,
): boolean {
  return Boolean(
    defaults &&
      lotControlMode &&
      expiryControlMode &&
      lotControlMode ===
        defaults.lot_control_mode &&
      expiryControlMode ===
        defaults.expiry_control_mode
  );
}

export function calculateImportProgress(
  status: ProductImportState | null,
): number {
  return status &&
    status.valid_rows > 0
    ? Math.min(
        100,
        Math.round(
          (status.processed_rows /
            status.valid_rows) *
            100
        )
      )
    : 0;
}

export function deriveImportProductViewState(
  status: ProductImportState | null,
  defaults: ProductTrackingDefaults | undefined,
  lotControlMode: ProductTrackingMode | null,
  expiryControlMode: ProductTrackingMode | null,
) {
  return {
    progress:
      calculateImportProgress(
        status
      ),
    trackingUsesCompanyDefaults:
      usesCompanyImportTrackingDefaults(
        defaults,
        lotControlMode,
        expiryControlMode
      ),
  };
}
