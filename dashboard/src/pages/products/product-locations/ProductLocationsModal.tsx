import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import type { CatalogVariant } from "@/features/catalog/contracts";
import { ProductLocationManager } from "@/features/inventory/productLocations/ProductLocationManager";
import type { ProductWarehouseFilterOption } from "@/pages/products/list/warehouseFilterContract";

type Props = {
  isOpen: boolean;
  variant: CatalogVariant | null;
  locations: ProductWarehouseFilterOption[];
  loading: boolean;
  loadError: boolean;
  candidateLocationsUnavailable: boolean;
  focusLocationId?: number;
  focusAssignmentId?: number;
  onClose: () => void;
  onRetry: () => void;
  onChanged: () => void | Promise<void>;
};

export function ProductLocationsModal({
  isOpen,
  variant,
  locations,
  loading,
  loadError,
  candidateLocationsUnavailable,
  focusLocationId,
  focusAssignmentId,
  onClose,
  onRetry,
  onChanged,
}: Props) {
  const { t } = useTranslation();
  const title = variant
    ? `${t("catalogLifecycle.assignments.title")} · ${variant.name}`
    : t("catalogLifecycle.assignments.title");

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={title}
      maxWidth="max-w-3xl"
    >
      {loading ? (
        <div
          role="status"
          className="flex min-h-[180px] items-center justify-center rounded-2xl border border-slate-200 bg-white text-xs font-bold text-slate-400"
        >
          {t("common.loading")}
        </div>
      ) : loadError || !variant ? (
        <div className="flex min-h-[180px] flex-col items-center justify-center rounded-2xl border border-rose-200 bg-rose-50 px-6 text-center">
          <p role="alert" className="text-xs font-black text-rose-800">
            {t("catalogLifecycle.assignments.errors.load")}
          </p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-3 rounded-lg border border-rose-200 bg-white px-3 py-2 text-[10px] font-black text-rose-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
          >
            {t("common.retry")}
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {candidateLocationsUnavailable ? (
            <p
              role="status"
              className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-900"
            >
              {t("catalogLifecycle.assignments.errors.load")}
            </p>
          ) : null}
          <ProductLocationManager
            variant={variant}
            locations={locations}
            focusLocationId={focusLocationId}
            focusAssignmentId={focusAssignmentId}
            onChanged={onChanged}
          />
        </div>
      )}
    </Modal>
  );
}
