import {
  Check,
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
    <div className="group grid min-h-14 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-slate-100 px-4 py-2.5 last:border-b-0 hover:bg-slate-50/70">
      <div className="min-w-0">
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
          <>
            <strong className="block break-words text-sm font-black text-slate-900">
              {family.name}
            </strong>
            <span className="mt-0.5 block text-[10px] font-bold text-slate-400">
              {t(
                "products.variantCount",
                {
                  count:
                    family.variant_count,
                }
              )}
            </span>
          </>
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

      <div className="flex items-center gap-1">
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
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-transparent text-slate-400 opacity-100 transition hover:border-slate-200 hover:bg-white hover:text-slate-800 sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}
