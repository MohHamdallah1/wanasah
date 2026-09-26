import type {
  ProductTrackingMode,
} from "@/pages/products/contracts";
import { ProductTrackingModePicker } from "@/pages/products/tracking/ProductTrackingModePicker";

type Props = {
  lotControlMode: ProductTrackingMode;
  expiryControlMode: ProductTrackingMode;
  onLotControlModeChange: (
    value: ProductTrackingMode
  ) => void;
  onExpiryControlModeChange: (
    value: ProductTrackingMode
  ) => void;
  disabled?: boolean;
};

export function ProductTrackingFields({
  lotControlMode,
  expiryControlMode,
  onLotControlModeChange,
  onExpiryControlModeChange,
  disabled = false,
}: Props) {
  return (
    <div className="grid gap-2.5 lg:grid-cols-2">
      <ProductTrackingModePicker
        kind="lot"
        value={lotControlMode}
        disabled={disabled}
        onChange={
          onLotControlModeChange
        }
      />

      <ProductTrackingModePicker
        kind="expiry"
        value={expiryControlMode}
        disabled={disabled}
        onChange={
          onExpiryControlModeChange
        }
      />
    </div>
  );
}
