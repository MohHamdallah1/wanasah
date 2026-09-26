import {
  AlertTriangle,
  ShieldCheck,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import type {
  ProductTrackingMode,
  SimpleProduct,
} from "@/pages/products/contracts";
import { ProductTrackingFields } from "@/pages/products/tracking/ProductTrackingFields";

type Props = {
  product: SimpleProduct | null;
  lotControlMode: ProductTrackingMode;
  expiryControlMode: ProductTrackingMode;
  saving: boolean;
  online: boolean;
  onLotControlModeChange: (
    value: ProductTrackingMode
  ) => void;
  onExpiryControlModeChange: (
    value: ProductTrackingMode
  ) => void;
  onClose: () => void;
  onSave: () => void;
};

export function ProductTrackingEditor({
  product,
  lotControlMode,
  expiryControlMode,
  saving,
  online,
  onLotControlModeChange,
  onExpiryControlModeChange,
  onClose,
  onSave,
}: Props) {
  const { t } = useTranslation();

  const changed =
    product !== null &&
    (lotControlMode !==
      product.lot_control_mode ||
      expiryControlMode !==
        product.expiry_control_mode);

  return (
    <Modal
      isOpen={product !== null}
      onClose={() => {
        if (!saving) {
          onClose();
        }
      }}
      title={
        product
          ? t(
              "products.trackingEditor.title"
            ) +
            " — " +
            product.name
          : t(
              "products.trackingEditor.title"
            )
      }
      maxWidth="max-w-2xl"
      footer={
        <>
          <button
            type="button"
            disabled={saving}
            onClick={onClose}
            className="px-4 py-2 text-sm font-bold text-slate-600"
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            disabled={
              saving ||
              !online ||
              product === null ||
              !changed
            }
            onClick={onSave}
            className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-black text-white disabled:opacity-50"
          >
            {t(
              "products.trackingEditor.save"
            )}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50/70 p-3 text-amber-950">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p className="text-[10px] font-bold leading-4">
            {t(
              "products.trackingEditor.warning"
            )}
          </p>
        </div>

        <ProductTrackingFields
          lotControlMode={lotControlMode}
          expiryControlMode={
            expiryControlMode
          }
          onLotControlModeChange={
            onLotControlModeChange
          }
          onExpiryControlModeChange={
            onExpiryControlModeChange
          }
          disabled={saving}
        />

        <div className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
          <p className="text-[10px] font-semibold leading-4 text-slate-500">
            {t(
              "products.trackingEditor.lockHint"
            )}
          </p>
        </div>
      </div>
    </Modal>
  );
}
