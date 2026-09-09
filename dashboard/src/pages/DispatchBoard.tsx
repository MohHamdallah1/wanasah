import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Truck, LayoutGrid, ClipboardList, Calendar, Search, Pencil, Trash2, Plus, RotateCcw, X, Upload, Eye, Eraser, Save, XCircle, Loader2, AlertCircle, Archive, Rocket } from "lucide-react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/modal";
// Components
import { CustomSelect } from "@/components/ui/custom-select";
import { QuantityInput } from "@/components/ui/quantity-input";
import { ShopTable } from "@/components/dispatch/ShopTable";
import { PendingRoutesTable } from "@/components/dispatch/PendingRoutesTable";
import { ShortageModal } from "@/components/dispatch/ShortageModal";
import { ScheduleModal } from "@/components/dispatch/ScheduleModal";
import { RouteManagementModal } from "@/components/dispatch/RouteManagementModal";
import { ShopFormModal } from "@/components/dispatch/ShopFormModal";
import { RecycleBinModal } from "@/components/dispatch/RecycleBinModal";
import { BulkTransferModal } from "@/components/dispatch/BulkTransferModal";
import { ZoneModal } from "@/components/dispatch/ZoneModal";
import { PostponedRoutesModal } from "@/components/dispatch/PostponedRoutesModal";
import { ZoneRecycleBinModal } from "@/components/dispatch/ZoneRecycleBinModal";
import { ShopBulkImportModal } from "@/components/dispatch/ShopBulkImportModal";
import { AdjustInventoryModal } from "@/components/dispatch/AdjustInventoryModal";
import { TransfersRadarModal } from "@/components/dispatch/TransfersRadarModal";
// Types
import { TabId, Zone, PendingRoute, Shortage, Shop } from "@/types/dispatch";
import { useAuthFetch } from "@/hooks/useAuthFetch";

interface WarehouseOption {
  id: string;
  label: string;
}

interface DispatchInitPayload {
  zones?: Zone[];
  drivers?: { id: string; name: string }[];
  vehicles?: { id: string; label: string }[];
  products?: { id: string; name: string }[];
}

interface WarehouseLocationPayload {
  id: number;
  name: string;
  code: string;
}

interface VehicleInventoryPayload {
  product_id: string;
  current_quantity: number;
}

interface ArchivedZonePayload {
  id: string;
  name: string;
}

interface WorkerRealtimeEvent {
  event?: string;
  message?: string;
}

interface DuplicateShopPayload {
  name: string;
  owner?: string | null;
  phone?: string | null;
  zone_name?: string | null;
}

interface ShopMutationPayload {
  name: string;
  owner: string;
  phone: string;
  initialDebt: number;
  maxDebtLimit: number;
  mapLink: string;
  zoneId: number;
  force_save?: boolean;
}

interface LocalShopState {
  name: string;
  owner: string;
  phone: string;
  initialDebt: number;
  maxDebtLimit: number;
  mapLink: string;
  zoneId: string;
}

interface DuplicateWarningState {
  show: boolean;
  shopData: DuplicateShopPayload;
  apiPayload: ShopMutationPayload;
  localState: LocalShopState;
}

type ShopWire = Omit<Shop, "initialDebt" | "maxDebtLimit"> & {
  initialDebt: number | string;
  maxDebtLimit: number | string;
};

const getErrorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : "حدث خطأ غير متوقع";

const getHttpErrorStatus = (error: unknown): number | undefined => {
  if (typeof error !== "object" || error === null || !("status" in error)) {
    return undefined;
  }
  const status = (error as { status?: unknown }).status;
  return typeof status === "number" ? status : undefined;
};

const getHttpErrorData = (error: unknown): unknown => {
  if (typeof error !== "object" || error === null || !("data" in error)) {
    return undefined;
  }
  return (error as { data?: unknown }).data;
};

const isDuplicateShopResponse = (
  data: unknown
): data is { is_duplicate: true; existing_shop: DuplicateShopPayload } => {
  if (typeof data !== "object" || data === null) return false;
  const record = data as Record<string, unknown>;
  return (
    record.is_duplicate === true &&
    typeof record.existing_shop === "object" &&
    record.existing_shop !== null
  );
};

const normalizeShops = (data: unknown): Shop[] => {
  if (!Array.isArray(data)) return [];
  return data.map((raw) => {
    const shop = raw as ShopWire;
    return {
      ...shop,
      initialDebt: Number(shop.initialDebt) || 0,
      maxDebtLimit: Number(shop.maxDebtLimit) || 0,
    };
  });
};

const isTabId = (value: string | null): value is TabId =>
  value === "routes" || value === "zones" || value === "launch";

const frequencyFromIntervalDays = (days: number | null): string => {
  if (days === 7) return "كل 7 أيام";
  if (days === 14) return "كل 14 يوم";
  if (days === 30) return "كل 30 يوم";
  return "مخصص";
};

const intervalDaysFromFrequency = (
  frequency: string,
  customDays: number
): number | null => {
  if (frequency === "كل 7 أيام") return 7;
  if (frequency === "كل 14 يوم") return 14;
  if (frequency === "كل 30 يوم") return 30;
  if (frequency === "مخصص" && Number.isInteger(customDays) && customDays > 0) {
    return customDays;
  }
  return null;
};

// Utils
const sortZones = (zones: Zone[]) => {
  const colorByStatus: Record<string, string> = {
    overdue: "text-red-600 font-bold",
    today: "text-emerald-600 font-bold",
    upcoming: "text-amber-500 font-bold",
    null: "text-slate-400",
  };
  const weights: Record<string, number> = {
    overdue: 4,
    today: 3,
    upcoming: 2,
    null: 0,
  };

  return [...zones]
    .map((zone) => ({
      ...zone,
      dateColor:
        colorByStatus[String(zone.scheduleStatus ?? "null")] ||
        "text-slate-500",
    }))
    .sort((a, b) => {
      const aStatus = String(a.scheduleStatus ?? "null");
      const bStatus = String(b.scheduleStatus ?? "null");
      const weightDiff = (weights[bStatus] || 0) - (weights[aStatus] || 0);
      if (weightDiff !== 0) return weightDiff;
      return String(a.startDate || "").localeCompare(String(b.startDate || ""));
    });
};

