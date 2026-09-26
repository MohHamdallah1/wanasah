import {
  useEffect,
  useRef,
} from "react";
import {
  Check,
  Pencil,
  Trash2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  ProductFamily,
} from "@/pages/products/contracts";

type Props = {
  family: ProductFamily;
  ordinal: number;
  editing: boolean;
  editingFamilyName: string;
  renameCommandPending: boolean;
  renameCommandBlocked: boolean;
  updatePending: boolean;
  deleteConfirming: boolean;
  deletePending: boolean;
  deleteCommandPending: boolean;
  deleteCommandBlocked: boolean;
  online: boolean;
  onEdit: (
    family: ProductFamily,
  ) => void;
  onEditingNameChange: (
    value: string,
  ) => void;
  onSave: () => void;
  onCancelEdit: () => void;
  onDeleteRequest: (
    family: ProductFamily,
  ) => void;
  onDeleteConfirm: () => void;
  onDeleteCancel: () => void;
};

export function ProductFamilyRow({
  family,
  ordinal,
  editing,
  editingFamilyName,
  renameCommandPending,
  renameCommandBlocked,
  updatePending,
  deleteConfirming,
  deletePending,
  deleteCommandPending,
  deleteCommandBlocked,
  online,
  onEdit,
  onEditingNameChange,
  onSave,
  onCancelEdit,
  onDeleteRequest,
  onDeleteConfirm,
  onDeleteCancel,
}: Props) {
  const { t } = useTranslation();
  const deleteTriggerRef =
    useRef<HTMLButtonElement | null>(
      null
    );
  const wasDeleteConfirming =
    useRef(deleteConfirming);

  useEffect(() => {
    if (
      wasDeleteConfirming.current &&
      !deleteConfirming
    ) {
      window.requestAnimationFrame(
        () =>
          deleteTriggerRef.current?.focus()
      );
    }
    wasDeleteConfirming.current =
      deleteConfirming;
  }, [deleteConfirming]);

  return (
    <div className="group flex min-h-16 items-center gap-3 border-b border-slate-100 px-4 py-3 last:border-b-0 hover:bg-slate-50/70 sm:px-5">
      <span
        aria-hidden="true"
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-xs font-black tabular-nums text-slate-500"
      >
        {ordinal}
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
            onKeyDown={(event) => {
              if (
                event.nativeEvent
                  .isComposing
              ) {
                return;
              }
              if (
                event.key === "Enter"
              ) {
                event.preventDefault();
                onSave();
              } else if (
                event.key === "Escape"
              ) {
                event.preventDefault();
                onCancelEdit();
              }
            }}
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
        ) : deleteConfirming &&
          deleteCommandPending ? (
          <p className="mt-1 text-[10px] font-semibold text-amber-700">
            {t(
              "products.familyDeletePending"
            )}
          </p>
        ) : deleteConfirming &&
          deleteCommandBlocked ? (
          <p className="mt-1 text-[10px] font-semibold text-rose-700">
            {t(
              "products.familyDeletePendingBlocked"
            )}
          </p>
        ) : null}
      </div>

      <div className="flex shrink-0 items-center gap-1">
        {deleteConfirming ? (
          <>
            <span className="hidden text-[11px] font-bold text-rose-700 lg:inline">
              {t(
                "products.familyDeleteQuestion"
              )}
            </span>
            <button
              type="button"
              autoFocus
              aria-label={t(
                deleteCommandPending
                  ? "products.retryFamilyDelete"
                  : "products.familyDeleteConfirm"
              )}
              title={t(
                deleteCommandPending
                  ? "products.retryFamilyDelete"
                  : "products.familyDeleteConfirm"
              )}
              disabled={
                deletePending ||
                deleteCommandBlocked ||
                !online
              }
              onClick={
                onDeleteConfirm
              }
              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg bg-rose-600 px-2.5 text-[11px] font-black text-white transition hover:bg-rose-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400 disabled:opacity-40"
            >
              <Trash2 className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">
                {t(
                  deleteCommandPending
                    ? "products.retryFamilyDelete"
                    : "products.familyDeleteConfirm"
                )}
              </span>
            </button>
            <button
              type="button"
              aria-label={t(
                "common.cancel"
              )}
              title={t(
                "common.cancel"
              )}
              disabled={
                deletePending ||
                deleteCommandPending ||
                deleteCommandBlocked
              }
              onClick={
                onDeleteCancel
              }
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition hover:bg-white hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 disabled:opacity-40"
            >
              <X className="h-4 w-4" />
            </button>
          </>
        ) : editing ? (
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
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-slate-950 text-white transition hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:opacity-40"
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
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition hover:bg-white hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300"
            >
              <X className="h-4 w-4" />
            </button>
          </>
        ) : (
          <>
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
              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-bold text-slate-500 transition hover:border-slate-300 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300"
            >
              <Pencil className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">
                {t("common.edit")}
              </span>
            </button>

            <button
              ref={deleteTriggerRef}
              type="button"
              aria-label={t(
                "products.deleteFamily"
              )}
              title={t(
                family.variant_count > 0
                  ? "products.familyDeleteBlocked"
                  : "products.deleteFamily",
                {
                  count:
                    family.variant_count,
                }
              )}
              onClick={() =>
                onDeleteRequest(
                  family
                )
              }
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-transparent text-slate-400 transition hover:border-rose-100 hover:bg-rose-50 hover:text-rose-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </>
        )}
      </div>
    </div>
  );
}
