import { useCallback, useDeferredValue, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowLeft, Package, RefreshCw, Search } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { createDispatchOwnerFocusState } from "@/features/dispatch/navigation";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { compareQuantity, validateVariantQuantity } from "@/lib/quantity";

import type { Vehicle } from "../contracts";
import { vehicleErrorMessage } from "../vehicleErrorMessage";
import {
  getVehicleLoadSnapshot,
  getVehicleLoadSourceInventory,
  getVehicleLoadWarehouses,
} from "./api";
import type {
  VehicleLoadDirection,
  VehicleLoadItem,
  VehicleLoadMutationItem,
  VehicleLoadSnapshot,
  VehicleLoadSourceItem,
  VehicleLoadStockStatus,
  VehicleLoadWarehouse,
} from "./contracts";
import { useVehicleLoadCommand } from "./useVehicleLoadCommand";

interface VehicleLoadModalProps {
  vehicle: Vehicle;
  open: boolean;
  onClose: () => void;
}

const itemKey = (productVariantId: number, stockStatus?: string) =>
  String(productVariantId) + ":" + (stockStatus || "AVAILABLE");

const candidateStockStatus = (
  item: VehicleLoadSourceItem | VehicleLoadItem,
): VehicleLoadStockStatus | undefined =>
  "stock_status" in item
    ? (item.stock_status as VehicleLoadStockStatus)
    : undefined;

