import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CarFront, Plus, RefreshCw, Search, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { createVehicle, updateVehicle } from "./api";
import type {
  CreateVehicleInput,
  UpdateVehicleInput,
  Vehicle,
  VehicleListResult,
  VehicleStatusFilter,
} from "./contracts";
import { VehicleDetailsModal } from "./VehicleDetailsModal";
import { VehicleForm } from "./VehicleForm";
import { VehicleLifecycleActions } from "./VehicleLifecycleActions";
import { VehicleTable } from "./VehicleTable";
import { VehicleQuickUpdateModal, type VehicleQuickActionKind } from "./VehicleQuickUpdateModal";
import type { VehicleNote } from "./vehiclePresentation";
import { replaceVehicleInInfiniteData } from "./vehicleCache";
import { vehicleErrorMessage } from "./vehicleErrorMessage";
import { useVehicleInfiniteScroll } from "./useVehicleInfiniteScroll";
import { useVehicles } from "./useVehicles";

const filters: VehicleStatusFilter[] = ["all", "ready", "maintenance", "inactive"];
type VehicleAction =
  | { type: "view" | "edit" | "lifecycle"; vehicle: Vehicle }
  | { type: "quick"; vehicle: Vehicle; kind: VehicleQuickActionKind };

export function VehiclesTab() {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const queryClient = useQueryClient();
  const vehicles = useVehicles();
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [action, setAction] = useState<VehicleAction | null>(null);
  const [editing, setEditing] = useState(false);

  const canManage = Boolean(access.isCompanyOwner || access.can("vehicle.manage"));
  const hasLoadedRows = vehicles.items.length > 0;
  const hasCursorPageError = Boolean(vehicles.query.isFetchNextPageError);
  const hasRetainedDataError = vehicles.query.isError && hasLoadedRows;
  const searchNeedsMore = vehicles.input.trim().length === 1;

  const infiniteScroll = useVehicleInfiniteScroll({
    hasMore: Boolean(vehicles.query.hasNextPage) && !hasCursorPageError,
    isFetchingNextPage: vehicles.query.isFetchingNextPage,
    onLoadMore: vehicles.query.fetchNextPage,
  });

  const replaceVehicleInCachedLists = (updated: Vehicle) => {
    queryClient.setQueriesData(
      { queryKey: ["vehicles"] },
      (cached: import("@tanstack/react-query").InfiniteData<VehicleListResult> | undefined) =>
        replaceVehicleInInfiniteData(cached, updated),
    );
  };

  const create = async (input: CreateVehicleInput, requestId: string) => {
    setCreating(true);
    try {
      await createVehicle(authFetch, input, requestId);
      await queryClient.invalidateQueries({ queryKey: ["vehicles"] });
      toast.success(t("representativesVehicles.vehicles.createSuccess"));
      setCreateOpen(false);
    } catch (error) {
      toast.error(vehicleErrorMessage(error, t("representativesVehicles.vehicles.saveFailed")));
    } finally {
      setCreating(false);
    }
  };

  const saveEdit = async (input: UpdateVehicleInput, requestId: string) => {
    const target = action?.type === "edit" ? action.vehicle : null;
    if (!target) return;
    setEditing(true);
    try {
      const updated = await updateVehicle(
        authFetch,
        target.id,
        input,
        requestId,
        target.version,
      );
      replaceVehicleInCachedLists(updated);
      // PATCH already returns the authoritative updated row. Mark list queries stale
      // without an immediate refetch so an older in-flight page cannot overwrite it.
      await queryClient.invalidateQueries({ queryKey: ["vehicles"], refetchType: "none" });
      toast.success(t("representativesVehicles.vehicles.updateSuccess"));
      setAction(null);
    } catch (error) {
      toast.error(vehicleErrorMessage(error, t("representativesVehicles.vehicles.saveFailed")));
    } finally {
      setEditing(false);
    }
  };

  const saveQuick = async (input: UpdateVehicleInput, requestId: string) => {
    const target = action?.type === "quick" ? action.vehicle : null;
    if (!target) return;
    setEditing(true);
    try {
      const updated = await updateVehicle(
        authFetch,
        target.id,
        input,
        requestId,
        target.version,
      );
      replaceVehicleInCachedLists(updated);
      // PATCH already returns the authoritative updated row. Mark list queries stale
      // without an immediate refetch so an older in-flight page cannot overwrite it.
      await queryClient.invalidateQueries({ queryKey: ["vehicles"], refetchType: "none" });
      toast.success(t("representativesVehicles.vehicles.quickActions.success"));
      setAction(null);
    } catch (error) {
      toast.error(vehicleErrorMessage(error, t("representativesVehicles.vehicles.saveFailed")));
    } finally {
      setEditing(false);
    }
  };

  const openNoteAction = (vehicle: Vehicle, note: VehicleNote) => {
    if (note.kind === "custody") {
      setAction({ type: "view", vehicle });
      return;
    }
    if (!canManage) return;
    setAction({ type: "quick", vehicle, kind: note.kind });
  };

  const retryRetainedData = () => {
    if (hasCursorPageError && vehicles.query.hasNextPage) {
      void vehicles.query.fetchNextPage();
      return;
    }
    void vehicles.query.refetch();
  };

  return (
    <section className="flex h-full min-h-0 flex-1 flex-col gap-0 overflow-hidden" aria-labelledby="vehicles-tab-heading">
      <h2 id="vehicles-tab-heading" className="sr-only">{t("representativesVehicles.tabs.vehicles")}</h2>

      <div className="flex shrink-0 flex-col gap-2.5 rounded-t-xl border border-b-0 border-slate-200/80 bg-white px-3 py-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)] sm:px-4 lg:flex-row lg:items-center">
        <div className="min-w-0 flex-1">
          <div className="relative">
            <Search className="pointer-events-none absolute start-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="search"
              value={vehicles.input}
              onChange={(event) => vehicles.setInput(event.target.value.slice(0, 100))}
              placeholder={t("representativesVehicles.vehicles.search")}
              aria-label={t("representativesVehicles.vehicles.search")}
              maxLength={100}
              className="h-11 w-full rounded-2xl border border-slate-200/80 bg-white pe-10 ps-10 text-sm font-semibold text-slate-800 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-cyan-300 focus:ring-4 focus:ring-cyan-100/60"
            />
            {vehicles.input ? (
              <button type="button" onClick={() => vehicles.setInput("")} aria-label={t("representativesVehicles.vehicles.clearSearch")}
                className="absolute end-2.5 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-full text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">
                <X className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>
          {searchNeedsMore ? <p className="px-2 pt-1 text-[10px] font-bold text-slate-500">{t("representativesVehicles.vehicles.searchHint")}</p> : null}
        </div>

        <div className="flex items-center rounded-2xl border border-slate-200/70 bg-slate-100/65 p-1" aria-label={t("representativesVehicles.vehicles.filterLabel")}>
          {filters.map((filter) => {
            const selected = vehicles.status === filter;
            return (
              <button key={filter} type="button" aria-pressed={selected} onClick={() => vehicles.setStatus(filter)}
                className={`h-9 flex-1 rounded-xl px-3 text-xs font-black transition lg:flex-none ${selected ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200/70" : "text-slate-500 hover:text-slate-800"}`}>
                {t(`representativesVehicles.vehicles.filters.${filter}`)}
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            disabled={!canManage || access.isLoading}
            aria-describedby={!canManage && !access.isLoading ? "vehicle-manage-blocked" : undefined}
            className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-xl bg-amber-400 px-4 text-sm font-black text-slate-950 transition hover:bg-amber-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 disabled:cursor-not-allowed disabled:opacity-50 lg:flex-none"
          >
            <Plus className="h-4 w-4" />{t("representativesVehicles.vehicles.add")}
          </button>
          <button type="button" onClick={() => void vehicles.query.refetch()} disabled={vehicles.query.isFetching}
            aria-label={t("common.refresh")} title={t("common.refresh")}
            className="inline-grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-slate-200 bg-white text-slate-600 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:opacity-50">
            <RefreshCw className={`h-4 w-4 ${vehicles.query.isFetching ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {!access.isLoading && !canManage ? (
        <p id="vehicle-manage-blocked" className="shrink-0 border-x border-slate-200/80 bg-white px-4 pb-2 text-[11px] font-semibold text-slate-500">
          {t("representativesVehicles.vehicles.permissions.manageRequired")}
        </p>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-b-xl border border-t-0 border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
        {vehicles.query.isError && !hasLoadedRows ? (
          <div className="grid flex-1 place-items-center p-6 text-center" role="alert">
            <div className="max-w-md">
              <AlertTriangle className="mx-auto h-7 w-7 text-rose-500" />
              <p className="mt-3 text-sm font-bold text-rose-700">{vehicleErrorMessage(vehicles.query.error, t("representativesVehicles.vehicles.loadFailed"))}</p>
              <button type="button" onClick={() => void vehicles.query.refetch()} className="mt-3 rounded-xl bg-slate-900 px-4 py-2 text-sm font-black text-white">{t("common.retry")}</button>
            </div>
          </div>
        ) : !vehicles.query.isFetching && vehicles.items.length === 0 ? (
          <div className="grid flex-1 place-items-center p-6 text-center">
            <div className="max-w-sm">
              <div className="mx-auto grid h-16 w-16 place-items-center rounded-[22px] border border-white bg-gradient-to-br from-cyan-50 to-amber-50 shadow-sm"><CarFront className="h-7 w-7 text-slate-600" /></div>
              <p className="mt-4 text-base font-black text-slate-900">{t("representativesVehicles.vehicles.empty")}</p>
              <p className="mt-1.5 text-sm font-semibold leading-6 text-slate-500">{t("representativesVehicles.vehicles.emptyHint")}</p>
            </div>
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-auto">
            <VehicleTable
              items={vehicles.items}
              loading={vehicles.query.isFetching && vehicles.items.length === 0}
              canManage={canManage}
              onView={(vehicle) => setAction({ type: "view", vehicle })}
              onEdit={(vehicle) => { if (canManage) setAction({ type: "edit", vehicle }); }}
              onLifecycle={(vehicle) => { if (canManage) setAction({ type: "lifecycle", vehicle }); }}
              onNoteAction={openNoteAction}
            />
            {vehicles.query.hasNextPage || vehicles.query.isFetchingNextPage || hasRetainedDataError ? (
              <div className="border-t border-slate-100 p-2 text-center">
                <div ref={infiniteScroll.sentinelRef} className="h-px w-full" aria-hidden="true" />
                {vehicles.query.isFetchingNextPage ? (
                  <p role="status" className="py-2 text-xs font-bold text-slate-500">{t("representativesVehicles.vehicles.loadingMore")}</p>
                ) : hasRetainedDataError ? (
                  <div role="alert" className="flex flex-col items-center justify-center gap-2 py-2 sm:flex-row">
                    <span className="text-xs font-bold text-rose-700">{vehicleErrorMessage(vehicles.query.error, t("representativesVehicles.vehicles.loadFailed"))}</span>
                    <button type="button" onClick={retryRetainedData} className="h-9 rounded-xl border border-slate-200 bg-white px-4 text-xs font-black text-slate-700">{t("common.retry")}</button>
                  </div>
                ) : infiniteScroll.manualFallback && vehicles.query.hasNextPage ? (
                  <button type="button" onClick={() => void vehicles.query.fetchNextPage()} className="h-9 rounded-xl border border-slate-200 bg-white px-4 text-xs font-black text-slate-700">{t("representativesVehicles.vehicles.loadMore")}</button>
                ) : null}
              </div>
            ) : null}
          </div>
        )}
      </div>

      <Modal isOpen={createOpen} onClose={() => { if (!creating) setCreateOpen(false); }} title={t("representativesVehicles.vehicles.createTitle")} maxWidth="max-w-xl">
        <VehicleForm
          busy={creating}
          onCancel={() => { if (!creating) setCreateOpen(false); }}
          onSubmit={(input, requestId) => create(input as CreateVehicleInput, requestId)}
        />
      </Modal>

      {action?.type === "view" ? (
        <VehicleDetailsModal
          vehicle={action.vehicle}
          open
          onOpenChange={(open) => { if (!open) setAction(null); }}
        />
      ) : null}

      <Modal isOpen={action?.type === "edit"} onClose={() => { if (!editing) setAction(null); }} title={t("representativesVehicles.vehicles.edit")} maxWidth="max-w-xl">
        {action?.type === "edit" ? (
          <VehicleForm
            vehicle={action.vehicle}
            busy={editing}
            onCancel={() => { if (!editing) setAction(null); }}
            onSubmit={(input, requestId) => saveEdit(input as UpdateVehicleInput, requestId)}
          />
        ) : null}
      </Modal>

      {action?.type === "quick" ? (
        <VehicleQuickUpdateModal
          vehicle={action.vehicle}
          kind={action.kind}
          open
          busy={editing}
          onClose={() => { if (!editing) setAction(null); }}
          onSubmit={saveQuick}
        />
      ) : null}

      {action?.type === "lifecycle" ? (
        <VehicleLifecycleActions
          vehicle={action.vehicle}
          allowed={canManage}
          open
          onOpenChange={(open) => { if (!open) setAction(null); }}
        />
      ) : null}
    </section>
  );
}
