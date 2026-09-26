import type {
  RefObject,
} from "react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import type {
  PackageUom,
  ProductFamily,
  ProductTrackingMode,
} from "@/pages/products/contracts";
import { CreateProductAdvancedSection } from "@/pages/products/create/CreateProductAdvancedSection";
import { CreateProductCommerceSection } from "@/pages/products/create/CreateProductCommerceSection";
import { CreateProductIdentitySection } from "@/pages/products/create/CreateProductIdentitySection";
import type {
  CreateFieldError,
  ProductDraft,
  ProductFamilyMode,
} from "@/pages/products/create/types";

type Props = {
  open: boolean;
  saving: boolean;
  online: boolean;
  draft: ProductDraft;
  createFieldError: CreateFieldError | null;
  familyOptions: ProductFamily[];
  familyOptionsError: boolean;
  packageUoms: PackageUom[];
  packageUomsLoading: boolean;
  packageUomsError: boolean;
  trackingDefaultsError: boolean;
  trackingUsesCompanyDefaults: boolean;
  draftDerived: {
    independent: boolean;
  } | null;
  createAdvancedExpanded: boolean;
  createTrackingExpanded: boolean;
  createNameRef: RefObject<HTMLInputElement>;
  createFamilyRef: RefObject<HTMLInputElement>;
  createUnitsRef: RefObject<HTMLInputElement>;
  createPackagePriceRef: RefObject<HTMLInputElement>;
  createUnitPriceRef: RefObject<HTMLInputElement>;
  onCancel: () => void;
  onSubmit: () => void;
  onNameChange: (value: string) => void;
  onFamilyModeChange: (
    mode: ProductFamilyMode,
  ) => void;
  onFamilyChange: (
    value: string,
    familyId?: number | null,
  ) => void;
  onRetryFamilyOptions: () => void;
  onRetryTrackingDefaults: () => void;
  onHasPackageChange: (checked: boolean) => void;
  onRetryPackageUoms: () => void;
  onPackageUomChange: (value: string) => void;
  onUnitsPerPackageChange: (value: string) => void;
  onPackagePriceChange: (value: string) => void;
  onUnitPriceChange: (value: string) => void;
  onToggleAdvanced: () => void;
  onExpandTracking: () => void;
  onLotControlModeChange: (
    value: ProductTrackingMode,
  ) => void;
  onExpiryControlModeChange: (
    value: ProductTrackingMode,
  ) => void;
  onResetTracking: () => void;
  onUnitBarcodeChange: (value: string) => void;
  onCopyBarcode: () => void;
  onPackageBarcodeChange: (value: string) => void;
};

export function CreateProductModal({
  open,
  saving,
  online,
  draft,
  createFieldError,
  familyOptions,
  familyOptionsError,
  packageUoms,
  packageUomsLoading,
  packageUomsError,
  trackingDefaultsError,
  trackingUsesCompanyDefaults,
  draftDerived,
  createAdvancedExpanded,
  createTrackingExpanded,
  createNameRef,
  createFamilyRef,
  createUnitsRef,
  createPackagePriceRef,
  createUnitPriceRef,
  onCancel,
  onSubmit,
  onNameChange,
  onFamilyModeChange,
  onFamilyChange,
  onRetryFamilyOptions,
  onRetryTrackingDefaults,
  onHasPackageChange,
  onRetryPackageUoms,
  onPackageUomChange,
  onUnitsPerPackageChange,
  onPackagePriceChange,
  onUnitPriceChange,
  onToggleAdvanced,
  onExpandTracking,
  onLotControlModeChange,
  onExpiryControlModeChange,
  onResetTracking,
  onUnitBarcodeChange,
  onCopyBarcode,
  onPackageBarcodeChange,
}: Props) {
  const { t } = useTranslation();

  const saveDisabled =
    saving ||
    !online ||
    !draft.lot_control_mode ||
    !draft.expiry_control_mode ||
    (draft.has_package &&
      (packageUomsLoading ||
        packageUomsError ||
        !packageUoms.some(
          (item) =>
            item.code ===
            draft.package_uom_code,
        )));

  return (
    <Modal
      isOpen={open}
      onClose={() => {
        if (!saving) {
          onCancel();
        }
      }}
      title={t("products.addTitle")}
      maxWidth="max-w-4xl"
      footer={
        <>
          <button
            type="button"
            disabled={saving}
            onClick={onCancel}
            className="min-h-10 px-4 text-sm font-black text-slate-500 transition hover:text-slate-900 disabled:opacity-50"
          >
            {t("common.cancel")}
          </button>

          <button
            type="button"
            disabled={saveDisabled}
            onClick={onSubmit}
            className="min-h-10 rounded-xl bg-amber-400 px-5 text-sm font-black text-slate-950 shadow-sm transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {t("products.saveProduct")}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        {!online ? (
          <div
            role="status"
            className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold leading-5 text-amber-900"
          >
            {t("products.offlineSaveHint")}
          </div>
        ) : null}

        <div className="grid gap-3 lg:grid-cols-2">
          <CreateProductIdentitySection
            draft={draft}
            createFieldError={
              createFieldError
            }
            familyOptions={
              familyOptions
            }
            familyOptionsError={
              familyOptionsError
            }
            createNameRef={
              createNameRef
            }
            createFamilyRef={
              createFamilyRef
            }
            onNameChange={
              onNameChange
            }
            onFamilyModeChange={
              onFamilyModeChange
            }
            onFamilyChange={
              onFamilyChange
            }
            onRetryFamilyOptions={
              onRetryFamilyOptions
            }
          />

          <CreateProductCommerceSection
            draft={draft}
            createFieldError={
              createFieldError
            }
            packageUoms={
              packageUoms
            }
            packageUomsLoading={
              packageUomsLoading
            }
            packageUomsError={
              packageUomsError
            }
            draftDerived={
              draftDerived
            }
            createUnitsRef={
              createUnitsRef
            }
            createPackagePriceRef={
              createPackagePriceRef
            }
            createUnitPriceRef={
              createUnitPriceRef
            }
            onHasPackageChange={
              onHasPackageChange
            }
            onRetryPackageUoms={
              onRetryPackageUoms
            }
            onPackageUomChange={
              onPackageUomChange
            }
            onUnitsPerPackageChange={
              onUnitsPerPackageChange
            }
            onPackagePriceChange={
              onPackagePriceChange
            }
            onUnitPriceChange={
              onUnitPriceChange
            }
          />
        </div>

        <CreateProductAdvancedSection
          draft={draft}
          trackingDefaultsError={
            trackingDefaultsError
          }
          trackingUsesCompanyDefaults={
            trackingUsesCompanyDefaults
          }
          createAdvancedExpanded={
            createAdvancedExpanded
          }
          createTrackingExpanded={
            createTrackingExpanded
          }
          onRetryTrackingDefaults={
            onRetryTrackingDefaults
          }
          onToggleAdvanced={
            onToggleAdvanced
          }
          onExpandTracking={
            onExpandTracking
          }
          onLotControlModeChange={
            onLotControlModeChange
          }
          onExpiryControlModeChange={
            onExpiryControlModeChange
          }
          onResetTracking={
            onResetTracking
          }
          onUnitBarcodeChange={
            onUnitBarcodeChange
          }
          onCopyBarcode={
            onCopyBarcode
          }
          onPackageBarcodeChange={
            onPackageBarcodeChange
          }
        />
      </div>
    </Modal>
  );
}