export function VehicleLoadModal({ vehicle, open, onClose }: VehicleLoadModalProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const authFetch = useAuthFetch();

  const [snapshot, setSnapshot] = useState<VehicleLoadSnapshot | null>(null);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [snapshotError, setSnapshotError] = useState<unknown>(null);
  const [direction, setDirection] = useState<VehicleLoadDirection | null>(null);

  const [warehouseSearch, setWarehouseSearch] = useState("");
  const deferredWarehouseSearch = useDeferredValue(warehouseSearch);
  const [warehouses, setWarehouses] = useState<VehicleLoadWarehouse[]>([]);
  const [warehousesLoading, setWarehousesLoading] = useState(false);
  const [warehouseId, setWarehouseId] = useState<number | null>(null);

  const [productSearch, setProductSearch] = useState("");
  const deferredProductSearch = useDeferredValue(productSearch);
  const [sourceItems, setSourceItems] = useState<VehicleLoadSourceItem[]>([]);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceNextCursor, setSourceNextCursor] = useState<string | null>(null);
  const [sourceHasMore, setSourceHasMore] = useState(false);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [selectedUnloadKeys, setSelectedUnloadKeys] = useState<Set<string>>(
    () => new Set(),
  );

  const addCommand = useVehicleLoadCommand(vehicle.id, "ADD");
  const unloadCommand = useVehicleLoadCommand(vehicle.id, "UNLOAD");
  const pendingCommand = addCommand.pending
    ? addCommand
    : unloadCommand.pending
      ? unloadCommand
      : null;
  const recoveryError = addCommand.recoveryError ?? unloadCommand.recoveryError;

  const reloadSnapshot = useCallback(async () => {
    setSnapshotLoading(true);
    setSnapshotError(null);
    try {
      setSnapshot(await getVehicleLoadSnapshot(authFetch, vehicle.id));
    } catch (error) {
      setSnapshotError(error);
    } finally {
      setSnapshotLoading(false);
    }
  }, [authFetch, vehicle.id]);

  useEffect(() => {
    if (!open) return;
    setDirection(null);
    setWarehouseSearch("");
    setWarehouses([]);
    setWarehouseId(null);
    setProductSearch("");
    setSourceItems([]);
    setSourceNextCursor(null);
    setSourceHasMore(false);
    setQuantities({});
    setSelectedUnloadKeys(new Set());
    void reloadSnapshot();
  }, [open, reloadSnapshot]);

  useEffect(() => {
    if (!open || !direction || snapshot?.mode !== "DIRECT") return;
    const search = deferredWarehouseSearch.trim();
    if (search.length === 1) {
      setWarehouses([]);
      setWarehouseId(null);
      return;
    }

    const controller = new AbortController();
    setWarehousesLoading(true);
    void getVehicleLoadWarehouses(authFetch, vehicle.id, direction, {
      search,
      limit: 100,
      signal: controller.signal,
    })
      .then((page) => {
        setWarehouses(page.items);
        setWarehouseId((current) => {
          if (current && page.items.some((item) => item.id === current)) return current;
          return page.items.length === 1 ? page.items[0].id : null;
        });
      })
      .catch((error: unknown) => {
        if (!(error instanceof Error && error.name === "AbortError")) {
          toast.error(
            vehicleErrorMessage(
              error,
              t("representativesVehicles.vehicles.load.loadFailed"),
            ),
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setWarehousesLoading(false);
      });

    return () => controller.abort();
  }, [
    authFetch,
    deferredWarehouseSearch,
    direction,
    open,
    snapshot?.mode,
    t,
    vehicle.id,
  ]);

  const loadSourcePage = useCallback(
    async (cursor?: string | null) => {
      if (!warehouseId || direction !== "ADD") return;
      const search = deferredProductSearch.trim();
      if (search.length === 1) {
        setSourceItems([]);
        setSourceNextCursor(null);
        setSourceHasMore(false);
        return;
      }

      setSourceLoading(true);
      try {
        const page = await getVehicleLoadSourceInventory(
          authFetch,
          vehicle.id,
          warehouseId,
          { search, cursor, limit: 50 },
        );
        setSourceItems((current) =>
          cursor
            ? current.concat(
                page.items.filter(
                  (candidate) =>
                    !current.some(
                      (existing) =>
                        existing.product_variant_id === candidate.product_variant_id,
                    ),
                ),
              )
            : page.items,
        );
        setSourceNextCursor(page.next_cursor);
        setSourceHasMore(page.has_more);
      } catch (error) {
        toast.error(
          vehicleErrorMessage(
            error,
            t("representativesVehicles.vehicles.load.loadFailed"),
          ),
        );
      } finally {
        setSourceLoading(false);
      }
    },
    [authFetch, deferredProductSearch, direction, t, vehicle.id, warehouseId],
  );

  useEffect(() => {
    setQuantities({});
    if (!open || direction !== "ADD" || !warehouseId) {
      setSourceItems([]);
      setSourceNextCursor(null);
      setSourceHasMore(false);
      return;
    }
    void loadSourcePage(null);
  }, [deferredProductSearch, direction, loadSourcePage, open, warehouseId]);

  const unloadItems = useMemo(
    () =>
      (snapshot?.items || []).filter(
        (item) => compareQuantity(item.available_quantity, "0") > 0,
      ),
    [snapshot?.items],
  );

  const candidates = direction === "ADD" ? sourceItems : unloadItems;

  const buildMutationItems = (
    source: Array<VehicleLoadSourceItem | VehicleLoadItem>,
    useFullAvailable: boolean,
  ): VehicleLoadMutationItem[] | null => {
    const items: VehicleLoadMutationItem[] = [];
    for (const item of source) {
      const status = candidateStockStatus(item);
      const key = itemKey(item.product_variant_id, status);
      const raw = useFullAvailable
        ? item.available_quantity
        : (quantities[key] || "").trim();
      if (!raw) continue;
      try {
        const quantity = validateVariantQuantity(
          raw,
          item.quantity_scale,
          item.quantity_step,
          "quantity",
        );
        if (compareQuantity(quantity, item.available_quantity) > 0) {
          throw new Error("over available");
        }
        items.push({
          product_variant_id: item.product_variant_id,
          quantity,
          ...(direction === "UNLOAD" ? { stock_status: status } : {}),
        });
      } catch {
        toast.error(t("representativesVehicles.vehicles.load.invalidQuantity"));
        return null;
      }
    }
    return items;
  };

  const executeMutation = async (items: VehicleLoadMutationItem[]) => {
    if (!direction || !warehouseId || !snapshot) return;
    if (!items.length) {
      toast.error(t("representativesVehicles.vehicles.load.noItemsSelected"));
      return;
    }
    try {
      const command = direction === "ADD" ? addCommand : unloadCommand;
      const result = await command.execute({ warehouse_id: warehouseId, items });
      if (!result) return;
      toast.success(
        t(
          direction === "ADD"
            ? "representativesVehicles.vehicles.load.successAdd"
            : "representativesVehicles.vehicles.load.successUnload",
        ),
      );
      setDirection(null);
      setWarehouseId(null);
      setQuantities({});
      setSelectedUnloadKeys(new Set());
      await reloadSnapshot();
    } catch (error) {
      toast.error(
        vehicleErrorMessage(
          error,
          t("representativesVehicles.vehicles.load.loadFailed"),
        ),
      );
    }
  };

  const submit = async () => {
    const items = buildMutationItems(candidates, false);
    if (items === null) return;
    await executeMutation(items);
  };

  const submitFullUnload = async (selectedOnly: boolean) => {
    if (direction !== "UNLOAD") return;
    const source = selectedOnly
      ? unloadItems.filter((item) =>
          selectedUnloadKeys.has(
            itemKey(item.product_variant_id, item.stock_status),
          ),
        )
      : unloadItems;
    const items = buildMutationItems(source, true);
    if (items === null) return;
    await executeMutation(items);
  };

  const retryPending = async () => {
    if (!pendingCommand) return;
    try {
      const result = await pendingCommand.retryPending();
      if (!result) return;
      toast.success(result.message);
      await reloadSnapshot();
    } catch (error) {
      toast.error(
        vehicleErrorMessage(
          error,
          t("representativesVehicles.vehicles.load.loadFailed"),
        ),
      );
    }
  };

  const openRouteLoad = () => {
    if (!snapshot?.route_id) return;
    const routeId = snapshot.route_id;
    onClose();
    navigate("/dispatch", {
      state: createDispatchOwnerFocusState({
        version: 1,
        kind: "route-load",
        routeId,
      }),
    });
  };

  const operationBusy = addCommand.busy || unloadCommand.busy;

  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title={t("representativesVehicles.vehicles.load.title")}
      subtitle={t("representativesVehicles.vehicles.load.subtitle", {
        plate: vehicle.plate_number,
      })}
      maxWidth="max-w-4xl"
      bodyClassName="p-3 sm:p-5"
    >
      <div className="space-y-4">
        {recoveryError ? (
          <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-800">
            {t("representativesVehicles.vehicles.load.recoveryFailed")}
          </div>
        ) : null}

        {pendingCommand ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-3">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-black text-amber-900">
                  {t("representativesVehicles.vehicles.load.pendingTitle")}
                </p>
                <p className="mt-1 text-xs font-semibold leading-5 text-amber-800">
                  {t("representativesVehicles.vehicles.load.pendingHint")}
                </p>
              </div>
              <button
                type="button"
                disabled={pendingCommand.busy}
                onClick={() => void retryPending()}
                className="shrink-0 rounded-lg bg-amber-900 px-3 py-2 text-xs font-black text-white disabled:opacity-50"
              >
                {t("representativesVehicles.vehicles.load.retryPending")}
              </button>
            </div>
          </div>
        ) : null}

        {snapshotLoading && !snapshot ? (
          <div role="status" className="flex min-h-40 items-center justify-center text-sm font-bold text-slate-500">
            <RefreshCw className="me-2 h-4 w-4 animate-spin" />
            {t("representativesVehicles.vehicles.load.loading")}
          </div>
        ) : snapshotError && !snapshot ? (
          <div role="alert" className="grid min-h-40 place-items-center text-center">
            <div>
              <AlertTriangle className="mx-auto h-6 w-6 text-rose-500" />
              <p className="mt-2 text-sm font-bold text-rose-700">
                {vehicleErrorMessage(
                  snapshotError,
                  t("representativesVehicles.vehicles.load.loadFailed"),
                )}
              </p>
              <button
                type="button"
                onClick={() => void reloadSnapshot()}
                className="mt-3 rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-black text-slate-700"
              >
                {t("common.retry")}
              </button>
            </div>
          </div>
        ) : snapshot ? (
          <>
            <div
              className={
                "rounded-xl border p-3 " +
                (snapshot.mode === "DIRECT"
                  ? "border-emerald-200 bg-emerald-50"
                  : snapshot.mode === "ROUTE"
                    ? "border-cyan-200 bg-cyan-50"
                    : "border-amber-200 bg-amber-50")
              }
            >
              <p className="text-xs font-bold leading-5 text-slate-700">
                {t(
                  snapshot.mode === "DIRECT"
                    ? "representativesVehicles.vehicles.load.directHint"
                    : snapshot.mode === "ROUTE"
                      ? "representativesVehicles.vehicles.load.routeHint"
                      : "representativesVehicles.vehicles.load.settlementHint",
                )}
              </p>
              {snapshot.mode === "ROUTE" && snapshot.route_id ? (
                <button
                  type="button"
                  onClick={openRouteLoad}
                  className="mt-2 rounded-lg bg-cyan-700 px-3 py-2 text-xs font-black text-white hover:bg-cyan-600"
                >
                  {t("representativesVehicles.vehicles.load.goToRoute")}
                </button>
              ) : null}
            </div>

            <div className="overflow-hidden rounded-xl border border-slate-200">
              <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-3 py-2">
                <div className="flex items-center gap-2 text-sm font-black text-slate-800">
                  <Package className="h-4 w-4 text-slate-500" />
                  {t("representativesVehicles.vehicles.load.title")}
                </div>
                <button
                  type="button"
                  onClick={() => void reloadSnapshot()}
                  disabled={snapshotLoading}
                  className="rounded-lg p-2 text-slate-500 hover:bg-white disabled:opacity-50"
                  aria-label={t("common.refresh")}
                >
                  <RefreshCw
                    className={"h-4 w-4 " + (snapshotLoading ? "animate-spin" : "")}
                  />
                </button>
              </div>

              {snapshot.items.length === 0 ? (
                <p className="px-4 py-8 text-center text-sm font-semibold text-slate-500">
                  {t("representativesVehicles.vehicles.load.empty")}
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[680px] text-sm">
                    <thead className="bg-white text-[11px] font-black text-slate-500">
                      <tr>
                        <th className="px-3 py-2 text-start">{t("representativesVehicles.vehicles.load.product")}</th>
                        <th className="px-3 py-2 text-start">{t("representativesVehicles.vehicles.load.stockStatus")}</th>
                        <th className="px-3 py-2 text-end">{t("representativesVehicles.vehicles.load.onHand")}</th>
                        <th className="px-3 py-2 text-end">{t("representativesVehicles.vehicles.load.reserved")}</th>
                        <th className="px-3 py-2 text-end">{t("representativesVehicles.vehicles.load.available")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {snapshot.items.map((item) => (
                        <tr
                          key={itemKey(item.product_variant_id, item.stock_status)}
                          className="border-t border-slate-100"
                        >
                          <td className="px-3 py-2.5">
                            <p className="font-black text-slate-800">{item.product_name}</p>
                            {item.sku ? (
                              <p className="text-[10px] font-semibold text-slate-400">{item.sku}</p>
                            ) : null}
                          </td>
                          <td className="px-3 py-2.5 text-xs font-bold text-slate-600">
                            {t("representativesVehicles.vehicles.load.statuses." + item.stock_status)}
                          </td>
                          <td className="px-3 py-2.5 text-end font-mono font-bold tabular-nums text-slate-700">
                            {item.on_hand_quantity} {item.base_uom_name}
                          </td>
                          <td className="px-3 py-2.5 text-end font-mono font-bold tabular-nums text-slate-500">
                            {item.reserved_quantity} {item.base_uom_name}
                          </td>
                          <td className="px-3 py-2.5 text-end font-mono font-black tabular-nums text-slate-900">
                            {item.available_quantity} {item.base_uom_name}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {snapshot.mode === "DIRECT" && !pendingCommand ? (
              direction === null ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  <button
                    type="button"
                    disabled={!snapshot.can_add}
                    onClick={() => {
                      setDirection("ADD");
                      setWarehouseId(null);
                      setQuantities({});
                      setSelectedUnloadKeys(new Set());
                    }}
                    className="rounded-xl bg-emerald-600 px-4 py-3 text-sm font-black text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {t("representativesVehicles.vehicles.load.add")}
                  </button>
                  <button
                    type="button"
                    disabled={!snapshot.can_unload}
                    onClick={() => {
                      setDirection("UNLOAD");
                      setWarehouseId(null);
                      setQuantities({});
                      setSelectedUnloadKeys(new Set());
                    }}
                    className="rounded-xl bg-slate-900 px-4 py-3 text-sm font-black text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {t("representativesVehicles.vehicles.load.unload")}
                  </button>
                  {!snapshot.can_add && !snapshot.can_unload ? (
                    <p className="sm:col-span-2 text-center text-xs font-bold text-slate-500">
                      {t(
                        snapshot.vehicle_operational
                          ? "representativesVehicles.vehicles.load.permissionDenied"
                          : "representativesVehicles.vehicles.load.notOperational",
                      )}
                    </p>
                  ) : null}
                </div>
              ) : (
                <div className="rounded-xl border border-slate-200 p-3 sm:p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <button
                      type="button"
                      onClick={() => {
                        setDirection(null);
                        setWarehouseId(null);
                        setQuantities({});
                        setSelectedUnloadKeys(new Set());
                      }}
                      className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs font-black text-slate-600 hover:bg-slate-100"
                    >
                      <ArrowLeft className="h-4 w-4 rtl:rotate-180" />
                      {t("representativesVehicles.vehicles.load.back")}
                    </button>
                    <p className="text-sm font-black text-slate-900">
                      {t(
                        direction === "ADD"
                          ? "representativesVehicles.vehicles.load.add"
                          : "representativesVehicles.vehicles.load.unload",
                      )}
                    </p>
                  </div>

                  <div className="grid gap-3 lg:grid-cols-[minmax(220px,0.7fr)_minmax(0,1.3fr)]">
                    <div className="space-y-2">
                      <label className="block text-xs font-black text-slate-700">
                        {t("representativesVehicles.vehicles.load.warehouse")}
                      </label>
                      <div className="relative">
                        <Search className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                        <input
                          type="search"
                          value={warehouseSearch}
                          onChange={(event) => setWarehouseSearch(event.target.value.slice(0, 100))}
                          placeholder={t("representativesVehicles.vehicles.load.warehouseSearch")}
                          className="h-10 w-full rounded-xl border border-slate-200 pe-3 ps-9 text-sm font-semibold outline-none focus:border-cyan-300 focus:ring-2 focus:ring-cyan-100"
                        />
                      </div>
                      {warehouseSearch.trim().length === 1 ? (
                        <p className="text-[10px] font-bold text-slate-500">
                          {t("representativesVehicles.vehicles.load.searchHint")}
                        </p>
                      ) : null}
                      <select
                        value={warehouseId ?? ""}
                        onChange={(event) => {
                          setWarehouseId(event.target.value ? Number(event.target.value) : null);
                          setQuantities({});
                          setSelectedUnloadKeys(new Set());
                        }}
                        disabled={warehousesLoading}
                        className="h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold text-slate-800 outline-none focus:border-cyan-300"
                      >
                        <option value="">{t("representativesVehicles.vehicles.load.chooseWarehouse")}</option>
                        {warehouses.map((warehouse) => (
                          <option key={warehouse.id} value={warehouse.id}>
                            {warehouse.name} ({warehouse.code})
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="min-w-0">
                      {direction === "ADD" ? (
                        <>
                          <div className="relative mb-2">
                            <Search className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                            <input
                              type="search"
                              value={productSearch}
                              onChange={(event) => setProductSearch(event.target.value.slice(0, 100))}
                              placeholder={t("representativesVehicles.vehicles.load.productSearch")}
                              disabled={!warehouseId}
                              className="h-10 w-full rounded-xl border border-slate-200 pe-3 ps-9 text-sm font-semibold outline-none focus:border-cyan-300 focus:ring-2 focus:ring-cyan-100 disabled:bg-slate-50"
                            />
                          </div>
                          {productSearch.trim().length === 1 ? (
                            <p className="mb-2 text-[10px] font-bold text-slate-500">
                              {t("representativesVehicles.vehicles.load.searchHint")}
                            </p>
                          ) : null}
                        </>
                      ) : null}

                      {!warehouseId ? (
                        <div className="grid min-h-28 place-items-center rounded-xl bg-slate-50 text-center text-xs font-bold text-slate-500">
                          {t("representativesVehicles.vehicles.load.chooseWarehouse")}
                        </div>
                      ) : sourceLoading && direction === "ADD" && sourceItems.length === 0 ? (
                        <div className="grid min-h-28 place-items-center rounded-xl bg-slate-50 text-xs font-bold text-slate-500">
                          {t("representativesVehicles.vehicles.load.sourceLoading")}
                        </div>
                      ) : candidates.length === 0 ? (
                        <div className="grid min-h-28 place-items-center rounded-xl bg-slate-50 text-center text-xs font-bold text-slate-500">
                          {t("representativesVehicles.vehicles.load.sourceEmpty")}
                        </div>
                      ) : (
                        <>
                          {direction === "UNLOAD" ? (
                            <div className="mb-2 flex flex-wrap gap-2">
                              <button
                                type="button"
                                disabled={operationBusy || unloadItems.length === 0}
                                onClick={() => void submitFullUnload(false)}
                                className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-black text-white disabled:opacity-40"
                              >
                                {t("representativesVehicles.vehicles.load.unloadAll")}
                              </button>
                              <button
                                type="button"
                                disabled={operationBusy || selectedUnloadKeys.size === 0}
                                onClick={() => void submitFullUnload(true)}
                                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-black text-slate-700 disabled:opacity-40"
                              >
                                {t("representativesVehicles.vehicles.load.unloadSelected")}
                              </button>
                            </div>
                          ) : null}
                          <div className="max-h-72 overflow-auto rounded-xl border border-slate-200">
                          {candidates.map((item) => {
                            const status = candidateStockStatus(item);
                            const key = itemKey(item.product_variant_id, status);
                            return (
                              <div
                                key={key}
                                className={
                                  "grid items-center gap-3 border-b border-slate-100 p-3 last:border-b-0 " +
                                  (direction === "UNLOAD"
                                    ? "grid-cols-[28px_minmax(0,1fr)_110px]"
                                    : "grid-cols-[minmax(0,1fr)_110px]")
                                }
                              >
                                {direction === "UNLOAD" ? (
                                  <input
                                    type="checkbox"
                                    checked={selectedUnloadKeys.has(key)}
                                    onChange={(event) => {
                                      setSelectedUnloadKeys((current) => {
                                        const next = new Set(current);
                                        if (event.target.checked) next.add(key);
                                        else next.delete(key);
                                        return next;
                                      });
                                    }}
                                    aria-label={
                                      t("representativesVehicles.vehicles.load.selectForFullUnload") +
                                      " - " +
                                      item.product_name
                                    }
                                    className="h-4 w-4 accent-slate-900"
                                  />
                                ) : null}
                                <div className="min-w-0">
                                  <p className="truncate text-sm font-black text-slate-800">{item.product_name}</p>
                                  <p className="mt-0.5 text-[10px] font-semibold text-slate-500">
                                    {t("representativesVehicles.vehicles.load.available")}:{" "}
                                    {item.available_quantity} {item.base_uom_name}
                                    {status
                                      ? " / " + t("representativesVehicles.vehicles.load.statuses." + status)
                                      : ""}
                                  </p>
                                </div>
                                <input
                                  type="text"
                                  inputMode="decimal"
                                  value={quantities[key] ?? ""}
                                  onChange={(event) =>
                                    setQuantities((current) => ({
                                      ...current,
                                      [key]: event.target.value.slice(0, 24),
                                    }))
                                  }
                                  placeholder={t("representativesVehicles.vehicles.load.quantity")}
                                  aria-label={
                                    t("representativesVehicles.vehicles.load.quantity") +
                                    " - " +
                                    item.product_name
                                  }
                                  className="h-9 rounded-lg border border-slate-200 px-2 text-end font-mono text-sm font-bold tabular-nums outline-none focus:border-cyan-300"
                                />
                              </div>
                            );
                          })}
                          {direction === "ADD" && sourceHasMore ? (
                            <div className="p-2 text-center">
                              <button
                                type="button"
                                disabled={sourceLoading || !sourceNextCursor}
                                onClick={() => void loadSourcePage(sourceNextCursor)}
                                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700 disabled:opacity-50"
                              >
                                {t("representativesVehicles.vehicles.load.loadMore")}
                              </button>
                            </div>
                          ) : null}
                          </div>
                        </>
                      )}
                    </div>
                  </div>

                  <div className="mt-4 flex justify-end">
                    <button
                      type="button"
                      onClick={() => void submit()}
                      disabled={!warehouseId || operationBusy || candidates.length === 0}
                      className="rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-black text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {t(
                        direction === "ADD"
                          ? "representativesVehicles.vehicles.load.submitAdd"
                          : "representativesVehicles.vehicles.load.submitUnload",
                      )}
                    </button>
                  </div>
                </div>
              )
            ) : null}
          </>
        ) : null}
      </div>
    </Modal>
  );
}
