import {
  ChevronLeft,
  ChevronRight,
  FolderTree,
  RefreshCw,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  ProductFamily,
} from "@/pages/products/contracts";
import { ProductFamilyRow } from "@/pages/products/family/ProductFamilyRow";

type Props = {
  families: ProductFamily[];
  loading: boolean;
  error: boolean;
  fetching: boolean;
  search: string;
  hasPrevious: boolean;
  hasNext: boolean;
  editingFamilyId: number | null;
  editingFamilyName: string;
  renameCommandPending: boolean;
  renameCommandBlocked: boolean;
  updatePending: boolean;
  online: boolean;
  onRetry: () => void;
  onEdit: (
    family: ProductFamily,
  ) => void;
  onEditingNameChange: (
    value: string,
  ) => void;
  onSaveEdit: () => void;
  onCancelEdit: () => void;
  onPrevious: () => void;
  onNext: () => void;
};

export function ProductFamiliesList({
  families,
  loading,
  error,
  fetching,
  search,
  hasPrevious,
  hasNext,
  editingFamilyId,
  editingFamilyName,
  renameCommandPending,
  renameCommandBlocked,
  updatePending,
  online,
  onRetry,
  onEdit,
  onEditingNameChange,
  onSaveEdit,
  onCancelEdit,
  onPrevious,
  onNext,
}: Props) {
  const { t, i18n } =
    useTranslation();
  const rtl =
    i18n.dir() === "rtl";

  const PreviousIcon = rtl
    ? ChevronRight
    : ChevronLeft;
  const NextIcon = rtl
    ? ChevronLeft
    : ChevronRight;

  return (
    <div className="min-h-[220px]">
      <div className="min-h-[220px]">
        {loading ? (
          <div className="flex min-h-[220px] items-center justify-center text-xs font-bold text-slate-400">
            {t("common.loading")}
          </div>
        ) : error ? (
          <div className="flex min-h-[220px] flex-col items-center justify-center px-6 text-center">
            <p className="text-xs font-black text-rose-800">
              {t(
                "products.errors.familiesLoad"
              )}
            </p>
            <button
              type="button"
              onClick={onRetry}
              className="mt-3 inline-flex h-9 items-center gap-2 rounded-xl border border-rose-200 bg-white px-3 text-xs font-black text-rose-700"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              {t("common.retry")}
            </button>
          </div>
        ) : !families.length ? (
          <div className="flex min-h-[220px] flex-col items-center justify-center px-6 text-center">
            <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-400">
              <FolderTree className="h-5 w-5" />
            </span>
            <p className="text-xs font-black text-slate-500">
              {t(
                search
                  ? "products.noMatchingFamilies"
                  : "products.noFamilies"
              )}
            </p>
          </div>
        ) : (
          families.map(
            (family) => (
              <ProductFamilyRow
                key={family.id}
                family={family}
                editing={
                  editingFamilyId ===
                  family.id
                }
                editingFamilyName={
                  editingFamilyName
                }
                renameCommandPending={
                  renameCommandPending
                }
                renameCommandBlocked={
                  renameCommandBlocked
                }
                updatePending={
                  updatePending
                }
                online={online}
                onEdit={onEdit}
                onEditingNameChange={
                  onEditingNameChange
                }
                onSave={
                  onSaveEdit
                }
                onCancelEdit={
                  onCancelEdit
                }
              />
            )
          )
        )}
      </div>

      {hasPrevious ||
      hasNext ? (
        <div className="flex items-center justify-end gap-1 border-t border-slate-100 bg-slate-50/60 px-4 py-2.5 sm:px-5">
          <button
            type="button"
            aria-label={t(
              "products.familyPrevious"
            )}
            title={t(
              "products.familyPrevious"
            )}
            disabled={
              !hasPrevious ||
              fetching
            }
            onClick={onPrevious}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:text-slate-900 disabled:opacity-30"
          >
            <PreviousIcon className="h-4 w-4" />
          </button>
          <button
            type="button"
            aria-label={t(
              "products.familyNext"
            )}
            title={t(
              "products.familyNext"
            )}
            disabled={
              !hasNext ||
              fetching
            }
            onClick={onNext}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:text-slate-900 disabled:opacity-30"
          >
            <NextIcon className="h-4 w-4" />
          </button>
        </div>
      ) : null}
    </div>
  );
}
