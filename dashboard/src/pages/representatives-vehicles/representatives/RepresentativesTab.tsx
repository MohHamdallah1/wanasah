import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Plus, RefreshCw, Search, UsersRound, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import { createRepresentative } from "./api";
import type { CreateRepresentativeInput, Representative, RepresentativeStatusFilter } from "./contracts";
import { RepresentativeDrawer } from "./RepresentativeDrawer";
import { RepresentativeForm } from "./RepresentativeForm";
import { RepresentativeTable } from "./RepresentativeTable";
import { useRepresentativeInfiniteScroll } from "./useRepresentativeInfiniteScroll";
import { useRepresentatives } from "./useRepresentatives";

const filters: RepresentativeStatusFilter[] = ["all", "active", "inactive"];

export function RepresentativesTab() {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const queryClient = useQueryClient();
  const representatives = useRepresentatives();
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<Representative | null>(null);

  const canManage = Boolean(
    access.isCompanyOwner || access.can("representative.manage"),
  );
  const canResetCredentials = Boolean(
    access.isCompanyOwner || access.can("representative.credentials.reset"),
  );

  const infiniteScroll = useRepresentativeInfiniteScroll({
    hasMore: Boolean(representatives.query.hasNextPage),
    isFetchingNextPage: representatives.query.isFetchingNextPage,
    onLoadMore: representatives.query.fetchNextPage,
  });

  const closeCreate = () => {
    if (creating) return;
    setCreateOpen(false);
  };

  const create = async (input: CreateRepresentativeInput, requestId: string) => {
    setCreating(true);
    try {
      await createRepresentative(authFetch, input, requestId);
      await queryClient.invalidateQueries({ queryKey: ["representatives"] });
      toast.success(t("representativesVehicles.representatives.createSuccess"));
      setCreateOpen(false);
    } catch (error) {
      toast.error(apiErrorMessage(error, t("representativesVehicles.representatives.saveFailed")));
    } finally {
      setCreating(false);
    }
  };

  const searchNeedsMore = representatives.input.trim().length === 1;

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-3" aria-labelledby="representatives-tab-heading">
      <h2 id="representatives-tab-heading" className="sr-only">{t("representativesVehicles.tabs.representatives")}</h2>

      <div className="flex flex-col gap-2.5 rounded-[24px] border border-white/80 bg-white/65 p-2.5 shadow-[0_20px_60px_-44px_rgba(15,23,42,0.6)] backdrop-blur-xl lg:flex-row lg:items-center">
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
        <p id="representative-manage-blocked" className="px-2 text-[11px] font-semibold text-slate-500">
          {t("representativesVehicles.representatives.permissions.manageRequired")}
        </p>
      ) : null}

      <div className="flex min-h-[320px] flex-1 flex-col overflow-hidden rounded-[26px] border border-white/85 bg-white/70 shadow-[0_22px_65px_-46px_rgba(15,23,42,0.65)] backdrop-blur-2xl">
        {representatives.query.isError ? (
          <div className="grid flex-1 place-items-center p-6 text-center" role="alert">
            <div className="max-w-md">
              <AlertTriangle className="mx-auto h-7 w-7 text-rose-500" />
              <p className="mt-3 text-sm font-bold text-rose-700">{apiErrorMessage(representatives.query.error, t("representativesVehicles.representatives.loadFailed"))}</p>
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
            <RepresentativeTable items={representatives.items} loading={representatives.query.isFetching && representatives.items.length === 0} onOpen={setSelected} />
            {representatives.query.hasNextPage || representatives.query.isFetchingNextPage ? (
              <div className="border-t border-slate-100 p-2 text-center">
                <div ref={infiniteScroll.sentinelRef} className="h-px w-full" aria-hidden="true" />
                {representatives.query.isFetchingNextPage ? (
                  <p role="status" className="py-2 text-xs font-bold text-slate-500">
                    {t("representativesVehicles.representatives.loadingMore")}
                  </p>
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

      <RepresentativeDrawer
        representative={selected}
        open={Boolean(selected)}
        canManage={canManage}
        canResetCredentials={canResetCredentials}
        onOpenChange={(open) => { if (!open) setSelected(null); }}
      />
    </section>
  );
}
