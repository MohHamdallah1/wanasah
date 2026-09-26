import {
  Check,
  FolderTree,
  Pencil,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  ProductFamily,
} from "@/pages/products/contracts";

type Props = {
  family: ProductFamily;
  editing: boolean;
  editingFamilyName: string;
  renameCommandPending: boolean;
  renameCommandBlocked: boolean;
  updatePending: boolean;
  online: boolean;
  onEdit: (
    family: ProductFamily,
  ) => void;
  onEditingNameChange: (
    value: string,
  ) => void;
  onSave: () => void;
  onCancelEdit: () => void;
};

export function ProductFamilyRow({
  family,
  editing,
  editingFamilyName,
  renameCommandPending,
  renameCommandBlocked,
  updatePending,
  online,
  onEdit,
  onEditingNameChange,
  onSave,
  onCancelEdit,
}: Props) {
  const { t } = useTranslation();

  return (
    <div className="group flex min-h-16 items-center gap-3 border-b border-slate-100 px-4 py-3 last:border-b-0 hover:bg-slate-50/70 sm:px-5">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-50 text-amber-700">
        <FolderTree className="h-4 w-4" />
      </span>

      <div className="min-w-0 flex-1">
        {editing ? (
          <input
            autoFocus
            aria-label={t(
              "products.family"
            )}
            value={
              editingFamilyName
            }
            maxLength={150}
            disabled={
              renameCommandPending ||
              renameCommandBlocked
            }
            onChange={(event) =>
              onEditingNameChange(
                event.target.value
              )
            }
            className="h-9 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm font-black text-slate-900 outline-none focus:ring-2 focus:ring-amber-300"
          />
        ) : (
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <strong className="min-w-0 break-words text-sm font-black text-slate-900">
              {family.name}
            </strong>
            <span className="inline-flex shrink-0 items-center rounded-full bg-slate-100 px-2 py-1 text-[10px] font-bold text-slate-500">
              {t(
                "products.variantCount",
                {
                  count:
                    family.variant_count,
                }
              )}
            </span>
          </div>
        )}

        {editing &&
        renameCommandPending ? (
          <p className="mt-1 text-[10px] font-semibold text-amber-700">
            {t(
              "products.familyPendingRetry"
            )}
          </p>
        ) : editing &&
          renameCommandBlocked ? (
          <p className="mt-1 text-[10px] font-semibold text-rose-700">
            {t(
              "products.familyPendingBlocked"
            )}
          </p>
        ) : null}
      </div>

      <div className="flex shrink-0 items-center gap-1">
        {editing ? (
          <>
            <button
              type="button"
              aria-label={t(
                "common.save"
              )}
              title={t(
                "common.save"
              )}
              disabled={
                updatePending ||
                renameCommandBlocked ||
                !online
              }
              onClick={onSave}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-slate-950 text-white transition hover:bg-slate-800 disabled:opacity-40"
            >
              <Check className="h-4 w-4" />
            </button>
            <button
              type="button"
              aria-label={t(
                "common.cancel"
              )}
              title={t(
                "common.cancel"
              )}
              onClick={
                onCancelEdit
              }
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition hover:bg-white hover:text-slate-800"
            >
              <X className="h-4 w-4" />
            </button>
          </>
        ) : (
          <button
            type="button"
            aria-label={t(
              "common.edit"
            )}
            title={t(
              "common.edit"
            )}
            onClick={() =>
              onEdit(family)
            }
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-bold text-slate-500 transition hover:border-slate-300 hover:text-slate-900"
          >
            <Pencil className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">
              {t("common.edit")}
            </span>
          </button>
        )}
      </div>
    </div>
  );
}
