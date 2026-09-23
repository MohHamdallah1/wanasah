import { Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import type {
  ProductTrackingMode,
  ProductTrackingSource,
} from "@/pages/products/contracts";
import { ProductTrackingFields } from "@/pages/products/ProductTrackingFields";

type Props = {
  open: boolean;
  lotControlMode: ProductTrackingMode;
  expiryControlMode: ProductTrackingMode;
  lotControlSource: ProductTrackingSource;
  expiryControlSource: ProductTrackingSource;
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

export function ProductTrackingSettings({
  open,
  lotControlMode,
  expiryControlMode,
  lotControlSource,
  expiryControlSource,
  saving,
  online,
  onLotControlModeChange,
  onExpiryControlModeChange,
  onClose,
  onSave,
}: Props) {
  const { t } = useTranslation();

  return (
    <Modal
      isOpen={open}
      onClose={() => {
        if (!saving) {
          onClose();
        }
      }}
      title={t(
        "products.trackingSettings.title"
      )}
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
            disabled={saving || !online}
            onClick={onSave}
            className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-black text-white disabled:opacity-50"
          >
            {t(
              "products.trackingSettings.save"
            )}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="flex gap-3 rounded-2xl bg-sky-50 p-4 text-sky-950">
          <Settings2 className="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <p className="text-sm font-black">
              {t(
                "products.trackingSettings.descriptionTitle"
              )}
            </p>
            <p className="mt-1 text-xs font-semibold leading-6 text-sky-900">
              {t(
                "products.trackingSettings.description"
              )}
            </p>
          </div>
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

        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3 text-[11px] font-semibold leading-5 text-slate-500">
          {t(
            "products.trackingSettings.sourceSummary",
            {
              lot:
                lotControlSource ===
                "COMPANY"
                  ? t(
                      "products.trackingSettings.companySource"
                    )
                  : t(
                      "products.trackingSettings.platformSource"
                    ),
              expiry:
                expiryControlSource ===
                "COMPANY"
                  ? t(
                      "products.trackingSettings.companySource"
                    )
                  : t(
                      "products.trackingSettings.platformSource"
                    ),
            }
          )}
        </div>
      </div>
    </Modal>
  );
}
