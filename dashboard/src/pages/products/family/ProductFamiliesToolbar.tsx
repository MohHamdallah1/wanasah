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
    <div className="shrink-0 border-b border-slate-100 bg-white px-4 py-3 sm:px-5">
      <div className="relative">
        <Search className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
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
          className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pe-3 ps-10 text-sm font-normal text-slate-900 outline-none transition placeholder:font-normal placeholder:text-slate-400 focus:ring-2 focus:ring-blue-500/20"
        />
      </div>

      <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50/70 p-2.5">
        <label className="block min-w-0">
          <span className="mb-1.5 block text-[11px] font-black text-slate-600">
            {t(
              "products.newFamilyTitle"
            )}
          </span>

          <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
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
              className="h-10 min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold text-slate-900 outline-none transition placeholder:font-normal placeholder:text-slate-400 focus:ring-2 focus:ring-amber-300 disabled:bg-slate-100 disabled:text-slate-400"
            />

            <button
              type="button"
              disabled={
                createPending ||
                createCommandBlocked ||
                !online
              }
              onClick={onCreate}
              className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-xl bg-amber-400 px-4 text-xs font-black text-slate-950 shadow-sm transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <FolderPlus className="h-4 w-4" />
              {t("products.addFamily")}
            </button>
          </div>
        </label>

        {newFamilyError ? (
          <p
            id="product-family-name-error"
            role="alert"
            className="mt-2 text-[11px] font-bold text-rose-700"
          >
            {newFamilyError}
          </p>
        ) : null}

        {createCommandPending ? (
          <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-[10px] font-semibold leading-4 text-amber-900">
            {t(
              "products.familyPendingRetry"
            )}
          </p>
        ) : createCommandBlocked ? (
          <p className="mt-2 rounded-lg bg-rose-50 px-3 py-2 text-[10px] font-semibold leading-4 text-rose-900">
            {t(
              "products.familyPendingBlocked"
            )}
          </p>
        ) : null}
      </div>
    </div>
  );
}
