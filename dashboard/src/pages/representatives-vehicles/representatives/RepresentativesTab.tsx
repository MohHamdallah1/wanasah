import { useState } from "react";
import { type InfiniteData, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Plus, RefreshCw, Search, UsersRound, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { createRepresentative, updateRepresentative } from "./api";
import type {
  CreateRepresentativeInput,
  Representative,
  RepresentativeListResult,
  RepresentativeStatusFilter,
  UpdateRepresentativeInput,
} from "./contracts";
import { RepresentativeCredentialAction } from "./RepresentativeCredentialAction";
import { representativeErrorMessage } from "./representativeErrorMessage";
import { RepresentativeForm } from "./RepresentativeForm";
import { RepresentativeLifecycleActions } from "./RepresentativeLifecycleActions";
import { RepresentativeTable } from "./RepresentativeTable";
import { useRepresentativeInfiniteScroll } from "./useRepresentativeInfiniteScroll";
import { useRepresentatives } from "./useRepresentatives";

const filters: RepresentativeStatusFilter[] = ["all", "active", "inactive"];

type RepresentativeAction = {
  type: "edit" | "lifecycle" | "credentials";
  representative: Representative;
};

export function RepresentativesTab() {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const queryClient = useQueryClient();
  const representatives = useRepresentatives();
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [action, setAction] = useState<RepresentativeAction | null>(null);
  const [editing, setEditing] = useState(false);

  const canManage = Boolean(
    access.isCompanyOwner || access.can("representative.manage"),
  );
  const canResetCredentials = Boolean(
    access.isCompanyOwner || access.can("representative.credentials.reset"),
  );
  const hasLoadedRows = representatives.items.length > 0;
  const hasCursorPageError = Boolean(representatives.query.isFetchNextPageError);
  const hasRetainedDataError = representatives.query.isError && hasLoadedRows;

  const infiniteScroll = useRepresentativeInfiniteScroll({
    hasMore: Boolean(representatives.query.hasNextPage) && !hasCursorPageError,
    isFetchingNextPage: representatives.query.isFetchingNextPage,
    onLoadMore: representatives.query.fetchNextPage,
  });

  const closeCreate = () => {
    if (creating) return;
    setCreateOpen(false);
  };

  const closeEdit = () => {
    if (editing) return;
    setAction(null);
  };

  const create = async (input: CreateRepresentativeInput, requestId: string) => {
    setCreating(true);
    try {
      await createRepresentative(authFetch, input, requestId);
      await queryClient.invalidateQueries({ queryKey: ["representatives"] });
      toast.success(t("representativesVehicles.representatives.createSuccess"));
      setCreateOpen(false);
    } catch (error) {
      toast.error(
        representativeErrorMessage(
          error,
          t("representativesVehicles.representatives.saveFailed"),
        ),
      );
    } finally {
      setCreating(false);
    }
  };

  const replaceRepresentativeInCachedLists = (updated: Representative) => {
    queryClient.setQueriesData<InfiniteData<RepresentativeListResult>>(
      { queryKey: ["representatives"] },
      (cached) => {
        if (!cached) return cached;
        return {
          ...cached,
          pages: cached.pages.map((page) => ({
            ...page,
            items: page.items.map((item) => item.id === updated.id ? updated : item),
          })),
        };
      },
    );
  };

  const saveEdit = async (input: UpdateRepresentativeInput, requestId: string) => {
    const target = action?.type === "edit" ? action.representative : null;
    if (!target) return;
    setEditing(true);
    try {
      const updated = await updateRepresentative(authFetch, target.id, input, requestId);
      replaceRepresentativeInCachedLists(updated);
      await queryClient.invalidateQueries({ queryKey: ["representatives"] });
      toast.success(t("representativesVehicles.representatives.updateSuccess"));
      setAction(null);
    } catch (error) {
      toast.error(
        representativeErrorMessage(
          error,
          t("representativesVehicles.representatives.saveFailed"),
        ),
      );
    } finally {
      setEditing(false);
    }
  };

  const retryRetainedData = () => {
    if (hasCursorPageError && representatives.query.hasNextPage) {
      void representatives.query.fetchNextPage();
      return;
    }
    void representatives.query.refetch();
  };

  const searchNeedsMore = representatives.input.trim().length === 1;

  return (
    <section className="flex h-full min-h-0 flex-1 flex-col gap-0 overflow-hidden" aria-labelledby="representatives-tab-heading">
      <h2 id="representatives-tab-heading" className="sr-only">{t("representativesVehicles.tabs.representatives")}</h2>

      <div className="flex shrink-0 flex-col gap-2.5 rounded-t-xl border border-b-0 border-slate-200/80 bg-white px-3 py-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)] sm:px-4 lg:flex-row lg:items-center">
        <div className="min-w-0 flex-1">
          <div className="relative">
            <Search className="pointer-events-none absolute start-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="search"
              value={representatives.input}
              onChange={(event) => representatives.setInput(event.target.value.slice(0, 100))}
              placeholder={t("representativesVehicles.representatives.search")}
              aria-label={t("representativesVehicles.representatives.search")}
              maxLength={100}
              className="h-11 w-full rounded-2xl border border-slate-200/80 bg-white pe-10 ps-10 text-sm font-semibold text-slate-800 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-cyan-300 focus:ring-4 focus:ring-cyan-100/60"
            />
            {representatives.input ? (
              <button type="button" onClick={() => representatives.setInput("")} aria-label={t("representativesVehicles.representatives.clearSearch")}
                className="absolute end-2.5 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-full text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">
                <X className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>
          {searchNeedsMore ? <p className="px-2 pt-1 text-[10px] font-bold text-slate-500">{t("representativesVehicles.representatives.searchHint")}</p> : null}
        </div>

        <div className="flex items-center rounded-2xl border border-slate-200/70 bg-slate-100/65 p-1" aria-label={t("representativesVehicles.representatives.filterLabel")}>
          {filters.map((filter) => {
            const selectedFilter = representatives.status === filter;
            return (
              <button key={filter} type="button" aria-pressed={selectedFilter} onClick={() => representatives.setStatus(filter)}
                className={`h-9 flex-1 rounded-xl px-3 text-xs font-black transition lg:flex-none ${selectedFilter ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200/70" : "text-slate-500 hover:text-slate-800"}`}>
                {t(`representativesVehicles.representatives.${filter}`)}
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            disabled={!canManage || access.isLoading}
            aria-describedby={!canManage && !access.isLoading ? "representative-manage-blocked" : undefined}
            className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-xl bg-amber-400 px-4 text-sm font-black text-slate-950 transition hover:bg-amber-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 disabled:cursor-not-allowed disabled:opacity-50 lg:flex-none"
          >
            <Plus className="h-4 w-4" />{t("representativesVehicles.representatives.add")}
          </button>
          <button type="button" onClick={() => void representatives.query.refetch()} disabled={representatives.query.isFetching}
            aria-label={t("common.refresh")} title={t("common.refresh")}
            className="inline-grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-slate-200 bg-white text-slate-600 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:opacity-50">
            <RefreshCw className={`h-4 w-4 ${representatives.query.isFetching ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {!access.isLoading && !canManage ? (
        <p id="representative-manage-blocked" className="shrink-0 border-x border-slate-200/80 bg-white px-4 pb-2 text-[11px] font-semibold text-slate-500">
          {t("representativesVehicles.representatives.permissions.manageRequired")}
        </p>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-b-xl border border-t-0 border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
        {representatives.query.isError && !hasLoadedRows ? (
          <div className="grid flex-1 place-items-center p-6 text-center" role="alert">
            <div className="max-w-md">
              <AlertTriangle className="mx-auto h-7 w-7 text-rose-500" />
              <p className="mt-3 text-sm font-bold text-rose-700">{representativeErrorMessage(representatives.query.error, t("representativesVehicles.representatives.loadFailed"))}</p>
              <button type="button" onClick={() => void representatives.query.refetch()} className="mt-3 rounded-xl bg-slate-900 px-4 py-2 text-sm font-black text-white">{t("common.retry")}</button>
            </div>
          </div>
        ) : !representatives.query.isFetching && representatives.items.length === 0 ? (
          <div className="grid flex-1 place-items-center p-6 text-center">
            <div className="max-w-sm">
              <div className="mx-auto grid h-16 w-16 place-items-center rounded-[22px] border border-white bg-gradient-to-br from-cyan-50 to-amber-50 shadow-sm"><UsersRound className="h-7 w-7 text-slate-600" /></div>
              <p className="mt-4 text-base font-black text-slate-900">{t("representativesVehicles.representatives.empty")}</p>
              <p className="mt-1.5 text-sm font-semibold leading-6 text-slate-500">{t("representativesVehicles.representatives.emptyHint")}</p>
            </div>
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-auto">
            <RepresentativeTable
              items={representatives.items}
              loading={representatives.query.isFetching && representatives.items.length === 0}
              canManage={canManage}
              canResetCredentials={canResetCredentials}
              onEdit={(representative) => {
                if (canManage) setAction({ type: "edit", representative });
              }}
              onLifecycle={(representative) => {
                if (canManage) setAction({ type: "lifecycle", representative });
              }}
              onResetCredentials={(representative) => {
                if (canResetCredentials) setAction({ type: "credentials", representative });
              }}
            />
            {representatives.query.hasNextPage || representatives.query.isFetchingNextPage || hasRetainedDataError ? (
              <div className="border-t border-slate-100 p-2 text-center">
                <div ref={infiniteScroll.sentinelRef} className="h-px w-full" aria-hidden="true" />
                {representatives.query.isFetchingNextPage ? (
                  <p role="status" className="py-2 text-xs font-bold text-slate-500">
                    {t("representativesVehicles.representatives.loadingMore")}
                  </p>
                ) : hasRetainedDataError ? (
                  <div role="alert" className="flex flex-col items-center justify-center gap-2 py-2 sm:flex-row">
                    <span className="text-xs font-bold text-rose-700">
                      {representativeErrorMessage(representatives.query.error, t("representativesVehicles.representatives.loadFailed"))}
                    </span>
                    <button
                      type="button"
                      onClick={retryRetainedData}
                      className="h-9 rounded-xl border border-slate-200 bg-white px-4 text-xs font-black text-slate-700 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
                    >
                      {t("common.retry")}
                    </button>
                  </div>
                ) : infiniteScroll.manualFallback && representatives.query.hasNextPage ? (
                  <button type="button" onClick={() => void representatives.query.fetchNextPage()} className="h-9 rounded-xl border border-slate-200 bg-white px-4 text-xs font-black text-slate-700 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">
                    {t("representativesVehicles.representatives.loadMore")}
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        )}
      </div>

      <Modal isOpen={createOpen} onClose={closeCreate} title={t("representativesVehicles.representatives.createTitle")} maxWidth="max-w-lg">
        <RepresentativeForm busy={creating} onCancel={closeCreate} onSubmit={(input, requestId) => create(input as CreateRepresentativeInput, requestId)} />
      </Modal>

      <Modal
        isOpen={action?.type === "edit"}
        onClose={closeEdit}
        title={t("representativesVehicles.representatives.edit")}
        maxWidth="max-w-lg"
      >
        {action?.type === "edit" ? (
          <RepresentativeForm
            representative={action.representative}
            busy={editing}
            onCancel={closeEdit}
            onSubmit={(input, requestId) => saveEdit(input as UpdateRepresentativeInput, requestId)}
          />
        ) : null}
      </Modal>

      {action?.type === "lifecycle" ? (
        <RepresentativeLifecycleActions
          representative={action.representative}
          allowed={canManage}
          open
          onOpenChange={(open) => {
            if (!open) setAction(null);
          }}
        />
      ) : null}

      {action?.type === "credentials" ? (
        <RepresentativeCredentialAction
          representative={action.representative}
          allowed={canResetCredentials}
          open
          onOpenChange={(open) => {
            if (!open) setAction(null);
          }}
        />
      ) : null}
    </section>
  );
}