export default function DispatchBoard() {
  const [activeTab, setActiveTab] = useState<TabId>(() => {
    const stored = localStorage.getItem("activeTab");
    return isTabId(stored) ? stored : "routes";
  });
  const [confirmDialog, setConfirmDialog] = useState<{ isOpen: boolean, title: string, message: string, onConfirm: () => void }>({ isOpen: false, title: "", message: "", onConfirm: () => { } });
  const [unsavedTabPrompt, setUnsavedTabPrompt] = useState<TabId | null>(null);

  // +++ حالات نافذة تعديل الحمولة +++
  const [isInventoryModalOpen, setIsInventoryModalOpen] = useState(false);
  const [inventoryRoute, setInventoryRoute] = useState<PendingRoute | null>(null);

  // +++ حالات رادار الحوالات +++
  const [isRadarModalOpen, setIsRadarModalOpen] = useState(false);
  const [radarRoute, setRadarRoute] = useState<PendingRoute | null>(null);

  useEffect(() => { localStorage.setItem("activeTab", activeTab); }, [activeTab]);

  const authenticatedFetch = useAuthFetch();

  const [zones, setZones] = useState<Zone[]>([]);
  const [drivers, setDrivers] = useState<{ id: string; name: string }[]>([]);
  const [vehicles, setVehicles] = useState<{ id: string; label: string }[]>([]);
  const [products, setProducts] = useState<{ id: string; name: string }[]>([]);
  const [warehouses, setWarehouses] = useState<WarehouseOption[]>([]);
  const [selectedSourceWarehouseId, setSelectedSourceWarehouseId] = useState("");
  const [pendingRoutes, setPendingRoutes] = useState<PendingRoute[]>([]);
  const [shortages, setShortages] = useState<Shortage[]>([]);
  const [shops, setShops] = useState<Shop[]>([]);

  // +++ الدرع المعماري للـ UX: ربط المنطقة المحددة بالذاكرة المحلية لمنع ضياعها عند الـ Refresh +++
  const [selectedZoneIdForZones, setSelectedZoneIdForZones] = useState(() => localStorage.getItem("wanasah_selected_zone") || "");

  useEffect(() => {
    if (selectedZoneIdForZones) {
      localStorage.setItem("wanasah_selected_zone", selectedZoneIdForZones);
    } else {
      localStorage.removeItem("wanasah_selected_zone");
    }
  }, [selectedZoneIdForZones]);

  // +++ الذاكرة الفولاذية: حفظ خيارات إطلاق خط السير +++
  const [selectedZoneId, setSelectedZoneId] = useState(() => localStorage.getItem("wanasah_route_zone") || "");
  const [selectedDriverId, setSelectedDriverId] = useState(() => localStorage.getItem("wanasah_route_driver") || "");
  const [selectedVehicleId, setSelectedVehicleId] = useState(() => localStorage.getItem("wanasah_route_vehicle") || "");

  useEffect(() => {
    localStorage.setItem("wanasah_route_zone", selectedZoneId);
    localStorage.setItem("wanasah_route_driver", selectedDriverId);
    localStorage.setItem("wanasah_route_vehicle", selectedVehicleId);
  }, [selectedZoneId, selectedDriverId, selectedVehicleId]);
  const [preloadQuantities, setPreloadQuantities] = useState<Record<string, number>>({});

  const [isRouteModalOpen, setIsRouteModalOpen] = useState(false);
  const [routeModalType, setRouteModalType] = useState<"follow_up" | "transfer">("follow_up");
  const [activeRoute, setActiveRoute] = useState<PendingRoute | null>(null);
  const [transferDriverId, setTransferDriverId] = useState("");

  const [isShortageModalOpen, setIsShortageModalOpen] = useState(false);
  const [shortageZoneId, setShortageZoneId] = useState("");
  const [shortageDriverId, setShortageDriverId] = useState("");
  const [shortageShopId, setShortageShopId] = useState("");
  const [shortageDraft, setShortageDraft] = useState<{ productId: string; productName: string; quantity: number }[]>([]);
  const [newShortage, setNewShortage] = useState<Partial<Shortage>>({});
  const [editingShortageIds, setEditingShortageIds] = useState<string[]>([]); // IDs to delete on confirm

  const [isSchedulingModalOpen, setIsSchedulingModalOpen] = useState(false);
  const [schedulingType, setSchedulingType] = useState<"bulk" | "local">("bulk");
  const [selectedBulkZoneIds, setSelectedBulkZoneIds] = useState<string[]>([]);
  const [bulkZoneSearch, setBulkZoneSearch] = useState("");
  const [customDays, setCustomDays] = useState(14);
  const [schedulingForm, setSchedulingForm] = useState({ frequency: "كل 7 أيام", startDate: "" });

  const [isZoneModalOpen, setIsZoneModalOpen] = useState(false);
  const [zoneFormName, setZoneFormName] = useState("");
  const [editingZoneId, setEditingZoneId] = useState<string | null>(null);

  const [isShopModalOpen, setIsShopModalOpen] = useState(false);
  const [editingShopId, setEditingShopId] = useState<string | null>(null);
  const [shopForm, setShopForm] = useState({ name: "", owner: "", phone: "", mapLink: "", zoneId: "", initialDebt: 0, maxDebtLimit: 0 });

  const [showRecycleBin, setShowRecycleBin] = useState(false);
  const [recycleSearchQuery, setRecycleSearchQuery] = useState("");
  const [isZoneRecycleBinOpen, setIsZoneRecycleBinOpen] = useState(false);
  const [isBulkImportModalOpen, setIsBulkImportModalOpen] = useState(false);
  const [zoneRecycleSearchQuery, setZoneRecycleSearchQuery] = useState("");
  const [archivedZones, setArchivedZones] = useState<Zone[]>([]);

  const [shopSearchQuery, setShopSearchQuery] = useState("");
  const [zoneSearchQueryMain, setZoneSearchQueryMain] = useState("");
  const [isEditMode, setIsEditMode] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [selectedShopIds, setSelectedShopIds] = useState<string[]>([]);
  const [isBulkTransferModalOpen, setIsBulkTransferModalOpen] = useState(false);
  const [targetTransferZoneId, setTargetTransferZoneId] = useState("");
  const [isShowPostponedModalOpen, setIsShowPostponedModalOpen] = useState(false);
  // +++ الدرع المعماري: فصل حالة السيرفر عن حالة الواجهة لمنع التلوث +++
  const [duplicateWarning, setDuplicateWarning] = useState<DuplicateWarningState | null>(null);
  const [restorePromptShop, setRestorePromptShop] = useState<Shop | null>(null);

  // Snapshot of shops taken when entering edit mode — used for Cancel/revert
  const savedShopsRef = useRef<Shop[]>([]);
  const shortageMutationInFlightRef = useRef(false);

  const [isSuicideModalOpen, setIsSuicideModalOpen] = useState(false);
  const [zoneToKill, setZoneToKill] = useState<Zone | null>(null);
  const [confirmName, setConfirmName] = useState("");

  // C-03: React-state product search filter (replaces DOM manipulation)
  const [productSearch, setProductSearch] = useState("");

  // CS-WH-03: Warehouse audit lock status for dispatch warning banner
  const [isWarehouseLocked, setIsWarehouseLocked] = useState(false);
  const [isWarehouseStatusLoading, setIsWarehouseStatusLoading] = useState(false);
  const [vehicleInventoryLoadedForId, setVehicleInventoryLoadedForId] = useState<string | null>(null);
  const [vehicleInventoryReloadKey, setVehicleInventoryReloadKey] = useState(0);

  const fetchInitialData = useCallback(() => {
    const controller = new AbortController();
    authenticatedFetch("/dispatch/init", { signal: controller.signal })
      .then((raw) => {
        const data = raw as DispatchInitPayload;
        const sorted = sortZones(Array.isArray(data.zones) ? data.zones : []);
        const nextDrivers = Array.isArray(data.drivers) ? data.drivers : [];
        const nextVehicles = Array.isArray(data.vehicles) ? data.vehicles : [];
        const nextProducts = Array.isArray(data.products) ? data.products : [];

        setZones(sorted);
        setDrivers(nextDrivers);
        setVehicles(nextVehicles);
        setProducts(nextProducts);

        setSelectedZoneIdForZones((prev) =>
          sorted.some((zone) => zone.id === prev)
            ? prev
            : (sorted[0]?.id || "")
        );
        setSelectedZoneId((prev) =>
          sorted.some((zone) => zone.id === prev) ? prev : ""
        );
        setSelectedDriverId((prev) =>
          nextDrivers.some((driver) => driver.id === prev) ? prev : ""
        );
        setSelectedVehicleId((prev) =>
          nextVehicles.some((vehicle) => vehicle.id === prev) ? prev : ""
        );

        if (nextProducts.length > 0) {
          setNewShortage((prev) =>
            prev.productId
              ? prev
              : {
                  productId: nextProducts[0].id,
                  productName: nextProducts[0].name,
                  quantity: 1,
                }
          );
        }
      })
      .catch((err: unknown) => {
        if (!(err instanceof Error && err.name === "AbortError")) {
          console.warn("تأخير بسيط في جلب البيانات:", getErrorMessage(err));
        }
      });

    // H-02: Pass abort signal to all parallel fetches for clean unmount cleanup
    // H-03: Add Array.isArray guards to prevent .map is not a function crashes
    const signal = controller.signal;
    authenticatedFetch("/dispatch/shops", { signal })
      .then((data) => setShops(normalizeShops(data)))
      .catch((err: unknown) => {
        if (!(err instanceof Error && err.name === "AbortError")) console.error(err);
      });
    authenticatedFetch("/dispatch/active_routes", { signal })
      .then(data => setPendingRoutes(Array.isArray(data) ? data : []))
      .catch(err => { if (err.name !== 'AbortError') console.error(err); });
    authenticatedFetch("/dispatch/shortages", { signal })
      .then(data => setShortages(Array.isArray(data) ? data : []))
      .catch(err => { if (err.name !== 'AbortError') console.error(err); });

    authenticatedFetch("/warehouse/locations", { signal })
      .then((data) => {
        const locations = Array.isArray(data)
          ? data.map((raw) => raw as WarehouseLocationPayload)
          : [];
        const options = locations.map((location) => ({
          id: String(location.id),
          label: `${location.name} (${location.code})`,
        }));
        setWarehouses(options);
        setSelectedSourceWarehouseId((prev) =>
          options.some((warehouse) => warehouse.id === prev) ? prev : ""
        );
      })
      .catch((err: unknown) => {
        if (!(err instanceof Error && err.name === "AbortError")) console.error(err);
      });

    return controller;
  }, [authenticatedFetch]); // +++ E-04: إضافة authenticatedFetch كـ Dependency لتجنب تحذيرات وتسريبات الذاكرة +++

  // Warehouse lock is scoped to the explicitly selected source warehouse.
  useEffect(() => {
    if (!selectedSourceWarehouseId) {
      setIsWarehouseLocked(false);
      setIsWarehouseStatusLoading(false);
      return;
    }

    const controller = new AbortController();
    setIsWarehouseStatusLoading(true);
    authenticatedFetch(
      `/warehouse/status?location_id=${encodeURIComponent(selectedSourceWarehouseId)}`,
      { signal: controller.signal }
    )
      .then((data) => {
        const status =
          typeof data === "object" && data !== null && "status" in data
            ? String((data as { status: unknown }).status)
            : "";
        setIsWarehouseLocked(status === "AUDIT_LOCK");
      })
      .catch((err: unknown) => {
        if (!(err instanceof Error && err.name === "AbortError")) {
          console.error(err);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsWarehouseStatusLoading(false);
      });

    return () => controller.abort();
  }, [selectedSourceWarehouseId, authenticatedFetch]);

  // Realtime dispatch updates: authenticate each reconnect with the latest token
  // and coalesce event bursts into one dashboard refresh.
  useEffect(() => {
    const controller = fetchInitialData();
    const apiUrl = (import.meta.env.VITE_API_URL || "").replace(/\/+$/, "");

    let ws: WebSocket | undefined;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    let realtimeRefreshController: AbortController | null = null;
    let retryCount = 0;
    let workerAlertTimer: ReturnType<typeof setTimeout> | undefined;
    const workerAlerts = new Map<
      string,
      { count: number; message: string; severity: "warning" | "error" }
    >();

    const flushWorkerAlerts = () => {
      workerAlerts.forEach(({ count, message, severity }) => {
        const rendered =
          count > 1 ? `${message} (+${count - 1} تنبيهات أخرى)` : message;
        if (severity === "warning") toast.warning(rendered);
        else toast.error(rendered);
      });
      workerAlerts.clear();
      workerAlertTimer = undefined;
    };

    const queueWorkerAlert = (eventName: string, message: string) => {
      const severity: "warning" | "error" =
        eventName === "STALE_HANDSHAKE_WARNING" ||
        eventName === "STALE_SESSION_WARNING"
          ? "warning"
          : "error";
      const previous = workerAlerts.get(eventName);
      workerAlerts.set(eventName, {
        count: (previous?.count || 0) + 1,
        message,
        severity,
      });
      if (workerAlertTimer) clearTimeout(workerAlertTimer);
      workerAlertTimer = setTimeout(flushWorkerAlerts, 500);
    };

    const scheduleRealtimeRefresh = () => {
      if (refreshTimer) clearTimeout(refreshTimer);
      refreshTimer = setTimeout(() => {
        realtimeRefreshController?.abort();
        realtimeRefreshController = fetchInitialData();
      }, 300);
    };

    const connectWS = () => {
      const token = localStorage.getItem("admin_token");
      if (!apiUrl || !token) return;

      const wsUrl =
        apiUrl.replace(/^http/, "ws") +
        `/ws/dispatch?token=${encodeURIComponent(token)}`;
      ws = new WebSocket(wsUrl);

      ws.onmessage = (event) => {
        try {
          const parsed: unknown = JSON.parse(event.data);
          if (typeof parsed !== "object" || parsed === null) return;
          const data = parsed as WorkerRealtimeEvent;
          if (!data.event) return;

          const isWorkerAlert =
            data.event === "STALE_HANDSHAKE_WARNING" ||
            data.event === "STALE_HANDSHAKE_CRITICAL" ||
            data.event === "STALE_SESSION_WARNING" ||
            data.event === "STALE_SESSION_CRITICAL" ||
            data.event === "INTEGRITY_ALERT";

          if (isWorkerAlert && data.message) {
            queueWorkerAlert(data.event, data.message);
          } else {
            scheduleRealtimeRefresh();
          }
        } catch (err) {
          console.error("WS Parse error", err);
        }
      };

      ws.onclose = () => {
        if (document.visibilityState === "hidden") return;
        const backoff = Math.min(1000 * Math.pow(2, retryCount), 30000);
        retryCount += 1;
        reconnectTimer = setTimeout(connectWS, backoff);
      };
      ws.onopen = () => {
        retryCount = 0;
      };
      ws.onerror = () => {};
    };

    connectWS();

    const handleVisChange = () => {
      if (
        document.visibilityState === "visible" &&
        (!ws || ws.readyState === WebSocket.CLOSED)
      ) {
        retryCount = 0;
        connectWS();
      }
    };
    document.addEventListener("visibilitychange", handleVisChange);

    return () => {
      controller.abort();
      realtimeRefreshController?.abort();
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (refreshTimer) clearTimeout(refreshTimer);
      if (workerAlertTimer) clearTimeout(workerAlertTimer);
      workerAlerts.clear();
      document.removeEventListener("visibilitychange", handleVisChange);
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    };
  }, [fetchInitialData]);

  useEffect(() => {
    if (!selectedVehicleId) {
      setPreloadQuantities({});
      setVehicleInventoryLoadedForId(null);
      return;
    }

    const requestedVehicleId = selectedVehicleId;
    const controller = new AbortController();
    setVehicleInventoryLoadedForId(null);

    authenticatedFetch(`/dispatch/inventory/${requestedVehicleId}`, {
      signal: controller.signal,
    })
      .then((data) => {
        if (!Array.isArray(data)) {
          throw new Error("استجابة مخزون المركبة غير صالحة.");
        }
        const inventory: Record<string, number> = {};
        data.forEach((raw) => {
          const item = raw as VehicleInventoryPayload;
          inventory[String(item.product_id)] = Number(item.current_quantity) || 0;
        });
        setPreloadQuantities(inventory);
        setVehicleInventoryLoadedForId(requestedVehicleId);
      })
      .catch((err: unknown) => {
        if (err instanceof Error && err.name === "AbortError") return;
        setVehicleInventoryLoadedForId(null);
        toast.error("خطأ في جلب مخزون المركبة: " + getErrorMessage(err));
      });

    return () => controller.abort();
  }, [selectedVehicleId, vehicleInventoryReloadKey, authenticatedFetch]);

  useEffect(() => { setIsEditMode(false); setSelectedShopIds([]); setHasUnsavedChanges(false); }, [activeTab]);

  // +++ المحرك الصاروخي O(1): حساب النواقص لكل مندوب مرة واحدة فقط بدل حسابها داخل الـ Loop +++
  const driverShortagesMap = useMemo(() => {
    const map: Record<string, Set<string>> = {};
    shortages.forEach(s => {
      if (s.status === "pending" && s.driverId) {
        if (!map[s.driverId]) map[s.driverId] = new Set();
        map[s.driverId].add(s.shopId);
      }
    });
    const countMap: Record<string, number> = {};
    for (const driverId in map) {
      countMap[driverId] = map[driverId].size;
    }
    return countMap;
  }, [shortages]);

  // Helper: save the current reorder to the backend
  const handleSaveReorder = useCallback(async () => {
    const currentZoneShops = shops.filter(s => s.zoneId === selectedZoneIdForZones);

    // +++ اللوجيك الذكي: ترتيب المحلات النشطة، وإرسال حالة المحذوفة للسيرفر +++
    let seq = 1;
    const payload = currentZoneShops
      .sort((a, b) => Number(a.sequence) - Number(b.sequence))
      .map(s => {
        if (s.archived) {
          return { id: s.id, archived: true };
        } else {
          return { id: s.id, sequence: seq++, archived: false };
        }
      });

    setIsSaving(true);
    try {
      await authenticatedFetch("/dispatch/shops/bulk_update", {
        method: "PUT",
        body: JSON.stringify(payload)
      });
      savedShopsRef.current = shops; // new baseline
      setHasUnsavedChanges(false);
      setIsEditMode(false);
      setSelectedShopIds([]);
      fetchInitialData();
      toast.success("تم حفظ التعديلات بنجاح ✓");
      return true;
    } catch (err: unknown) {
      toast.error("خطأ في حفظ التعديلات: " + getErrorMessage(err));
      return false;
    } finally {
      setIsSaving(false);
    }
  }, [authenticatedFetch, fetchInitialData, selectedZoneIdForZones, shops]);

  // Helper: cancel edits and revert by re-fetching from server
  const handleCancelReorder = useCallback(async () => {
    try {
      const freshShops = await authenticatedFetch("/dispatch/shops");
      setShops(normalizeShops(freshShops));
    } catch (e) {
      // fallback to snapshot if fetch fails
      setShops(savedShopsRef.current);
    }
    setHasUnsavedChanges(false);
    setIsEditMode(false);
    setSelectedShopIds([]);
  }, [authenticatedFetch]);

  const fetchArchivedZones = async () => {
    try {
      const data = await authenticatedFetch("/dispatch/zones/archived");
      if (!Array.isArray(data)) {
        throw new Error("استجابة أرشيف المناطق غير صالحة.");
      }
      setArchivedZones(
        data.map((raw) => {
          const zone = raw as ArchivedZonePayload;
          return {
            id: String(zone.id),
            name: zone.name,
            scheduleStatus: "null",
            startDate: "",
            intervalDays: null,
            shopsCount: 0,
          } as Zone;
        })
      );
    } catch (err: unknown) {
      toast.error("خطأ في جلب أرشيف المناطق: " + getErrorMessage(err));
    }
  };

  const handleRestoreZone = async (zoneId: string) => {
    try {
      await authenticatedFetch(`/dispatch/zones/${zoneId}/restore`, {
      method: "PUT",
      body: JSON.stringify({
        mode: "shops_archived_by_same_zone",
      }),
    });

      const [initRaw, shopsRaw] = await Promise.all([
        authenticatedFetch("/dispatch/init"),
        authenticatedFetch("/dispatch/shops"),
      ]);
      const initData = initRaw as DispatchInitPayload;
      setZones(sortZones(Array.isArray(initData.zones) ? initData.zones : []));
      setShops(normalizeShops(shopsRaw));
      setArchivedZones((prev) => prev.filter((zone) => zone.id !== zoneId));

      toast.success("تم استعادة المنطقة بنجاح");
      if (archivedZones.length <= 1) setIsZoneRecycleBinOpen(false);
    } catch (err: unknown) {
      toast.error("خطأ في الاستعادة: " + getErrorMessage(err));
    }
  };

  // Helper: handle tab switch with dirty-state guard
  const handleTabChange = useCallback((tabId: TabId) => {
    if (tabId === activeTab) return;
    if (hasUnsavedChanges) {
      setUnsavedTabPrompt(tabId); // تفعيل النافذة الذكية بدل العادية
      return;
    }
    setActiveTab(tabId);
  }, [activeTab, hasUnsavedChanges]);

  const handleDispatchRoute = () => {
    if (
      !selectedZoneId ||
      !selectedDriverId ||
      !selectedVehicleId ||
      !selectedSourceWarehouseId
    ) {
      return toast.error("⚠️ يرجى تحديد المنطقة والمندوب والسيارة ومستودع المصدر");
    }
    if (isWarehouseStatusLoading) {
      return toast.info("جاري التحقق من حالة مستودع المصدر...");
    }
    if (isWarehouseLocked) {
      return toast.error("🔒 مستودع المصدر تحت الجرد حالياً ولا يمكن إطلاق حمولة منه.");
    }
    if (vehicleInventoryLoadedForId !== selectedVehicleId) {
      return toast.info("جاري تحميل مخزون السيارة. حاول بعد اكتمال القراءة.");
    }

    const targetShops = shops.filter(s => s.zoneId === selectedZoneId && !s.archived);
    if (targetShops.length === 0) {
      return toast.error("⚠️ المنطقة المختارة لا تحتوي على محلات نشطة.");
    }
    if (Object.values(preloadQuantities).reduce((acc, q) => acc + (Number(q) || 0), 0) === 0) return toast.error("⚠️ لا يمكن إطلاق خط السير بحمولة صفر");

    authenticatedFetch("/dispatch/route", {
      method: "POST",
      body: JSON.stringify({
        zone_id: selectedZoneId,
        driver_id: selectedDriverId,
        vehicle_id: selectedVehicleId,
        source_location_id: Number(selectedSourceWarehouseId),
        inventory: preloadQuantities
      })
    })
      .then(() => {
        toast.success("تم إطلاق خط السير بنجاح");
        setSelectedZoneId(""); setSelectedDriverId(""); setSelectedVehicleId(""); setPreloadQuantities({});
        // +++ الكي الجراحي: استخدام Array.isArray لمنع كراش دالة .map إذا أرجع السيرفر كائن خطأ بدل المصفوفة +++
        authenticatedFetch("/dispatch/active_routes").then(data => setPendingRoutes(Array.isArray(data) ? data : [])).catch(err => console.error(err));
      })
      .catch(err => toast.error("خطأ في إطلاق خط السير: " + getErrorMessage(err)));
  };

  const handleConfirmRouteAction = async () => {
    if (!activeRoute) return;
    if (activeRoute.sessionEnded) {
      toast.error("لا يمكن إعادة تشغيل هذا المسار من هنا بعد انتهاء WorkSession.");
      return;
    }
    if (!selectedVehicleId) {
      toast.error("⚠️ اختر السيارة.");
      return;
    }
    if (vehicleInventoryLoadedForId !== selectedVehicleId) {
      toast.info("جاري تحميل مخزون السيارة. انتظر اكتمال القراءة قبل الاعتماد.");
      return;
    }

    const newDriverId =
      routeModalType === "transfer" ? transferDriverId : activeRoute.driverId;

    if (
      routeModalType === "transfer" &&
      (!newDriverId || newDriverId === activeRoute.driverId)
    ) {
      toast.error("⚠️ اختر مندوباً آخر للتحويل.");
      return;
    }
    if (
      activeRoute.sessionBound &&
      (newDriverId !== activeRoute.driverId ||
        selectedVehicleId !== activeRoute.vehicleId)
    ) {
      toast.error("لا يمكن تغيير المندوب أو السيارة بعد ربط WorkSession.");
      return;
    }

    try {
      await authenticatedFetch(`/dispatch/route/${activeRoute.id}/status`, {
        method: "PUT",
        body: JSON.stringify({
          status: "active",
          driverId: newDriverId,
          vehicleId: selectedVehicleId,
          inventory: preloadQuantities
        })
      });

      const freshRoutes = await authenticatedFetch("/dispatch/active_routes");
      setPendingRoutes(Array.isArray(freshRoutes) ? freshRoutes : []);

      toast.success("تم تفعيل خط السير بنجاح");
      setIsRouteModalOpen(false);
    } catch (err: unknown) {
      toast.error(getErrorMessage(err));
    }
  };

  const handleUpdateScheduling = async () => {
    const targetIds =
      schedulingType === "bulk"
        ? selectedBulkZoneIds
        : [selectedZoneIdForZones].filter(Boolean);

    if (targetIds.length === 0) {
      toast.error("⚠️ اختر منطقة واحدة على الأقل للجدولة.");
      return;
    }
    if (!schedulingForm.startDate) {
      toast.error("⚠️ تاريخ البدء مطلوب.");
      return;
    }

    const intervalDays = intervalDaysFromFrequency(
      schedulingForm.frequency,
      customDays
    );
    if (intervalDays === null) {
      toast.error("⚠️ عدد أيام التكرار يجب أن يكون عدداً صحيحاً أكبر من صفر.");
      return;
    }

    setIsSchedulingModalOpen(false);

    const results = await Promise.allSettled(
      targetIds.map((id) =>
        authenticatedFetch(`/dispatch/zones/${id}`, {
          method: "PUT",
          body: JSON.stringify({
            intervalDays,
            startDate: schedulingForm.startDate,
          }),
        })
      )
    );

    const successIds = targetIds.filter(
      (_, index) => results[index].status === "fulfilled"
    );
    const failedCount = targetIds.length - successIds.length;

    if (successIds.length > 0) {
      const initRaw = await authenticatedFetch("/dispatch/init");
      const initData = initRaw as DispatchInitPayload;
      setZones(sortZones(Array.isArray(initData.zones) ? initData.zones : []));
      toast.success(
        `تم تحديث إعدادات الجدولة بنجاح لـ ${successIds.length} منطقة`
      );
    }
    if (failedCount > 0) {
      toast.error(`فشل تحديث ${failedCount} منطقة.`);
    }
  };

  const handleSaveZone = async () => {
  const cleanZoneName = zoneFormName.trim();

  if (cleanZoneName.length < 2) {
    toast.error("⚠️ اسم المنطقة يجب أن يحتوي حرفين على الأقل");
    return;
  }

  if (cleanZoneName.length > 100) {
    toast.error("⚠️ اسم المنطقة لا يجوز أن يتجاوز 100 حرف");
    return;
  }

  try {
    if (editingZoneId) {
      await authenticatedFetch(`/dispatch/zones/${editingZoneId}`, {
        method: "PUT",
        body: JSON.stringify({ name: cleanZoneName }),
      });

      const initRaw = await authenticatedFetch("/dispatch/init");
      const initData = initRaw as DispatchInitPayload;

      setZones(
        sortZones(Array.isArray(initData.zones) ? initData.zones : [])
      );

      setIsZoneModalOpen(false);
      setZoneFormName("");
      setEditingZoneId(null);

      toast.success("تم الحفظ بنجاح");
    } else {
      const raw = await authenticatedFetch("/dispatch/zones", {
        method: "POST",
        body: JSON.stringify({ name: cleanZoneName }),
      });

      const response =
        typeof raw === "object" && raw !== null
          ? (raw as { zone_id?: unknown })
          : {};

      if (
        typeof response.zone_id !== "string" &&
        typeof response.zone_id !== "number"
      ) {
        throw new Error("استجابة إنشاء المنطقة غير مكتملة.");
      }

      const newZoneId = String(response.zone_id);

      const initRaw = await authenticatedFetch("/dispatch/init");
      const initData = initRaw as DispatchInitPayload;

      setZones(
        sortZones(Array.isArray(initData.zones) ? initData.zones : [])
      );

      setIsZoneModalOpen(false);
      setZoneFormName("");
      setEditingZoneId(null);

      toast.success("تم إضافة المنطقة ✅. يرجى تحديد جدولتها الآن.");

      setSelectedZoneIdForZones(newZoneId);
      setSchedulingType("local");
      setSchedulingForm({
        frequency: "كل 7 أيام",
        startDate: "",
      });
      setCustomDays(14);
      setIsSchedulingModalOpen(true);
    }
  } catch (err: unknown) {
    toast.error("خطأ في حفظ المنطقة: " + getErrorMessage(err));
  }
};

  const handleSaveShop = async () => {
    if (isSaving) return; // +++ درع الحماية: منع النقر المزدوج وازدواجية البيانات +++
    if (!shopForm.name.trim() || !shopForm.zoneId) {
      toast.error("⚠️ اسم المحل والمنطقة مطلوبان");
      return;
    }
    setIsSaving(true);

    // +++ الكي الجراحي: مطابقة أسماء المتغيرات بدقة مع Pydantic Schemas لنسف خطأ 422 +++
    const apiPayload: ShopMutationPayload = {
      name: shopForm.name,
      owner: shopForm.owner,
      phone: shopForm.phone,
      initialDebt: Number(shopForm.initialDebt) || 0,
      maxDebtLimit: Number(shopForm.maxDebtLimit) || 0,
      mapLink: shopForm.mapLink,
      zoneId: Number(shopForm.zoneId) // تحويل المنطقة لرقم صريح
    };

    const localShopState: LocalShopState = {
      name: shopForm.name,
      owner: shopForm.owner,
      phone: shopForm.phone,
      initialDebt: Number(shopForm.initialDebt) || 0,
      maxDebtLimit: Number(shopForm.maxDebtLimit) || 0,
      mapLink: shopForm.mapLink,
      zoneId: shopForm.zoneId
    };

    try {
      if (editingShopId) {
        await authenticatedFetch(`/dispatch/shops/${editingShopId}`, {
          method: "PUT",
          body: JSON.stringify(apiPayload)
        });
        const [shopsRaw, initRaw] = await Promise.all([
          authenticatedFetch("/dispatch/shops"),
          authenticatedFetch("/dispatch/init"),
        ]);
        setShops(normalizeShops(shopsRaw));
        const initData = initRaw as DispatchInitPayload;
        setZones(sortZones(Array.isArray(initData.zones) ? initData.zones : []));
        setIsShopModalOpen(false);
        toast.success("تم تحديث بيانات المحل ✅");
      } else {
        // +++ استخدام الهوك المطور لاصطياد الـ 409 دون التفاف +++
        const data = await authenticatedFetch("/dispatch/shops", {
          method: "POST",
          body: JSON.stringify({ ...apiPayload, force_save: false })
        });
        const newShop = { ...localShopState, id: String(data.shop_id), sequence: 999, archived: false };
        setShops(prev => [...prev, newShop]);
        setZones(prev => sortZones(prev.map(z => z.id === localShopState.zoneId ? { ...z, shopsCount: (z.shopsCount || 0) + 1 } : z)));
        setIsShopModalOpen(false);
        toast.success("تم الإضافة بنجاح");
      }
    } catch (error: unknown) {
      const status = getHttpErrorStatus(error);
      const data = getHttpErrorData(error);
      if (status === 409 && isDuplicateShopResponse(data)) {
        setDuplicateWarning({
          show: true,
          shopData: data.existing_shop,
          apiPayload: { ...apiPayload, force_save: true },
          localState: localShopState,
        });
      } else {
        toast.error(`❌ خطأ: ${getErrorMessage(error)}`);
      }
    } finally {
      setIsSaving(false); // +++ تحرير الدرع بعد انتهاء العملية +++
    }
  };

  const forceSaveShop = async () => {
    if (!duplicateWarning) return;

    const payload = { ...duplicateWarning.apiPayload, force_save: true };

    try {
      // نعود للهوك لأن فرض الحفظ لا يرجع 409 أبداً
      const data = await authenticatedFetch("/dispatch/shops", {
        method: "POST",
        body: JSON.stringify(payload)
      });

      // +++ استخدام الكائن المحلي النظيف (Camel Case) المحفوظ في التحذير +++
      const newShop = {
        ...duplicateWarning.localState,
        id: String(data.shop_id),
        sequence: 999,
        archived: false
      };

      setShops(prev => [...prev, newShop]);
      setZones(prev => sortZones(prev.map(z => z.id === duplicateWarning.localState.zoneId ? { ...z, shopsCount: (z.shopsCount || 0) + 1 } : z)));

      toast.success("تم فرض الحفظ بنجاح");
      setIsShopModalOpen(false);
      setDuplicateWarning(null);
    } catch (error: unknown) {
      toast.error(getErrorMessage(error));
    }
  };

  const activeShops = useMemo(() => shops.filter(s => !s.archived), [shops]);
  const archivedShops = useMemo(() => shops.filter(s => s.archived), [shops]);
  const shopsInSelectedZone = useMemo(() => {
    let list = activeShops;
    if (shopSearchQuery.trim()) { const q = shopSearchQuery.toLowerCase(); list = list.filter(s => s.name.toLowerCase().includes(q) || s.owner.toLowerCase().includes(q) || s.phone.includes(q) || (zones.find(z => z.id === s.zoneId)?.name || "").toLowerCase().includes(q)); }
    else list = list.filter(s => s.zoneId === selectedZoneIdForZones);
    return list.sort((a, b) => Number(a.sequence) - Number(b.sequence));
  }, [activeShops, shopSearchQuery, selectedZoneIdForZones, zones]);

  const filteredRecycleBin = useMemo(() => {
    const q = recycleSearchQuery.toLowerCase(); return archivedShops.filter(s => s.name.toLowerCase().includes(q) || s.owner.toLowerCase().includes(q) || s.phone.includes(q) || (zones.find(z => z.id === s.zoneId)?.name || "").toLowerCase().includes(q));
  }, [archivedShops, recycleSearchQuery, zones]);

  const filteredZoneRecycleBin = useMemo(() => {
    const q = zoneRecycleSearchQuery.toLowerCase();
    return archivedZones.filter(z => z.name.toLowerCase().includes(q));
  }, [archivedZones, zoneRecycleSearchQuery]);

  const refreshShortages = useCallback(async () => {
    const data = await authenticatedFetch("/dispatch/shortages");
    setShortages(Array.isArray(data) ? data : []);
  }, [authenticatedFetch]);

  const replaceShortageGroupAtomic = useCallback(
    async (
      shortageIds: string[],
      items: Array<{
        zoneId: number;
        shopId: number;
        driverId: number | null;
        productId: number;
        quantity: number;
      }>
    ) => {
      if (shortageMutationInFlightRef.current) {
        toast.info("هناك عملية نواقص قيد التنفيذ.");
        return false;
      }

      const parsedIds = shortageIds.map(Number);
      if (
        parsedIds.length === 0 ||
        parsedIds.some((id) => !Number.isInteger(id) || id <= 0)
      ) {
        toast.error("معرفات طلبات النواقص غير صالحة.");
        return false;
      }

      shortageMutationInFlightRef.current = true;
      try {
        await authenticatedFetch("/dispatch/shortages/group", {
          method: "PUT",
          body: JSON.stringify({
            request_id: crypto.randomUUID(),
            shortage_ids: parsedIds,
            items,
          }),
        });
        await refreshShortages();
        return true;
      } catch (err: unknown) {
        toast.error(getErrorMessage(err));
        return false;
      } finally {
        shortageMutationInFlightRef.current = false;
      }
    },
    [authenticatedFetch, refreshShortages]
  );

  const handleAddShortage = async () => {
    if (!shortageZoneId || !shortageShopId || shortageDraft.length === 0) {
      return toast.error("⚠️ يرجى إكمال بيانات الطلب");
    }
    if (
      shortageDraft.some(
        (item) =>
          !item.productId ||
          !Number.isInteger(Number(item.productId)) ||
          Number(item.productId) <= 0 ||
          !Number.isInteger(Number(item.quantity)) ||
          Number(item.quantity) <= 0
      )
    ) {
      return toast.error("⚠️ يوجد منتج أو كمية غير صالحة في الطلب.");
    }

    const newShortages = shortageDraft.map((item) => ({
      zoneId: Number(shortageZoneId),
      shopId: Number(shortageShopId),
      driverId: shortageDriverId ? Number(shortageDriverId) : null,
      productId: Number(item.productId),
      quantity: Number(item.quantity),
    }));

    if (shortageMutationInFlightRef.current) {
      toast.info("هناك عملية نواقص قيد التنفيذ.");
      return;
    }

    try {
      let saved = false;
      if (editingShortageIds.length > 0) {
        saved = await replaceShortageGroupAtomic(
          editingShortageIds,
          newShortages
        );
      } else {
        shortageMutationInFlightRef.current = true;
        try {
          await authenticatedFetch("/dispatch/shortages", {
            method: "POST",
            body: JSON.stringify(newShortages),
          });
          await refreshShortages();
          saved = true;
        } finally {
          shortageMutationInFlightRef.current = false;
        }
      }

      if (!saved) return;

      const wasEditing = editingShortageIds.length > 0;
      setEditingShortageIds([]);
      setShortageDraft([]);
      if (products.length > 0) {
        setNewShortage({
          productId: products[0].id,
          productName: products[0].name,
          quantity: 1,
        });
      }
      toast.success(
        wasEditing
          ? "تم حفظ تعديلات الطلبات ذرياً"
          : "تم تسجيل الطلبات بنجاح"
      );
    } catch (err: unknown) {
      toast.error(getErrorMessage(err));
      shortageMutationInFlightRef.current = false;
    }
  };

  const handleAddProductToDraft = () => {
    if (!newShortage.productId || !newShortage.quantity) {
      return toast.error("⚠️ اختر منتج وكمية");
    }

    const product = products.find((item) => item.id === newShortage.productId);
    if (!product) {
      return toast.error("المنتج المحدد لم يعد متاحاً.");
    }

    setShortageDraft((prev) => {
      const existing = prev.findIndex(
        (item) => item.productId === product.id
      );
      if (existing !== -1) {
        return prev.map((item, index) =>
          index === existing
            ? {
                ...item,
                quantity: item.quantity + Number(newShortage.quantity),
              }
            : item
        );
      }
      return [
        ...prev,
        {
          productId: product.id,
          productName: product.name,
          quantity: Number(newShortage.quantity),
        },
      ];
    });
    setNewShortage((prev) => ({ ...prev, quantity: 1 }));
  };

  const handleEditShortageGroup = (
    shopId: string,
    driverId?: string
  ) => {
    const shopShortages = shortages.filter(
      (item) =>
        item.shopId === shopId &&
        (item.driverId || "") === (driverId || "")
    );
    if (shopShortages.length === 0) return;

    const first = shopShortages[0];
    const identityKeys = new Set(
      shopShortages.map(
        (item) =>
          `${item.zoneId}:${item.shopId}:${item.driverId || ""}`
      )
    );
    if (identityKeys.size !== 1) {
      toast.error("مجموعة النواقص غير متسقة ولا يمكن تعديلها بأمان.");
      return;
    }

    setShortageZoneId(first.zoneId);
    setShortageShopId(first.shopId);
    setShortageDriverId(first.driverId || "");

    setShortageDraft(
      shopShortages.map((item) => ({
        productId: item.productId,
        productName: item.productName,
        quantity: item.quantity,
      }))
    );

    setEditingShortageIds(shopShortages.map((item) => item.id));
    toast.info("تم تحميل الطلب للتعديل — الهوية ثابتة ويمكن تعديل المنتجات والكميات.");
  };

  const handleDeleteShortageGroup = (ids: string[]) => {
    setConfirmDialog({
      isOpen: true,
      title: "حذف طلبات المحل",
      message: `هل أنت متأكد من حذف المجموعة كاملة (${ids.length} منتجات)؟`,
      onConfirm: async () => {
        try {
          const deleted = await replaceShortageGroupAtomic(ids, []);
          if (deleted) {
            toast.success("تم حذف المجموعة كاملة ذرياً");
          }
        } finally {
          setConfirmDialog((dialog) => ({ ...dialog, isOpen: false }));
        }
      },
    });
  };

  const handleCloseShortageModal = () => {
    setIsShortageModalOpen(false);
    setShortageDraft([]);
    setShortageZoneId("");
    setShortageShopId("");
    setShortageDriverId("");
    setEditingShortageIds([]);
  };

  return (
    <div className="w-full h-full flex flex-col flex-1 min-h-0 animate-in fade-in duration-200">
      {/* +++ الكي الجراحي: إزالة التثبيت (sticky) لكي يصعد البار مع السكرول ولا يتداخل مع المحتوى +++ */}
      <div className="glass-card rounded-2xl h-16 md:h-20 px-4 md:px-6 flex items-center justify-between gap-3 relative z-20">
        <div className="flex items-center gap-6">
          <div className="flex bg-slate-100 p-1 rounded-xl">
            {/* +++  فصل الإطلاق عن المراقبة בـ 3 تبويبات +++ */}
            {([
              { id: "routes", label: "الخطوط النشطة", icon: Truck },
              { id: "launch", label: "إطلاق خط جديد", icon: Plus },
              { id: "zones", label: "هيكلة المناطق", icon: LayoutGrid }
            ] as const).map(tab => (
              <button key={tab.id} onClick={() => handleTabChange(tab.id)} className={`flex items-center gap-2 px-6 py-2 rounded-lg text-sm font-bold transition-all ${activeTab === tab.id ? "bg-white text-[#1e87bb] shadow-sm" : "text-slate-500 hover:text-slate-700"}`}>
                <tab.icon className="w-4 h-4" /> {tab.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {activeTab === "routes" && <button onClick={() => setIsShortageModalOpen(true)} className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold transition-all shadow-sm ${shortages.length > 0 ? "bg-amber-500 text-white animate-pulse" : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50"}`}><ClipboardList className="w-4 h-4" /> 📦 طلبات ونواقص</button>}
          {activeTab === "zones" && <button onClick={() => { setSchedulingType("bulk"); setSelectedBulkZoneIds(zones.map(z => z.id)); setIsSchedulingModalOpen(true); }} className="bg-[#1e87bb] hover:bg-[#0f766e] text-white px-4 py-2 rounded-xl text-sm font-bold flex items-center gap-2 transition-colors shadow-sm"><Calendar className="w-4 h-4" /> 🗓️ الجدولة الشاملة</button>}
        </div>
      </div>

      {/* CS-WH-03: Warehouse audit lock warning banner */}
      {isWarehouseLocked && (
        <div className="mx-0 mb-4 bg-amber-50 border-l-4 border-amber-500 p-4 rounded-r-lg shadow-sm" dir="rtl">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🔒</span>
            <div>
              <p className="text-amber-800 font-bold text-sm">المستودع مقفل حالياً — جرد مخزني قيد التنفيذ</p>
              <p className="text-amber-600 text-xs mt-1">عمليات إطلاق خطوط السير وتعديل الحمولات معلقة حتى انتهاء الجرد. يرجى مراجعة مشرف المستودع.</p>
            </div>
          </div>
        </div>
      )}

      {/* +++  تقليل الـ padding الخارجي ليتمدد المحتوى لليمين واليسار +++ */}
      {/* +++ الكي الجراحي: تحويل الحاوية لـ flex-1 لتمتص المساحة وإزالة الـ padding السفلي الزائد الذي يضرب القائمة الجانبية +++ */}
      <div className="pt-2 pb-0 px-0 w-full h-full flex-1 min-h-0 flex flex-col">
        <>
          {activeTab === "routes" ? (
            <div key="routes" className="flex flex-col w-full gap-4 mt-4 h-full flex-1 min-h-0">
              <div className="relative bg-white rounded-2xl border border-slate-200 flex flex-col shadow-sm pb-2 flex-1 min-h-0">
                
                {/* الشريطة العائمة */}
                <div className="absolute -top-3.5 right-6 bg-gradient-to-r from-[#1e87bb] to-[#166a94] text-white px-4 py-1.5 rounded-lg text-sm font-black flex items-center gap-2 shadow-md z-20">
                  <Truck className="w-4 h-4" /> مناطق قيد العمل (الخطوط النشطة)
                </div>

                {/* شريط الأدوات */}
                <div className="p-3 pt-2 border-b border-slate-100 flex items-center justify-end bg-slate-50 rounded-t-2xl">
                  {(() => {
                    const hasPostponed = pendingRoutes.some(r => r.status === "postponed");
                    return (
                      <button
                        onClick={() => setIsShowPostponedModalOpen(true)}
                        /* +++ تكبير الزر عبر px-4 py-2 text-sm +++ */
                        className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold shadow-sm transition-all ${hasPostponed ? "bg-orange-50 border border-orange-500 text-orange-700 hover:bg-orange-100" : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50"}`}
                      >
                        <Eye className="w-4 h-4" />
                        {hasPostponed && (
                          <span className="relative flex h-2 w-2">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-orange-400 opacity-75" />
                            <span className="relative inline-flex rounded-full h-2 w-2 bg-orange-500" />
                          </span>
                        )}
                        عرض المؤجل ({pendingRoutes.filter(r => r.status === "postponed").length})
                      </button>
                    );
                  })()}
                </div>

                {/* +++ الكي الجراحي: نسف الـ vh واستخدام flex-1 min-h-0 ليتمدد الجدول حسب المساحة المتاحة فقط +++ */}
                <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar bg-white rounded-b-2xl">
                  <PendingRoutesTable
                    routes={pendingRoutes.filter(r => r.status !== "postponed")}
                    onAdjustInventory={(route) => {
                      setInventoryRoute(route);
                      setIsInventoryModalOpen(true);
                    }}
                    onOpenRadar={(route) => {
                      setRadarRoute(route);
                      setIsRadarModalOpen(true);
                    }}
                    onOpenRouteModal={(r, t) => {
                      setActiveRoute(r);
                      setRouteModalType(t);
                      setTransferDriverId(r.driverId);
                      setPreloadQuantities({});
                      setVehicleInventoryLoadedForId(null);
                      setSelectedVehicleId(r.vehicleId);
                      setVehicleInventoryReloadKey((key) => key + 1);
                      setIsRouteModalOpen(true);
                    }}
                    onPostponeRoute={async (id) => {
                      try {
                        await authenticatedFetch(`/dispatch/route/${id}/status`, {
                          method: "PUT",
                          body: JSON.stringify({ status: "postponed" })
                        });
                        setPendingRoutes(prev => prev.map(r => r.id === id ? { ...r, status: "postponed" } : r));
                        toast.info("تم تأجيل المنطقة");
                      } catch (e: unknown) {
                        toast.error(getErrorMessage(e));
                      }
                    }}
                    onCloseZone={route => {
                      const isAlmostDone = route.shopsRemaining > 0 && route.shopsRemaining <= 5;
                      const message = isAlmostDone
                        ? `تنبيه: باقي ${route.shopsRemaining} محلات فقط لإنهاء المنطقة! هل أنت متأكد من إغلاق خط السير؟`
                        : "هل أنت متأكد من إغلاق خط السير؟ ستبقى عهدة السيارة كما هي حتى التسوية المخزنية.";

                      setConfirmDialog({
                        isOpen: true,
                        title: "تأكيد إغلاق خط السير",
                        message: message,
                        onConfirm: async () => {
                          try {
                            await authenticatedFetch(`/dispatch/route/${route.id}/status`, {
                              method: "PUT",
                              body: JSON.stringify({ status: "closed" })
                            });
                            setPendingRoutes(prev => prev.filter(r => r.id !== route.id));
                            fetchInitialData();
                            toast.success("تم إغلاق خط السير. عهدة السيارة لم تُصفّر.");
                          } catch (e: unknown) {
                            toast.error(getErrorMessage(e));
                          } finally {
                            setConfirmDialog(d => ({ ...d, isOpen: false }));
                          }
                        }
                      })
                    }}
                    onForceWithdraw={route => {
                      const isAlmostDone = route.shopsRemaining > 0 && route.shopsRemaining <= 5;
                      const message = isAlmostDone
                        ? `تنبيه: باقي ${route.shopsRemaining} محلات فقط! هل أنت متأكد من إيقاف خط السير مؤقتاً وإعادته للانتظار؟`
                        : "هل أنت متأكد من إيقاف المنطقة وإعادتها للانتظار؟";

                      setConfirmDialog({
                        isOpen: true,
                        title: "إيقاف المنطقة",
                        message: message,
                        onConfirm: async () => {
                          try {
                            await authenticatedFetch(`/dispatch/route/${route.id}/status`, {
                              method: "PUT",
                              body: JSON.stringify({ status: "waiting" })
                            });
                                                        fetchInitialData();
                            toast.success("تم تحويل خط السير إلى حالة الانتظار مع بقاء تعيين المندوب والسيارة.");
                          } catch (e: unknown) {
                            toast.error(getErrorMessage(e));
                          } finally {
                            setConfirmDialog(d => ({ ...d, isOpen: false }));
                          }
                        }
                      })
                    }}
                    driverShortagesMap={driverShortagesMap}
                  />
                </div>
              </div>
            </div>
          ) : activeTab === "launch" ? (
            <div key="launch" className="flex flex-col w-full gap-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
              
              {/* +++ الحاوية الأولى: إعدادات الخط (لون صلب bg-slate-50 لتوحيد الخلفية وإخفاء الترقيع) +++ */}
              <div className="relative grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-5 bg-slate-50 p-6 pt-7 rounded-2xl border border-slate-200 shadow-sm transition-all hover:border-[#1e87bb]/30 mt-3">
                <div className="absolute -top-3.5 right-6 bg-gradient-to-r from-[#1e87bb] to-[#166a94] text-white px-4 py-1.5 rounded-lg text-sm font-black flex items-center gap-2 shadow-md z-20">
                  <Rocket className="w-4 h-4" /> إطلاق خط سير جديد
                </div>
                
                {/* +++ تمرير labelBg="bg-slate-50" ليذوب العنوان في خلفية الحاوية تماماً +++ */}
                <CustomSelect labelBg="bg-slate-50" label="المنطقة" options={zones.map(z => ({ id: z.id, label: z.name, scheduleStatus: z.scheduleStatus }))} value={selectedZoneId} onChange={setSelectedZoneId} placeholder="اختر المنطقة" />
                <CustomSelect labelBg="bg-slate-50" label="المندوب" options={drivers.map(d => ({ id: d.id, label: d.name }))} value={selectedDriverId} onChange={setSelectedDriverId} placeholder="اختر المندوب" />
                <CustomSelect labelBg="bg-slate-50" label="السيارة" options={vehicles.map(v => ({ id: v.id, label: v.label }))} value={selectedVehicleId} onChange={setSelectedVehicleId} placeholder="اختر السيارة" />
                <CustomSelect
                  labelBg="bg-slate-50"
                  label="مستودع المصدر"
                  options={warehouses}
                  value={selectedSourceWarehouseId}
                  onChange={setSelectedSourceWarehouseId}
                  placeholder="اختر مستودع المصدر"
                />
              </div>

              {/* +++ الحاوية الثانية: جدول الحمولة (محدود الارتفاع بـ 400px لحل مشكلة المليون منتج) +++ */}
              <div className="relative bg-white rounded-2xl border border-slate-200 flex flex-col shadow-sm mb-4 mt-0">
                <div className="absolute -top-3.5 right-6 bg-gradient-to-r from-[#1e87bb] to-[#166a94] text-white px-4 py-1.5 rounded-lg text-sm font-black flex items-center gap-2 shadow-md z-20">
                  📦 إدخال الحمولة (كرتونة)
                </div>
                
                {/* +++ تقييد الارتفاع الصارم h-[400px] لمنع تمدد الصفحة اللانهائي +++ */}
                <div className="w-full mt-6 h-[400px] overflow-y-auto custom-scrollbar rounded-b-2xl">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 z-10 bg-slate-50/90 backdrop-blur-md shadow-sm border-b border-slate-200">
                      <tr className="text-slate-500 text-xs uppercase">
                        <th className="text-start py-3 px-6 font-extrabold w-2/3">
                          <div className="flex flex-col md:flex-row md:items-center gap-4">
                            <span>المنتج</span>
                            <div className="relative font-normal flex-1 max-w-sm">
                              <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                              <input
                                type="search"
                                placeholder="ابحث عن منتج (مثال: لولو شيبس)..."
                                value={productSearch}
                                onChange={(e) => setProductSearch(e.target.value)}
                                className="w-full pl-4 pr-9 py-1.5 text-xs border border-slate-200 rounded-lg outline-none focus:border-[#1e87bb] bg-white transition-all shadow-sm"
                              />
                            </div>
                          </div>
                        </th>
                        <th className="text-center py-3 px-6 font-extrabold relative">
                          {/* +++ سنترة الكلمة فوق العدادات بالضبط +++ */}
                          <span className="block w-full text-center">الكمية (كرتونة)</span>
                          {/* +++ زر التصفير تم نقله لأقصى اليسار ليفسح المجال للسنترة المطلقة +++ */}
                          <button onClick={() => setPreloadQuantities({})} className="absolute left-4 top-1/2 -translate-y-1/2 text-[10px] font-bold text-red-500 hover:text-red-700 flex items-center gap-1 bg-red-50 hover:bg-red-100 px-2.5 py-1.5 rounded-md transition-colors border border-red-100 shadow-sm shrink-0">
                            <Eraser className="w-3.5 h-3.5" /> تصفير الحمولة
                          </button>
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {products
                        .filter(prod => {
                          // +++ خوارزمية البحث المرن (Tokenized Search) +++
                          if (!productSearch.trim()) return true;
                          const searchTokens = productSearch.toLowerCase().trim().split(/\s+/);
                          return searchTokens.every(token => prod.name.toLowerCase().includes(token));
                        })
                        .map(prod => (
                        <tr key={prod.id} className="hover:bg-slate-50 transition-colors">
                          <td className="py-3 px-6 font-bold text-slate-800 text-base">{prod.name}</td>
                          <td className="py-3 px-6">
                            <div className="flex justify-center">
                              <QuantityInput value={preloadQuantities[prod.id] ?? 0} onChange={n => setPreloadQuantities(p => ({ ...p, [prod.id]: n }))} />
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* +++ الزر: تصغيره وتنسيقه بالأسفل +++ */}
              <div className="flex justify-end mb-8">
                <button
                  onClick={handleDispatchRoute}
                  className="bg-gradient-to-r from-[#1e87bb] to-[#166a94] hover:opacity-90 text-white px-8 py-3 rounded-xl text-sm font-black shadow-lg transition-all active:scale-[0.98] flex items-center justify-center gap-2 w-full md:w-auto min-w-[250px]"
                >
                  <Rocket className="w-5 h-5" /> اعتماد وإطلاق خط السير
                </button>
              </div>

            </div>
          ) : (
            <div key="zones" className="flex gap-4 h-full flex-1 min-h-0 w-full mt-[4px]">
              <div className="w-[29%] flex flex-col gap-4 min-h-0">
                <div className="bg-white rounded-2xl border border-slate-200 flex flex-col h-full shadow-sm">
                  <div className="p-4 border-b border-slate-100 flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                      <h2 className="font-bold text-slate-800">المناطق ({zones.length})</h2>
                      <div className="flex items-center gap-2">
                        <button onClick={() => { fetchArchivedZones(); setIsZoneRecycleBinOpen(true); }} className="text-[10px] font-bold text-slate-500 border border-slate-200 px-2 py-1 rounded-lg hover:bg-slate-50 transition-colors">🗑️ الأرشيف</button>
                        <button onClick={() => { setEditingZoneId(null); setZoneFormName(""); setIsZoneModalOpen(true); }} className="text-[10px] font-bold text-[#1e87bb] border border-[#1e87bb]/20 px-2 py-1 rounded-lg hover:bg-blue-50 transition-colors">[+ منطقة جديدة]</button>
                      </div>
                    </div>
                    <div className="relative">
                      <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                      <input type="search" value={zoneSearchQueryMain} onChange={e => setZoneSearchQueryMain(e.target.value)} placeholder="بحث عن منطقة..." className="w-full rounded-xl border border-slate-200 bg-slate-50 pr-9 pl-4 py-2 text-xs focus:ring-2 focus:ring-[#1e87bb]/20 outline-none" />
                    </div>
                  </div>
                  <div className="flex-1 overflow-y-auto p-2 space-y-1">
                    {zones.filter(z => z.name.toLowerCase().includes(zoneSearchQueryMain.toLowerCase())).map(zone => (
                      <div key={zone.id} onClick={() => setSelectedZoneIdForZones(zone.id)} className={`p-3 rounded-xl cursor-pointer flex items-center justify-between transition-all group ${selectedZoneIdForZones === zone.id ? "bg-emerald-50 text-[#1e87bb] font-bold shadow-sm" : "text-slate-600 hover:bg-slate-50"}`}><div className="flex flex-col min-w-0">
                        <span className="flex items-center gap-2">
                          {zone.name}
                          {(!zone.startDate || !zone.intervalDays) && (
                            <span title="تنبيه: لم يتم ضبط إعدادات الجدولة لهذه المنطقة" className="text-amber-500 bg-amber-50 rounded-full p-0.5 animate-pulse cursor-help"><AlertCircle className="w-3.5 h-3.5" /></span>
                          )}
                        </span>
                        <p className="text-[10px] mt-1 flex items-center gap-1">
                          <span className={zone.dateColor || "text-slate-400"}>
                            {zone.intervalDays ? `كل ${zone.intervalDays} يوم` : "غير مجدول"}
                            {zone.startDate ? ` (${zone.startDate})` : ""}
                          </span>
                          <span className="text-slate-300">•</span>
                          <span className="text-[#1e87bb] font-bold">{zone.shopsCount || 0} محلات</span>
                        </p>
                      </div><div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"><button onClick={e => { e.stopPropagation(); setZoneFormName(zone.name); setEditingZoneId(zone.id); setIsZoneModalOpen(true); }} className="p-1 hover:bg-white rounded-md text-slate-400 hover:text-[#1e87bb]"><Pencil className="w-3.5 h-3.5" /></button><button onClick={e => { e.stopPropagation(); setSelectedZoneIdForZones(zone.id); setSchedulingType("local"); setSchedulingForm({ frequency: frequencyFromIntervalDays(zone.intervalDays), startDate: zone.startDate }); setCustomDays(zone.intervalDays && ![7, 14, 30].includes(zone.intervalDays) ? zone.intervalDays : 14); setIsSchedulingModalOpen(true); }} className="p-1 hover:bg-white rounded-md text-slate-400 hover:text-[#1e87bb]"><Calendar className="w-3.5 h-3.5" /></button><button
                        onClick={e => {
                          e.stopPropagation();
                          setZoneToKill(zone);
                          setConfirmName("");
                          setIsSuicideModalOpen(true);
                        }}
                        className="p-1 hover:bg-white rounded-md text-slate-400 hover:text-red-500"
                        title="أرشفة المنطقة بمسح شامل (سوبر أدمن)"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button></div></div>))}</div>
                </div>
              </div>

              {/* +++ تم وضع قائمة المحلات ثانياً (على اليسار في RTL) وتوسيع عرضها لـ 75% +++ */}
              <div className="w-[75%] flex flex-col gap-4 min-h-0">
                <div className="bg-white rounded-2xl border border-slate-200 flex flex-col h-full shadow-sm relative">
                  <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between shrink-0"><div className="flex items-center gap-4"><h2 className="text-lg font-bold text-slate-800">المحلات</h2><div className="relative"><Search className="absolute end-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" /><input type="search" value={shopSearchQuery} onChange={e => setShopSearchQuery(e.target.value)} placeholder="بحث..." className="rounded-xl border border-slate-200 bg-slate-50 pe-9 ps-4 py-2 text-sm focus:ring-2 focus:ring-[#1e87bb]/20 outline-none w-80 transition-all" /></div></div><div className="flex items-center gap-3">{isEditMode ? (<><button onClick={handleCancelReorder} disabled={isSaving} className="px-4 py-2.5 rounded-xl text-sm font-bold flex items-center gap-2 transition-all shadow-sm border border-slate-200 text-slate-600 hover:bg-red-50 hover:text-red-600 hover:border-red-200 disabled:opacity-50"><XCircle className="w-4 h-4" /> إلغاء</button><button onClick={handleSaveReorder} disabled={isSaving || !hasUnsavedChanges} className={`px-4 py-2.5 rounded-xl text-sm font-bold flex items-center gap-2 transition-all shadow-sm ${hasUnsavedChanges ? 'bg-emerald-500 hover:bg-emerald-600 text-white' : 'bg-slate-100 text-slate-400 cursor-not-allowed'} disabled:opacity-60`}>{isSaving ? <><Loader2 className="w-4 h-4 animate-spin" /> جاري الحفظ...</> : <><Save className="w-4 h-4" /> حفظ</>}</button></>) : (<button onClick={() => { savedShopsRef.current = shops; setIsEditMode(true); }} className="px-4 py-2.5 rounded-xl text-sm font-bold flex items-center gap-2 transition-all shadow-sm border border-slate-200 text-slate-600 hover:bg-slate-50"><Pencil className="w-4 h-4" />تعديل</button>)}<button
                    onClick={() => setShowRecycleBin(true)}
                    className="p-2.5 rounded-xl border border-slate-200 text-slate-500 hover:bg-slate-50 shadow-sm transition-all hover:text-blue-600"
                    title="فتح أرشيف المحلات المؤرشفة"
                  >
                    <Archive className="w-5 h-5" />
                  </button><button onClick={() => { setEditingShopId(null); setShopForm({ name: "", owner: "", phone: "", mapLink: "", zoneId: selectedZoneIdForZones, initialDebt: 0, maxDebtLimit: 0 }); setIsShopModalOpen(true); }} className="bg-[#1e87bb] hover:bg-[#0f766e] text-white px-4 py-2.5 rounded-xl text-sm font-bold flex items-center gap-2 shadow-sm transition-colors"><Plus className="w-4 h-4" /> إضافة محل</button></div></div>
                  <ShopTable shops={shopsInSelectedZone} zones={zones} isEditMode={isEditMode} selectedShopIds={selectedShopIds} allFilteredShops={shopSearchQuery.trim() ? shopsInSelectedZone : null} selectedZoneIdForZones={selectedZoneIdForZones} onToggleSelectAll={() => setSelectedShopIds(selectedShopIds.length === shopsInSelectedZone.length ? [] : shopsInSelectedZone.map(s => s.id))} onToggleSelectShop={id => setSelectedShopIds(prev => prev.includes(id) ? prev.filter(sid => sid !== id) : [...prev, id])} onSequenceChange={(id, n) => { const list = [...shopsInSelectedZone]; const from = list.findIndex(s => s.id === id); const to = Math.max(0, Math.min(n - 1, list.length - 1)); const [item] = list.splice(from, 1); list.splice(to, 0, item); const reordered = list.map((s, i) => ({ ...s, sequence: i + 1 })); setShops(prev => prev.map(s => { if (s.zoneId !== selectedZoneIdForZones || s.archived) return s; return reordered.find(r => r.id === s.id) || s; })); setHasUnsavedChanges(true); }} onEditShop={s => { setShopForm({ ...s }); setEditingShopId(s.id); setIsShopModalOpen(true); }} onArchiveShop={id => {
                    if (isEditMode) {
                      // +++ الكي الجراحي: استخدام نافذة النظام الموحدة بدلاً من نافذة المتصفح البدائية +++
                      setConfirmDialog({
                        isOpen: true,
                        title: "تأكيد الإخفاء",
                        message: "هل أنت متأكد من رغبتك في إخفاء هذا المحل مؤقتاً؟",
                        onConfirm: () => {
                          setShops(prev => prev.map(s => s.id === id ? { ...s, archived: true } : s));
                          setZones(prev => sortZones(prev.map(z => z.id === shops.find(s => s.id === id)?.zoneId ? { ...z, shopsCount: Math.max(0, (z.shopsCount || 0) - 1) } : z)));
                          setHasUnsavedChanges(true);
                          setConfirmDialog(d => ({ ...d, isOpen: false }));
                          toast.info("تم إخفاء المحل محلياً. اضغط 'حفظ التعديلات' لتأكيد النقل للأرشيف.");
                        }
                      });
                    } else {
                      // الأرشفة الفورية العادية إذا لم يكن في وضع التعديل
                      setConfirmDialog({
                        isOpen: true,
                        title: "تأكيد الأرشفة",
                        message: "هل تريد أرشفة هذا المحل؟",
                        onConfirm: async () => {
                          try {
                            await authenticatedFetch("/dispatch/shops/bulk_update", { method: "PUT", body: JSON.stringify([{ id, archived: true }]) });
                            setShops(prev => prev.map(s => s.id === id ? { ...s, archived: true } : s));
                            fetchInitialData();
                            toast.success("تم أرشفة المحل بنجاح");
                          } catch (err: unknown) { toast.error("خطأ في الأرشفة: " + getErrorMessage(err)); }
                          finally { setConfirmDialog(d => ({ ...d, isOpen: false })); }
                        }
                      });
                    }
                  }} onDragStart={(e, id) => e.dataTransfer.setData("shopId", id)} onDrop={(e, targetId) => { const draggedId = e.dataTransfer.getData("shopId"); if (draggedId === targetId) return; const list = [...shopsInSelectedZone]; const from = list.findIndex(s => s.id === draggedId); const to = list.findIndex(s => s.id === targetId); const [item] = list.splice(from, 1); list.splice(to, 0, item); const reordered = list.map((s, i) => ({ ...s, sequence: i + 1 })); setShops(prev => prev.map(s => { if (s.zoneId !== selectedZoneIdForZones || s.archived) return s; return reordered.find(r => r.id === s.id) || s; })); setHasUnsavedChanges(true); }} />
                  <AnimatePresence>{isEditMode && selectedShopIds.length > 0 && (<motion.div initial={{ opacity: 0, y: 50, x: "-50%" }} animate={{ opacity: 1, y: 0, x: "-50%" }} exit={{ opacity: 0, y: 50, x: "-50%" }} className="absolute bottom-6 left-1/2 -translate-x-1/2 z-20"><div className="bg-slate-900/90 backdrop-blur border border-slate-700 px-6 py-3 rounded-full shadow-2xl flex items-center gap-6 whitespace-nowrap text-white"><p className="text-sm font-bold">تحديد <span className="text-amber-400">{selectedShopIds.length}</span> محلات</p><div className="w-px h-6 bg-slate-700" /><div className="flex items-center gap-2"><button onClick={() => setIsBulkTransferModalOpen(true)} className="bg-[#1e87bb] text-white px-4 py-2 rounded-xl text-xs font-bold hover:bg-[#166a94] flex items-center gap-2 transition-all"><RotateCcw className="w-3.5 h-3.5" /> نقل 🔄</button><button onClick={() => setConfirmDialog({ isOpen: true, title: "أرشفة المحلات", message: `أرشفة ${selectedShopIds.length} محلات؟`, onConfirm: async () => { try { const payload = selectedShopIds.map(id => ({ id, archived: true })); await authenticatedFetch("/dispatch/shops/bulk_update", { method: "PUT", body: JSON.stringify(payload) }); setShops(prev => prev.map(s => selectedShopIds.includes(s.id) ? { ...s, archived: true } : s)); setSelectedShopIds([]); fetchInitialData(); toast.success("تم أرشفة المحلات بنجاح"); } catch (err: unknown) { toast.error("خطأ في الأرشفة: " + getErrorMessage(err)); } finally { setConfirmDialog(d => ({ ...d, isOpen: false })); } } })} className="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-2 transition-all"><Trash2 className="w-3.5 h-3.5" /> أرشفة 🗑️</button></div><button onClick={() => setSelectedShopIds([])} className="text-slate-400 hover:text-slate-200"><X className="w-4 h-4" /></button></div></motion.div>)}</AnimatePresence>
                  <div className="p-4 bg-slate-50 border-t border-slate-100 shrink-0">
                    <button onClick={() => setIsBulkImportModalOpen(true)} className="w-full rounded-xl border-2 border-dashed border-slate-200 bg-white p-4 flex items-center justify-center gap-3 hover:border-[#1e87bb] hover:bg-slate-50 transition-all group shadow-sm">
                      <Upload className="w-6 h-6 text-slate-400 group-hover:text-[#1e87bb]" />
                      <div className="text-start">
                        <p className="text-base font-bold text-slate-700 group-hover:text-[#1e87bb]">استيراد المحلات الذكي (Excel / Paste)</p>
                        <p className="text-xs text-slate-500">اضغط هنا لفتح نافذة الاستيراد واختيار المنطقة</p>
                      </div>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </>
      </div>

      <ShortageModal
        isOpen={isShortageModalOpen}
        onClose={handleCloseShortageModal}
        zones={zones}
        activeShops={activeShops}
        shortageZoneId={shortageZoneId}
        shortageShopId={shortageShopId}
        onZoneChange={id => { setShortageZoneId(id); setShortageShopId(""); }}
        onShopChange={id => { setShortageShopId(id); }}
        products={products}
        newShortage={newShortage}
        onNewShortageChange={setNewShortage}
        shortageDraft={shortageDraft}
        onAddProductToDraft={handleAddProductToDraft}
        onRemoveProductFromDraft={idx => setShortageDraft(p => p.filter((_, i) => i !== idx))}
        onUpdateDraftQty={(idx, qty) => setShortageDraft(p => p.map((d, i) => i === idx ? { ...d, quantity: qty } : d))}
        onClearDraft={() => setShortageDraft([])}
        onConfirmShortages={handleAddShortage}
        shortages={shortages}
        drivers={drivers}
        shortageDriverId={shortageDriverId}
        onDriverChange={setShortageDriverId}
        editingShortageIds={editingShortageIds}
        onCancelEdit={() => { setShortageDraft([]); setEditingShortageIds([]); setShortageZoneId(""); setShortageShopId(""); setShortageDriverId(""); }}
        onDeleteShortage={id => setConfirmDialog({ isOpen: true, title: "تأكيد الحذف", message: "هل أنت متأكد من حذف هذا الطلب نهائياً؟", onConfirm: async () => { try { await authenticatedFetch(`/dispatch/shortages/${id}`, { method: "DELETE" }); setShortages(prev => prev.filter(s => s.id !== id)); toast.success("تم حذف الطلب بنجاح"); } catch (e: unknown) { toast.error("خطأ في الحذف: " + getErrorMessage(e)); } finally { setConfirmDialog(d => ({ ...d, isOpen: false })); } } })}
        onDeleteShortageGroup={handleDeleteShortageGroup}
        onEditShortageGroup={handleEditShortageGroup}
      />
      <ScheduleModal isOpen={isSchedulingModalOpen} onClose={() => { setIsSchedulingModalOpen(false); setBulkZoneSearch(""); }} schedulingType={schedulingType} zones={zones} selectedZoneIdForZones={selectedZoneIdForZones} bulkZoneSearch={bulkZoneSearch} onBulkZoneSearchChange={setBulkZoneSearch} selectedBulkZoneIds={selectedBulkZoneIds} onToggleBulkZoneSelection={id => setSelectedBulkZoneIds(prev => prev.includes(id) ? prev.filter(bid => bid !== id) : [...prev, id])} onToggleAllBulkZones={() => { const filtered = zones.filter(z => z.name.toLowerCase().includes(bulkZoneSearch.toLowerCase())).map(z => z.id); setSelectedBulkZoneIds(prev => filtered.every(id => prev.includes(id)) ? prev.filter(id => !filtered.includes(id)) : Array.from(new Set([...prev, ...filtered]))); }} schedulingForm={schedulingForm} onSchedulingFormChange={setSchedulingForm} customDays={customDays} onCustomDaysChange={setCustomDays} onUpdateScheduling={handleUpdateScheduling} />
      <RouteManagementModal
        isOpen={isRouteModalOpen}
        onClose={() => setIsRouteModalOpen(false)}
        routeModalType={routeModalType}
        activeRoute={activeRoute}
        drivers={drivers}
        transferDriverId={transferDriverId}
        onTransferDriverChange={setTransferDriverId}
        vehicles={vehicles}
        selectedVehicleId={selectedVehicleId}
        onVehicleChange={setSelectedVehicleId}
        products={products}
        preloadQuantities={preloadQuantities}
        onPreloadQuantitiesChange={setPreloadQuantities}
        onClearInventory={() => setConfirmDialog({
          isOpen: true,
          title: "تأكيد تصفير هدف الحمولة",
          message: "هل تريد جعل الكمية المستهدفة صفراً لكل أصناف الحمولة الحالية؟",
          onConfirm: () => {
            setPreloadQuantities((current) =>
              Object.fromEntries(Object.keys(current).map((id) => [id, 0]))
            );
            setConfirmDialog(d => ({ ...d, isOpen: false }));
          }
        })}
        onConfirmAction={handleConfirmRouteAction}
      />
      <ShopFormModal isOpen={isShopModalOpen} onClose={() => setIsShopModalOpen(false)} editingShopId={editingShopId} shopForm={shopForm} onShopFormChange={setShopForm} zones={zones} onSave={handleSaveShop} />
      <RecycleBinModal
        isOpen={showRecycleBin}
        onClose={() => setShowRecycleBin(false)}
        recycleSearchQuery={recycleSearchQuery}
        onRecycleSearchQueryChange={setRecycleSearchQuery}
        filteredRecycleBin={filteredRecycleBin}
        zones={[...zones, ...archivedZones]}
        onRestoreShop={async (id) => {
          const shopToRestore = shops.find(s => s.id === id);
          const isZoneActive = zones.some(z => z.id === shopToRestore?.zoneId);

          if (!isZoneActive && shopToRestore) {
            setRestorePromptShop(shopToRestore); // تفعيل النافذة المتطورة
            return;
          }

          try {
            await authenticatedFetch("/dispatch/shops/bulk_update", {
              method: "PUT",
              body: JSON.stringify([{ id, archived: false }])
            });
            setShops(prev => prev.map(s => s.id === id ? { ...s, archived: false } : s));
            setZones(prev => sortZones(prev.map(z => z.id === archivedShops.find(s => s.id === id)?.zoneId ? { ...z, shopsCount: (z.shopsCount || 0) + 1 } : z)));
            fetchInitialData();
            toast.success("تم استعادة المحل بنجاح");
          } catch (err: unknown) { toast.error(getErrorMessage(err)); }
        }}
      />
      <BulkTransferModal isOpen={isBulkTransferModalOpen} onClose={() => setIsBulkTransferModalOpen(false)} selectedShopIds={selectedShopIds} zones={zones} selectedZoneIdForZones={selectedZoneIdForZones} targetTransferZoneId={targetTransferZoneId} onTargetTransferZoneChange={setTargetTransferZoneId} onConfirm={async () => { if (!targetTransferZoneId) return toast.error("⚠️ اختر المنطقة"); try { const payload = selectedShopIds.map(id => ({ id, zoneId: targetTransferZoneId, sequence: 999, archived: false })); await authenticatedFetch("/dispatch/shops/bulk_update", { method: "PUT", body: JSON.stringify(payload) }); setShops(prev => prev.map(s => selectedShopIds.includes(s.id) ? { ...s, zoneId: targetTransferZoneId, sequence: 999 } : s)); setSelectedShopIds([]); setIsBulkTransferModalOpen(false); setTargetTransferZoneId(""); fetchInitialData(); toast.success("تم نقل المحلات بنجاح"); } catch (err: unknown) { toast.error("خطأ في النقل: " + getErrorMessage(err)); } }} />
      {/* +++ نافذة تعديل الحمولة +++ */}
      <AdjustInventoryModal
        isOpen={isInventoryModalOpen}
        onClose={() => setIsInventoryModalOpen(false)}
        route={inventoryRoute}
        onSuccess={fetchInitialData}
      />

      {/* +++ رادار الحوالات المصفح +++ */}
      <TransfersRadarModal
        isOpen={isRadarModalOpen}
        onClose={() => setIsRadarModalOpen(false)}
        route={radarRoute}
      />

      <ZoneModal isOpen={isZoneModalOpen} onClose={() => { setIsZoneModalOpen(false); setZoneFormName(""); setEditingZoneId(null); }} editingZoneId={editingZoneId} zoneFormName={zoneFormName} onZoneFormNameChange={setZoneFormName} onSave={handleSaveZone} />
      <PostponedRoutesModal isOpen={isShowPostponedModalOpen} onClose={() => setIsShowPostponedModalOpen(false)} routes={pendingRoutes.filter(r => r.status === "postponed")} drivers={drivers} onUpdateDriver={(id, drvId) => { const d = drivers.find(drv => drv.id === drvId); setPendingRoutes(prev => prev.map(r => r.id === id ? { ...r, driverId: drvId, driverName: d?.name || "" } : r)); }} onRestore={async (id) => { try { const route = pendingRoutes.find(r => r.id === id); await authenticatedFetch(`/dispatch/route/${id}/status`, { method: "PUT", body: JSON.stringify(
          route?.sessionBound
            ? { status: "waiting" }
            : { status: "waiting", driverId: route?.driverId }
        ) }); setPendingRoutes(prev => prev.map(r => r.id === id ? { ...r, status: "waiting" } : r)); toast.success("تم استعادة المنطقة وتعيين المندوب بنجاح"); } catch (e: unknown) { toast.error(getErrorMessage(e)); } }} />
      <ZoneRecycleBinModal isOpen={isZoneRecycleBinOpen} onClose={() => setIsZoneRecycleBinOpen(false)} recycleSearchQuery={zoneRecycleSearchQuery} onRecycleSearchQueryChange={setZoneRecycleSearchQuery} filteredRecycleBin={filteredZoneRecycleBin} onRestoreZone={handleRestoreZone} />
      <ShopBulkImportModal
        isOpen={isBulkImportModalOpen}
        onClose={() => setIsBulkImportModalOpen(false)}
        zones={zones}
        existingShops={shops}
        onSuccess={fetchInitialData}
      />
      {confirmDialog.isOpen && (
        <Modal
          isOpen={confirmDialog.isOpen}
          onClose={() => setConfirmDialog({ ...confirmDialog, isOpen: false })}
          title={confirmDialog.title}
          footer={
            <div className="flex gap-2 w-full">
              <button onClick={() => setConfirmDialog({ ...confirmDialog, isOpen: false })} className="px-6 py-2 text-slate-500 font-bold hover:bg-slate-100 rounded-xl transition-colors">إلغاء</button>
              <button onClick={confirmDialog.onConfirm} className="flex-1 bg-[#1e87bb] text-white py-2 rounded-xl font-bold hover:bg-[#166a94] transition-colors shadow-lg">تأكيد</button>
            </div>
          }
        >
          <div className="space-y-4">
            <p className={`font-bold ${confirmDialog.message.includes('تنبيه') ? 'text-red-600 text-base leading-relaxed' : 'text-sm text-slate-600'}`}>
              {confirmDialog.message}
            </p>
          </div>
        </Modal>
      )}

      {duplicateWarning?.show && (
        <Modal
          isOpen={duplicateWarning.show}
          onClose={() => setDuplicateWarning(null)}
          title="⚠️ تحذير: اكتشاف تطابق"
          footer={
            <div className="flex gap-2 w-full">
              <button onClick={() => setDuplicateWarning(null)} className="px-6 py-2 text-slate-500 font-bold hover:bg-slate-100 rounded-xl transition-colors">إلغاء</button>
              <button onClick={forceSaveShop} className="flex-1 bg-red-500 text-white py-2 rounded-xl font-bold hover:bg-red-600 transition-colors shadow-lg">تخطي التحذير والحفظ</button>
            </div>
          }
        >
          <div className="space-y-4">
            <p className="text-sm text-slate-600">تم العثور على محل ببيانات مشابهة. يرجى مراجعة التطابق قبل الحفظ.</p>
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-red-50 p-4 rounded-xl border border-red-200">
                <h4 className="text-sm font-bold text-red-700 mb-2 border-b border-red-200 pb-2">البيانات المدخلة حديثاً</h4>
                <p className="font-bold text-slate-800 text-sm">{duplicateWarning.localState.name}</p>
                <p className="text-xs text-slate-500 mt-1" dir="ltr">{duplicateWarning.localState.phone}</p>
              </div>
              <div className="bg-emerald-50 p-4 rounded-xl border border-emerald-200">
                <h4 className="text-sm font-bold text-emerald-700 mb-2 border-b border-emerald-200 pb-2">المحل الموجود مسبقاً</h4>
                <p className="font-bold text-slate-800 text-sm">{duplicateWarning.shopData.name}</p>
                <p className="text-xs text-slate-600 mt-1">المالك: {duplicateWarning.shopData.owner}</p>
                <p className="text-xs text-slate-600 mt-1">المنطقة: <span className="font-bold text-[#1e87bb]">{duplicateWarning.shopData.zone_name}</span></p>
                <p className="text-xs text-slate-500 mt-1" dir="ltr">{duplicateWarning.shopData.phone}</p>
              </div>
            </div>
          </div>
        </Modal>
      )}

      {unsavedTabPrompt && (
        <Modal
          isOpen={!!unsavedTabPrompt}
          onClose={() => setUnsavedTabPrompt(null)}
          title="⚠️ تعديلات غير محفوظة"
          footer={
            <div className="flex gap-2 w-full">
              <button onClick={() => setUnsavedTabPrompt(null)} className="px-4 py-2 text-slate-500 font-bold hover:bg-slate-100 rounded-xl transition-colors">إلغاء</button>
              <button
                onClick={() => {
                  handleCancelReorder();
                  setActiveTab(unsavedTabPrompt);
                  setUnsavedTabPrompt(null);
                }}
                className="flex-1 bg-red-50 text-red-600 border border-red-200 py-2 rounded-xl font-bold hover:bg-red-100 transition-colors"
              >
                تجاهل وخروج
              </button>
              <button
                onClick={async () => {
                  const success = await handleSaveReorder();
                  if (success) {
                    setActiveTab(unsavedTabPrompt);
                    setUnsavedTabPrompt(null);
                  }
                }}
                className="flex-1 bg-emerald-500 text-white py-2 rounded-xl font-bold hover:bg-emerald-600 transition-colors shadow-lg"
              >
                حفظ وخروج
              </button>
            </div>
          }
        >
          <div className="space-y-4">
            <p className="text-sm text-slate-600 font-bold">لديك تعديلات على ترتيب المحلات لم تقم بحفظها. ماذا تريد أن تفعل قبل الانتقال؟</p>
          </div>
        </Modal>
      )}

      {restorePromptShop && (
        <Modal
          isOpen={!!restorePromptShop}
          onClose={() => setRestorePromptShop(null)}
          title="⚠️ المنطقة مؤرشفة"
          footer={
            <div className="flex gap-2 w-full">
              <button onClick={() => setRestorePromptShop(null)} className="px-4 py-2 text-slate-500 font-bold hover:bg-slate-100 rounded-xl transition-colors">إلغاء</button>
              <button
                onClick={() => {
                  setRestorePromptShop(null);
                  setSelectedShopIds([restorePromptShop.id]);
                  setIsBulkTransferModalOpen(true);
                }}
                className="flex-1 bg-[#1e87bb] text-white py-2 rounded-xl font-bold hover:bg-[#156a94] transition-colors"
                title="نقل المحل لمنطقة أخرى نشطة قبل تفعيله"
              >
                نقل لمنطقة نشطة 🔄
              </button>
              <button
                onClick={async () => {
                  try {
                    await authenticatedFetch(
                      `/dispatch/zones/${restorePromptShop.zoneId}/restore`,
                      {
                        method: "PUT",
                        body: JSON.stringify({
                          mode: "zone_only",
                        }),
                      }
                    );

                    await authenticatedFetch("/dispatch/shops/bulk_update", {
                      method: "PUT",
                      body: JSON.stringify([
                        {
                          id: restorePromptShop.id,
                          archived: false,
                        },
                      ]),
                    });
                    setShops(prev => prev.map(s => s.id === restorePromptShop.id ? { ...s, archived: false } : s));
                    setRestorePromptShop(null);
                    toast.success("تم استعادة المنطقة والمحل بنجاح ✅");
                  } catch (e: unknown) { toast.error("خطأ: " + getErrorMessage(e)); }
                }}
                className="flex-1 bg-emerald-500 text-white py-2 rounded-xl font-bold hover:bg-emerald-600 transition-colors"
              >
                استعادة المنطقة والمحل ♻️
              </button>
            </div>
          }
        >
          <div className="space-y-3">
            <p className="text-sm font-bold text-slate-700">
              المحل <span className="text-[#1e87bb]">({restorePromptShop.name})</span> كان مسجلاً في منطقة تم أرشفتها لاحقاً.
            </p>
            <p className="text-xs text-slate-500">لا يمكن استعادة المحل إلى العدم. يرجى اختيار الإجراء المناسب:</p>
          </div>
        </Modal>
      )}

      {/* +++ مودال أرشفة المنطقة بمسح شامل (سوبر أدمن) +++ */}
      <Modal
        isOpen={isSuicideModalOpen}
        onClose={() => setIsSuicideModalOpen(false)}
        title={`⚠️ أرشفة منطقة: ${zoneToKill?.name}`}
        footer={
          <div className="flex gap-2 w-full">
            <button onClick={() => setIsSuicideModalOpen(false)} className="px-6 py-2 text-slate-500 font-bold hover:bg-slate-100 rounded-xl">تراجع</button>
            <button
              disabled={confirmName !== zoneToKill?.name}
              onClick={async () => {
                try {
                  await authenticatedFetch(`/dispatch/zones/${zoneToKill?.id}`, { method: "DELETE" });
                  setZones(prev => prev.filter(z => z.id !== zoneToKill?.id));
                  fetchInitialData();
                  setIsSuicideModalOpen(false);
                  toast.success(`تم أرشفة المنطقة (${zoneToKill?.name}) وكل محلاتها بنجاح ✅`);
                } catch (err: unknown) { toast.error(getErrorMessage(err)); }
              }}
              className="flex-1 bg-red-600 text-white py-2 rounded-xl font-bold hover:bg-red-700 disabled:opacity-30 transition-all shadow-lg"
            >
              تأكيد المسح الشامل 🧨
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <div className="bg-red-50 border-r-4 border-red-500 p-4">
            <p className="text-sm text-red-800 font-bold">هذا الإجراء سيؤدي لأرشفة المنطقة وجميع المحلات التابعة لها ({zoneToKill?.shopsCount || 0} محل) فوراً.</p>
          </div>
          <p className="text-xs text-slate-600">لتأكيد هذه العملية الخطيرة، يرجى كتابة اسم المنطقة <span className="font-black text-red-600">({zoneToKill?.name})</span> في الأسفل:</p>
          <input
            value={confirmName}
            onChange={(e) => setConfirmName(e.target.value)}
            className="w-full rounded-xl border-2 border-red-100 p-3 text-center font-black text-slate-800 focus:border-red-500 outline-none transition-all"
            placeholder="اكتب اسم المنطقة هنا..."
          />
        </div>
      </Modal>
    </div>
  );
}

