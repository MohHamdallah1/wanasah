import type { CatalogVariant } from "@/features/catalog/contracts";
import { CatalogLifecycleActions } from "@/features/catalog/lifecycle/CatalogLifecycleActions";
import { ProductLocationManager } from "@/features/inventory/productLocations/ProductLocationManager";

interface LocationOption {
  id: number;
  code: string;
  name: string;
}

interface Props {
  variant: CatalogVariant;
  locations: LocationOption[];
  onVariantChanged: (variant: CatalogVariant) => void | Promise<void>;
  onVariantDeleted: (variantId: number) => void | Promise<void>;
}

/**
 * Legacy compatibility composition for the unmounted advanced catalog surface.
 * Catalog lifecycle and Inventory product-location authority live in separate features.
 */
export function CatalogLifecyclePanel({
  variant,
  locations,
  onVariantChanged,
  onVariantDeleted,
}: Props) {
  return (
    <div className="space-y-4">
      <CatalogLifecycleActions
        variant={variant}
        onVariantChanged={onVariantChanged}
        onVariantDeleted={onVariantDeleted}
      />
      <ProductLocationManager
        variant={variant}
        locations={locations}
      />
    </div>
  );
}
