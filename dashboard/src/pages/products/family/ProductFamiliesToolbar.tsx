import type {
  RefObject,
} from "react";
import {
  FolderPlus,
  Search,
} from "lucide-react";
import { useTranslation } from "react-i18next";

type Props = {
  searchInput: string;
  newFamilyName: string;
  newFamilyError: string | null;
  createCommandPending: boolean;
  createCommandBlocked: boolean;
  createPending: boolean;
  online: boolean;
  newFamilyRef: RefObject<HTMLInputElement>;
  onSearchChange: (value: string) => void;
  onNewFamilyNameChange: (value: string) => void;
  onCreate: () => void;
};

export function ProductFamiliesToolbar({
  searchInput,
  newFamilyName,
  newFamilyError,
  createCommandPending,
  createCommandBlocked,
  createPending,
  online,
  newFamilyRef,
  onSearchChange,
  onNewFamilyNameChange,
  onCreate,
}: Props) {
  const { t } = useTranslation();

  return (
    <div className="space-y-3 border-b border-slate-100 p-4">
      <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <div className="relative min-w-0">
          <Search className="absolute end-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="search"
            value={searchInput}
            maxLength={100}
            onChange={(event) =>
              onSearchChange(
                event.target.value
              )
            }
            placeholder={t(
              "products.familySearchPlaceholder"
            )}
            aria-label={t(
              "products.familySearchPlaceholder"
            )}
            className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50/70 py-2 pe-10 ps-3 text-sm font-bold text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-slate-400 focus:bg-white focus:ring-2 focus:ring-slate-100"
          />
        </div>

        <input
          ref={newFamilyRef}
          value={newFamilyName}
          maxLength={150}
          disabled={
            createCommandPending ||
            createCommandBlocked
          }
          onChange={(event) =>
            onNewFamilyNameChange(
              event.target.value
            )
          }
          placeholder={t(
            "products.newFamilyPlaceholder"
          )}
          aria-label={t(
            "products.newFamilyPlaceholder"
          )}
          aria-invalid={
            newFamilyError
              ? "true"
              : undefined
          }
          aria-describedby={
            newFamilyError
              ? "product-family-name-error"
              : undefined
          }
          className="h-10 min-w-0 rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-slate-400 focus:ring-2 focus:ring-slate-100 disabled:bg-slate-50 disabled:text-slate-400"
        />

        <button
          type="button"
          disabled={
            createPending ||
            createCommandBlocked ||
            !online
          }
          onClick={onCreate}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-amber-400 px-4 text-xs font-black text-slate-950 shadow-sm transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <FolderPlus className="h-4 w-4" />
          {t("products.addFamily")}
        </button>
      </div>

      {newFamilyError ? (
        <p
          id="product-family-name-error"
          role="alert"
          className="text-[11px] font-bold text-rose-700"
        >
          {newFamilyError}
        </p>
      ) : null}

      {createCommandPending ? (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-[10px] font-semibold leading-4 text-amber-900">
          {t(
            "products.familyPendingRetry"
          )}
        </p>
      ) : createCommandBlocked ? (
        <p className="rounded-lg bg-rose-50 px-3 py-2 text-[10px] font-semibold leading-4 text-rose-900">
          {t(
            "products.familyPendingBlocked"
          )}
        </p>
      ) : null}
    </div>
  );
}
