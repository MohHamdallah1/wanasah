import type {
  RefObject,
} from "react";
import {
  Copy,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import type {
  PackageUom,
  ProductFamily,
  ProductTrackingMode,
} from "@/pages/products/contracts";
import type {
  CreateFieldError,
  ProductDraft,
  ProductFamilyMode,
} from "@/pages/products/create/types";
import { ProductTrackingFields } from "@/pages/products/tracking/ProductTrackingFields";

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

  return (
    <Modal
        isOpen={open}
        onClose={() => {
          if (
            !saving
          ) {
            onCancel();
          }
        }}
        title={t(
          "products.addTitle"
        )}
        maxWidth="max-w-2xl"
        footer={
          <>
            <button
              type="button"
              disabled={
                saving
              }
              onClick={
                onCancel
              }
              className="px-4 py-2 text-sm font-bold text-slate-600"
            >
              {t(
                "common.cancel"
              )}
            </button>
            <button
              type="button"
              disabled={
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
                        draft.package_uom_code
                    )))
              }
              onClick={onSubmit}
              className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-black text-white disabled:opacity-50"
            >
              {t(
                "products.saveProduct"
              )}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          {!online ? (
            <div className="rounded-2xl bg-amber-50 p-3 text-xs font-bold leading-6 text-amber-900">
              {t(
                "products.offlineSaveHint"
              )}
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-black text-slate-600">
              {t(
                "products.productName"
              )}
              <input
                ref={createNameRef}
                value={draft.name}
                onChange={(event) =>
                  onNameChange(
                    event.target.value
                  )
                }
                placeholder={t(
                  "products.productNamePlaceholder"
                )}
                aria-invalid={
                  createFieldError?.field ===
                  "name"
                    ? "true"
                    : undefined
                }
                aria-describedby={
                  createFieldError?.field ===
                  "name"
                    ? "product-name-error"
                    : undefined
                }
                className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-bold outline-none"
              />
              {createFieldError?.field ===
              "name" ? (
                <span
                  id="product-name-error"
                  role="alert"
                  className="mt-1 block text-[11px] font-bold text-rose-700"
                >
                  {createFieldError.message}
                </span>
              ) : null}
            </label>

            <fieldset className="text-xs font-black text-slate-600">
              <legend>
                {t(
                  "products.family"
                )}{" "}
                <span className="font-bold text-slate-400">
                  {t(
                    "common.optional"
                  )}
                </span>
              </legend>

              <div
                role="group"
                aria-label={t(
                  "products.familyModeLabel"
                )}
                className="mt-1.5 grid grid-cols-3 gap-2"
              >
                {(
                  [
                    "none",
                    "existing",
                    "new",
                  ] as const
                ).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    aria-pressed={
                      draft.family_mode ===
                      mode
                    }
                    onClick={() =>
                      onFamilyModeChange(
                        mode
                      )
                    }
                    className={`rounded-xl border px-2 py-2 text-[11px] font-black transition ${
                      draft.family_mode ===
                      mode
                        ? "border-slate-950 bg-slate-950 text-white"
                        : "border-slate-200 bg-white text-slate-600"
                    }`}
                  >
                    {t(
                      `products.familyMode.${mode}`
                    )}
                  </button>
                ))}
              </div>

              {draft.family_mode ===
              "existing" ? (
                <>
                  <input
                    ref={
                      createFamilyRef
                    }
                    list="product-family-options"
                    value={
                      draft.family
                    }
                    onChange={(
                      event
                    ) => {
                      const value =
                        event.target
                          .value;
                      const normalized =
                        value
                          .trim()
                          .toLocaleLowerCase();
                      const selected =
                        familyOptions.find(
                          (
                            family
                          ) =>
                            family.name
                              .trim()
                              .toLocaleLowerCase() ===
                            normalized
                        );
                      onFamilyChange(
                        value,
                        selected?.id ??
                          null
                      );
                    }}
                    placeholder={t(
                      "products.familyExistingPlaceholder"
                    )}
                    aria-invalid={
                      createFieldError?.field ===
                      "family"
                        ? "true"
                        : undefined
                    }
                    aria-describedby={
                      createFieldError?.field ===
                      "family"
                        ? "product-family-error"
                        : undefined
                    }
                    className="mt-2 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-bold outline-none"
                  />
                  <datalist id="product-family-options">
                    {familyOptions.map(
                      (
                        family
                      ) => (
                        <option
                          key={
                            family.id
                          }
                          value={
                            family.name
                          }
                        />
                      )
                    )}
                  </datalist>
                  <p className="mt-1 text-[11px] font-semibold leading-5 text-slate-500">
                    {t(
                      "products.familyExistingHint"
                    )}
                  </p>
                  {familyOptionsError ? (
                    <button
                      type="button"
                      onClick={() =>
                        onRetryFamilyOptions()
                      }
                      className="mt-1 text-[11px] font-black text-rose-700"
                    >
                      {t(
                        "products.errors.familiesLoad"
                      )}
                    </button>
                  ) : null}
                </>
              ) : draft.family_mode ===
                "new" ? (
                <>
                  <input
                    ref={
                      createFamilyRef
                    }
                    value={
                      draft.family
                    }
                    maxLength={
                      150
                    }
                    onChange={(
                      event
                    ) =>
                      onFamilyChange(
                        event.target
                          .value,
                        null
                      )
                    }
                    placeholder={t(
                      "products.familyNewPlaceholder"
                    )}
                    aria-invalid={
                      createFieldError?.field ===
                      "family"
                        ? "true"
                        : undefined
                    }
                    aria-describedby={
                      createFieldError?.field ===
                      "family"
                        ? "product-family-error"
                        : undefined
                    }
                    className="mt-2 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-bold outline-none"
                  />
                  <p className="mt-1 text-[11px] font-semibold leading-5 text-amber-700">
                    {t(
                      "products.familyNewHint"
                    )}
                  </p>
                </>
              ) : (
                <p className="mt-2 rounded-xl bg-slate-50 px-3 py-2 text-[11px] font-semibold leading-5 text-slate-500">
                  {t(
                    "products.familyNoneHint"
                  )}
                </p>
              )}

              {createFieldError?.field ===
              "family" ? (
                <span
                  id="product-family-error"
                  role="alert"
                  className="mt-1 block text-[11px] font-bold text-rose-700"
                >
                  {createFieldError.message}
                </span>
              ) : null}
            </fieldset>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-4">
            <div className="mb-3">
              <h3 className="text-sm font-black text-slate-900">
                {t(
                  "products.tracking.createTitle"
                )}
              </h3>
              <p className="mt-1 text-xs font-semibold leading-6 text-slate-500">
                {t(
                  "products.tracking.createHint"
                )}
              </p>
            </div>

            {!draft.lot_control_mode ||
            !draft.expiry_control_mode ? (
              trackingDefaultsError ? (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-rose-50 p-3">
                  <span className="text-xs font-bold text-rose-800">
                    {t(
                      "products.errors.trackingDefaultsLoad"
                    )}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      onRetryTrackingDefaults()
                    }
                    className="rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs font-black text-rose-800"
                  >
                    {t(
                      "common.retry"
                    )}
                  </button>
                </div>
              ) : (
                <div className="rounded-xl bg-slate-50 p-3 text-xs font-bold text-slate-500">
                  {t(
                    "products.trackingDefaultsLoading"
                  )}
                </div>
              )
            ) : (
              <div className="space-y-3">
                <div className="rounded-xl bg-slate-50 p-3">
                  <p className="text-xs font-black leading-6 text-slate-800">
                    {t(
                      "products.tracking.createSummary",
                      {
                        lot: t(
                          `products.tracking.lotModes.${draft.lot_control_mode}`
                        ),
                        expiry: t(
                          `products.tracking.expiryModes.${draft.expiry_control_mode}`
                        ),
                      }
                    )}
                  </p>
                  <p className="mt-1 text-[11px] font-semibold leading-5 text-slate-500">
                    {t(
                      trackingUsesCompanyDefaults
                        ? "products.tracking.createCompanyScope"
                        : "products.tracking.createCustomScope"
                    )}
                  </p>
                </div>

                <p className="text-[11px] font-semibold leading-5 text-slate-500">
                  {t(
                    "products.quickCreate.trackingAdvancedHint"
                  )}
                </p>
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
            <label className="flex cursor-pointer items-center justify-between gap-4">
              <span className="text-xs font-black text-slate-700">
                {draft.has_package
                  ? t(
                      "products.hasOuterPackage"
                    )
                  : t(
                      "products.noOuterPackage"
                    )}
              </span>
              <input
                type="checkbox"
                checked={
                  draft.has_package
                }
                onChange={(event) =>
                  onHasPackageChange(
                    event.target.checked
                  )
                }
                className="h-4 w-4"
              />
            </label>
          </div>

          {draft.has_package ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {packageUomsLoading ? (
                <div className="rounded-xl bg-slate-50 p-3 text-xs font-bold text-slate-500">
                  {t(
                    "common.loading"
                  )}
                </div>
              ) : packageUomsError ? (
                <div
                  role="alert"
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-rose-50 p-3"
                >
                  <span className="text-xs font-bold text-rose-800">
                    {t(
                      "products.errors.packageUomsLoad"
                    )}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      onRetryPackageUoms()
                    }
                    className="rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs font-black text-rose-800"
                  >
                    {t(
                      "common.retry"
                    )}
                  </button>
                </div>
              ) : (
                <label className="text-xs font-black text-slate-600">
                  {t(
                    "products.packageType"
                  )}
                  <select
                    value={
                      draft.package_uom_code
                    }
                    onChange={(event) =>
                      onPackageUomChange(
                        event.target.value
                      )
                    }
                    className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-bold"
                  >
                    {packageUoms.map(
                      (uom) => (
                        <option
                          key={
                            uom.code
                          }
                          value={
                            uom.code
                          }
                        >
                          {t(
                            `uom.${uom.code}`
                          )}
                        </option>
                      )
                    )}
                  </select>
                </label>
              )}

              <label className="text-xs font-black text-slate-600">
                {t(
                  "products.unitsPerPackage"
                )}
                <input
                  ref={createUnitsRef}
                  inputMode="numeric"
                  value={
                    draft.units_per_package
                  }
                  onChange={(event) =>
                  onUnitsPerPackageChange(
                    event.target.value
                  )
                }
                  aria-invalid={
                    createFieldError?.field ===
                    "units"
                      ? "true"
                      : undefined
                  }
                  aria-describedby={
                    createFieldError?.field ===
                    "units"
                      ? "product-units-error"
                      : undefined
                  }
                  className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-bold"
                />
                {createFieldError?.field ===
                "units" ? (
                  <span
                    id="product-units-error"
                    role="alert"
                    className="mt-1 block text-[11px] font-bold text-rose-700"
                  >
                    {createFieldError.message}
                  </span>
                ) : null}
              </label>
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2">
            {draft.has_package ? (
              <label className="text-xs font-black text-slate-600">
                {t(
                  "products.packagePrice"
                )}{" "}
                <span className="font-bold text-slate-400">
                  {t(
                    "common.optional"
                  )}
                </span>
                <input
                  ref={createPackagePriceRef}
                  inputMode="decimal"
                  value={
                    draft.package_price
                  }
                  onChange={(event) =>
                    onPackagePriceChange(
                      event.target.value
                    )
                  }
                  placeholder={t(
                    "products.packagePricePlaceholder"
                  )}
                  aria-invalid={
                    createFieldError?.field ===
                    "packagePrice"
                      ? "true"
                      : undefined
                  }
                  aria-describedby={
                    createFieldError?.field ===
                    "packagePrice"
                      ? "product-package-price-error"
                      : undefined
                  }
                  className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-black"
                />
                {createFieldError?.field ===
                "packagePrice" ? (
                  <span
                    id="product-package-price-error"
                    role="alert"
                    className="mt-1 block text-[11px] font-bold text-rose-700"
                  >
                    {createFieldError.message}
                  </span>
                ) : null}
              </label>
            ) : null}

            <label className="text-xs font-black text-slate-600">
              {t(
                "products.unitPrice"
              )}{" "}
              {draft.has_package ? (
                <span className="font-bold text-slate-400">
                  {t(
                    "common.optional"
                  )}
                </span>
              ) : null}
              <input
                ref={createUnitPriceRef}
                inputMode="decimal"
                value={
                  draft.unit_price
                }
                onChange={(event) =>
                  onUnitPriceChange(
                    event.target.value
                  )
                }
                placeholder={t(
                  "products.unitPricePlaceholder"
                )}
                aria-invalid={
                  createFieldError?.field ===
                  "unitPrice"
                    ? "true"
                    : undefined
                }
                aria-describedby={
                  createFieldError?.field ===
                  "unitPrice"
                    ? "product-unit-price-error"
                    : undefined
                }
                className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-black"
              />
              {createFieldError?.field ===
              "unitPrice" ? (
                <span
                  id="product-unit-price-error"
                  role="alert"
                  className="mt-1 block text-[11px] font-bold text-rose-700"
                >
                  {createFieldError.message}
                </span>
              ) : null}
            </label>
          </div>

          {draftDerived ? (
            <div className="rounded-2xl bg-emerald-50 p-3 text-xs font-bold leading-6 text-emerald-900">
              {draft.has_package &&
              draftDerived.independent
                ? t(
                    "products.independentPrices"
                  )
                : draft.has_package
                  ? t(
                      "products.derivedPrice"
                    )
                  : t(
                      "products.unitPrice"
                    )}
            </div>
          ) : null}

          <section className="rounded-2xl border border-slate-200 bg-white">
            <button
              type="button"
              onClick={onToggleAdvanced}
              aria-expanded={
                createAdvancedExpanded
              }
              className="flex w-full items-center justify-between gap-4 p-4 text-start"
            >
              <span>
                <span className="block text-sm font-black text-slate-900">
                  {t(
                    "products.quickCreate.advancedTitle"
                  )}
                </span>
                <span className="mt-1 block text-[11px] font-semibold leading-5 text-slate-500">
                  {t(
                    "products.quickCreate.advancedHint"
                  )}
                </span>
              </span>
              <span className="shrink-0 text-xs font-black text-slate-600">
                {t(
                  createAdvancedExpanded
                    ? "products.quickCreate.hideAdvanced"
                    : "products.quickCreate.showAdvanced"
                )}
              </span>
            </button>

            {createAdvancedExpanded ? (
              <div className="space-y-4 border-t border-slate-100 p-4">
                <div className="rounded-xl bg-slate-50 p-3 text-[11px] font-semibold leading-5 text-slate-600">
                  {t(
                    "products.quickCreate.systemManagedHint"
                  )}
                </div>

                <div className="space-y-3">
                  <div>
                    <h4 className="text-xs font-black text-slate-800">
                      {t(
                        "products.tracking.createTitle"
                      )}
                    </h4>
                    <p className="mt-1 text-[11px] font-semibold leading-5 text-slate-500">
                      {t(
                        "products.tracking.createOnlyThisProduct"
                      )}
                    </p>
                  </div>

                  {!createTrackingExpanded ? (
                    <button
                      type="button"
                      onClick={onExpandTracking}
                      className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700"
                    >
                      {t(
                        "products.tracking.createChange"
                      )}
                    </button>
                  ) : (
                    <div className="space-y-3">
                      <ProductTrackingFields
                        lotControlMode={
                          draft.lot_control_mode
                        }
                        expiryControlMode={
                          draft.expiry_control_mode
                        }
                        onLotControlModeChange={
                          onLotControlModeChange
                        }
                                                onExpiryControlModeChange={
                          onExpiryControlModeChange
                        }
                      />

                      {!trackingUsesCompanyDefaults ? (
                        <button
                          type="button"
                          onClick={onResetTracking}
                          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700"
                        >
                          {t(
                            "products.tracking.createReset"
                          )}
                        </button>
                      ) : null}
                    </div>
                  )}
                </div>

                <div className="border-t border-slate-100 pt-4">
                  <h4 className="text-xs font-black text-slate-800">
                    {t(
                      "products.barcodeSection"
                    )}
                  </h4>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <label className="text-xs font-bold text-slate-500">
                {t(
                  "products.unitBarcode"
                )}
                <input
                  value={
                    draft.unit_barcode
                  }
                  onChange={(event) =>
                    onUnitBarcodeChange(
                      event.target.value
                    )
                  }
                  className="mt-1.5 w-full rounded-xl border border-slate-200 p-2.5 font-mono"
                />
              </label>

              {draft.has_package ? (
                <label className="text-xs font-bold text-slate-500">
                  <span className="flex items-center justify-between gap-2">
                    <span>
                      {t(
                        "products.packageBarcode"
                      )}
                    </span>
                    <button
                      type="button"
                      disabled={
                        !draft.unit_barcode.trim()
                      }
                      onClick={onCopyBarcode}
                      title={t(
                        "products.copyBarcode"
                      )}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-[10px] font-black text-slate-600 disabled:opacity-30"
                    >
                      <Copy className="h-3 w-3" />
                      {t(
                        "products.copyBarcode"
                      )}
                    </button>
                  </span>
                  <input
                    value={
                      draft.package_barcode
                    }
                    onChange={(event) =>
                      onPackageBarcodeChange(
                        event.target.value
                      )
                    }
                    className="mt-1.5 w-full rounded-xl border border-slate-200 p-2.5 font-mono"
                  />
                </label>
              ) : null}
                  </div>
                </div>
              </div>
            ) : null}
          </section>
        </div>
      </Modal>
  );
}
