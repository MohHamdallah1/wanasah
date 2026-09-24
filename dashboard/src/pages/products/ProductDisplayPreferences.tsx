import {
  useEffect,
  useState,
} from "react";
import {
  SlidersHorizontal,
} from "lucide-react";
import {
  useTranslation,
} from "react-i18next";

import { Modal } from "@/components/ui/modal";
import {
  DEFAULT_PRODUCT_DISPLAY_PREFERENCES,
  type ProductDisplayColumn,
  type ProductDisplayPreferences,
  type ProductDetailSection,
  type ProductDisplaySortField,
} from "@/lib/productDisplayPreferences";

type Props = {
  open: boolean;
  preferences: ProductDisplayPreferences;
  pricingAvailable: boolean;
  onClose: () => void;
  onSave: (
    preferences: ProductDisplayPreferences,
  ) => void;
};

const COLUMNS: ProductDisplayColumn[] =
  [
    "package",
    "unitsPerPackage",
    "tracking",
    "lifecycle",
    "unitBarcode",
    "packageBarcode",
    "packagePrice",
    "unitPrice",
  ];

const DETAIL_SECTIONS: ProductDetailSection[] =
  [
    "package",
    "tracking",
    "barcodes",
    "pricing",
    "compatibility",
  ];

const SORT_FIELDS: ProductDisplaySortField[] =
  [
    "id",
    "name",
    "family",
    "sku",
    "lifecycle",
  ];

const clonePreferences = (
  preferences: ProductDisplayPreferences,
): ProductDisplayPreferences => ({
  version: preferences.version,
  columns: {
    ...preferences.columns,
  },
  density: preferences.density,
  defaultSort: {
    ...preferences.defaultSort,
  },
  detailSections: {
    ...preferences.detailSections,
  },
});

