import {
  BadgeInfo,
  Building2,
  Settings2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import type {
  ProductTrackingMode,
  ProductTrackingSource,
} from "@/pages/products/contracts";
import { ProductTrackingFields } from "@/pages/products/tracking/ProductTrackingFields";

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

const sourceTone = (
  source: ProductTrackingSource,
) =>
  source === "COMPANY"
    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
    : "border-slate-200 bg-slate-50 text-slate-600";

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
      <div className="space-y-3">
        <div className="flex items-start gap-3 rounded-xl border border-sky-100 bg-sky-50/70 p-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white text-sky-700 ring-1 ring-sky-100">
            <Settings2 className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-black leading-5 text-sky-950">
              {t(
                "products.trackingSettings.descriptionTitle"
              )}
            </p>
            <p className="mt-0.5 text-[10px] font-semibold leading-4 text-sky-800">
              {t(
                "products.trackingSettings.description"
              )}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-black ${sourceTone(
              lotControlSource,
            )}`}
          >
            <Building2 className="h-3.5 w-3.5" />
            {t("products.tracking.shortLot")}
            <span aria-hidden="true">·</span>
            {t(
              lotControlSource === "COMPANY"
                ? "products.trackingSettings.companySource"
                : "products.trackingSettings.platformSource"
            )}
          </span>

          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-black ${sourceTone(
              expiryControlSource,
            )}`}
          >
            <Building2 className="h-3.5 w-3.5" />
            {t("products.tracking.shortExpiry")}
            <span aria-hidden="true">·</span>
            {t(
              expiryControlSource === "COMPANY"
                ? "products.trackingSettings.companySource"
                : "products.trackingSettings.platformSource"
            )}
          </span>
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

        <div className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[10px] font-semibold leading-4 text-slate-500">
          <BadgeInfo className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
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
          </span>
        </div>
      </div>
    </Modal>
  );
}