export function ProductDisplayPreferencesModal({
  open,
  preferences,
  pricingAvailable,
  onClose,
  onSave,
}: Props) {
  const { t } =
    useTranslation();
  const [draft, setDraft] =
    useState<ProductDisplayPreferences>(
      () =>
        clonePreferences(
          preferences,
        ),
    );

  useEffect(() => {
    if (open) {
      setDraft(
        clonePreferences(
          preferences,
        ),
      );
    }
  }, [open, preferences]);

  const setColumn = (
    column: ProductDisplayColumn,
    checked: boolean,
  ) =>
    setDraft((current) => ({
      ...current,
      columns: {
        ...current.columns,
        [column]: checked,
      },
    }));

  const setSection = (
    section: ProductDetailSection,
    checked: boolean,
  ) =>
    setDraft((current) => ({
      ...current,
      detailSections: {
        ...current.detailSections,
        [section]: checked,
      },
    }));

  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title={t(
        "products.displayPreferences.title",
      )}
      maxWidth="max-w-3xl"
      footer={
        <>
          <button
            type="button"
            onClick={() =>
              setDraft(
                clonePreferences(
                  DEFAULT_PRODUCT_DISPLAY_PREFERENCES,
                ),
              )
            }
            className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-black text-slate-600"
          >
            {t(
              "products.displayPreferences.restoreDefaults",
            )}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-black text-slate-600"
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            onClick={() =>
              onSave(
                clonePreferences(
                  draft,
                ),
              )
            }
            className="rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-black text-white"
          >
            {t("common.save")}
          </button>
        </>
      }
    >
      <div className="space-y-5">
        <p className="rounded-2xl bg-slate-50 p-3 text-xs font-bold leading-6 text-slate-600">
          {t(
            "products.displayPreferences.userScopedHint",
          )}
        </p>

        <section className="rounded-2xl border border-slate-200 p-4">
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4 text-slate-500" />
            <h3 className="text-sm font-black text-slate-900">
              {t(
                "products.displayPreferences.visibleColumns",
              )}
            </h3>
          </div>
          <p className="mt-1 text-[11px] font-semibold leading-5 text-slate-500">
            {t(
              "products.displayPreferences.fixedColumnsHint",
            )}
          </p>

          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {COLUMNS.map(
              (column) => {
                const pricingColumn =
                  column ===
                    "packagePrice" ||
                  column ===
                    "unitPrice";
                return (
                  <label
                    key={column}
                    className="flex items-start gap-2 rounded-xl bg-slate-50 p-3 text-xs font-bold text-slate-700"
                  >
                    <input
                      type="checkbox"
                      checked={
                        draft.columns[
                          column
                        ]
                      }
                      disabled={
                        pricingColumn &&
                        !pricingAvailable
                      }
                      onChange={(
                        event,
                      ) =>
                        setColumn(
                          column,
                          event.target
                            .checked,
                        )
                      }
                      className="mt-0.5"
                    />
                    <span className="min-w-0 break-words">
                      {t(
                        `products.displayPreferences.columns.${column}`,
                      )}
                    </span>
                  </label>
                );
              },
            )}
          </div>
        </section>

        <section className="grid gap-4 rounded-2xl border border-slate-200 p-4 sm:grid-cols-2">
          <label className="text-xs font-black text-slate-600">
            {t(
              "products.displayPreferences.density",
            )}
            <select
              value={draft.density}
              onChange={(event) =>
                setDraft(
                  (current) => ({
                    ...current,
                    density:
                      event.target
                        .value as ProductDisplayPreferences["density"],
                  }),
                )
              }
              className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-bold"
            >
              <option value="comfortable">
                {t(
                  "products.displayPreferences.densities.comfortable",
                )}
              </option>
              <option value="compact">
                {t(
                  "products.displayPreferences.densities.compact",
                )}
              </option>
            </select>
          </label>

          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs font-black text-slate-600">
              {t(
                "products.displayPreferences.defaultSort",
              )}
              <select
                value={
                  draft.defaultSort
                    .field
                }
                onChange={(
                  event,
                ) =>
                  setDraft(
                    (current) => ({
                      ...current,
                      defaultSort: {
                        ...current.defaultSort,
                        field:
                          event.target
                            .value as ProductDisplaySortField,
                      },
                    }),
                  )
                }
                className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-bold"
              >
                {SORT_FIELDS.map(
                  (field) => (
                    <option
                      key={field}
                      value={field}
                    >
                      {t(
                        `products.filters.sortFields.${field}`,
                      )}
                    </option>
                  ),
                )}
              </select>
            </label>

            <label className="text-xs font-black text-slate-600">
              {t(
                "products.filters.sortDirection",
              )}
              <select
                value={
                  draft.defaultSort
                    .direction
                }
                onChange={(
                  event,
                ) =>
                  setDraft(
                    (current) => ({
                      ...current,
                      defaultSort: {
                        ...current.defaultSort,
                        direction:
                          event.target
                            .value as ProductDisplayPreferences["defaultSort"]["direction"],
                      },
                    }),
                  )
                }
                className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-bold"
              >
                <option value="asc">
                  {t(
                    "products.filters.ascending",
                  )}
                </option>
                <option value="desc">
                  {t(
                    "products.filters.descending",
                  )}
                </option>
              </select>
            </label>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 p-4">
          <h3 className="text-sm font-black text-slate-900">
            {t(
              "products.displayPreferences.detailSections",
            )}
          </h3>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {DETAIL_SECTIONS.map(
              (section) => {
                const pricingSection =
                  section ===
                  "pricing";
                return (
                  <label
                    key={section}
                    className="flex items-start gap-2 rounded-xl bg-slate-50 p-3 text-xs font-bold text-slate-700"
                  >
                    <input
                      type="checkbox"
                      checked={
                        draft
                          .detailSections[
                          section
                        ]
                      }
                      disabled={
                        pricingSection &&
                        !pricingAvailable
                      }
                      onChange={(
                        event,
                      ) =>
                        setSection(
                          section,
                          event.target
                            .checked,
                        )
                      }
                      className="mt-0.5"
                    />
                    <span className="min-w-0 break-words">
                      {t(
                        `products.displayPreferences.detailSectionsOptions.${section}`,
                      )}
                    </span>
                  </label>
                );
              },
            )}
          </div>
        </section>
      </div>
    </Modal>
  );
}
