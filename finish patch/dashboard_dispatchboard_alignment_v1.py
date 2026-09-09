from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOARD = ROOT / "dashboard" / "src" / "pages" / "DispatchBoard.tsx"
BACKEND = ROOT / "wa_backend" / "api" / "dispatch.py"


def fail(msg: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {msg}")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"ALREADY_PATCHED={label}")
        return
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected 1 match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"PATCHED={label}")


for path in (BOARD, BACKEND):
    if not path.exists():
        fail(f"Missing required file: {path.relative_to(ROOT)}")


# ------------------------------------------------------------------
# Backend read-contract bug: recycle bin needs archived shops too.
# This endpoint is tenant-scoped and already exposes `archived` in its schema.
# ------------------------------------------------------------------
replace_once(
    BACKEND,
    """    stmt = select(Shop).filter(
    Shop.company_id == current_admin.company_id,
    Shop.is_active == True,
    Shop.is_archived == False
).order_by(nullslast(Shop.sequence.asc()), Shop.id.asc())
""",
    """    stmt = select(Shop).filter(
    Shop.company_id == current_admin.company_id,
    Shop.is_active == True,
).order_by(nullslast(Shop.sequence.asc()), Shop.id.asc())
""",
    "backend_dispatch_shops_include_archived",
)


# ------------------------------------------------------------------
# DispatchBoard shared contracts/helpers
# ------------------------------------------------------------------
replace_once(
    BOARD,
    """import { useAuthFetch } from "@/hooks/useAuthFetch";
// Utils
""",
    """import { useAuthFetch } from "@/hooks/useAuthFetch";

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

type ShopWire = Omit<Shop, "initialDebt" | "maxDebtLimit"> & {
  initialDebt: number | string;
  maxDebtLimit: number | string;
};

const getErrorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : "حدث خطأ غير متوقع";

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
  if (days === 7) return "أسبوعي (مرة في الأسبوع)";
  if (days === 14) return "كل أسبوعين (مرة كل 14 يوم)";
  if (days === 30) return "شهري (مرة في الشهر)";
  return "مخصص";
};

const intervalDaysFromFrequency = (
  frequency: string,
  customDays: number
): number | null => {
  if (frequency === "أسبوعي (مرة في الأسبوع)") return 7;
  if (frequency === "كل أسبوعين (مرة كل 14 يوم)") return 14;
  if (frequency === "شهري (مرة في الشهر)") return 30;
  if (frequency === "مخصص" && Number.isInteger(customDays) && customDays > 0) {
    return customDays;
  }
  return null;
};

// Utils
""",
    "dispatchboard_contract_helpers",
)


# Trust backend company-local schedule status. Do not recompute using browser timezone.
old_sort = """const sortZones = (zones: Zone[]) => {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  return [...zones].map(z => {
    let status = "null";
    let color = "text-slate-400";
    if (z.startDate) {
      const sDate = new Date(z.startDate);
      sDate.setHours(0, 0, 0, 0);
      const diffTime = sDate.getTime() - today.getTime();
      const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

      if (diffDays < 0) { status = "overdue"; color = "text-red-600 font-bold"; }
      else if (diffDays === 0 || diffDays === 1) { status = "soon"; color = "text-emerald-600 font-bold"; } // اليوم وبكرا
      else if (diffDays > 1 && diffDays <= 5) { status = "upcoming"; color = "text-amber-500 font-bold"; } // من يومين لـ 5 أيام
      else { status = "future"; color = "text-slate-700 font-bold"; } // أبعد من هيك
    }
    return { ...z, scheduleStatus: status as import("@/types/dispatch").ScheduleStatus, dateColor: color };
  }).sort((a, b) => {
    const weights: Record<string, number> = { overdue: 4, soon: 3, upcoming: 2, future: 1, null: 0 };
    const wDiff = (weights[b.scheduleStatus] || 0) - (weights[a.scheduleStatus] || 0);
    if (wDiff !== 0) return wDiff;
    if (a.startDate && b.startDate) return new Date(a.startDate).getTime() - new Date(b.startDate).getTime();
    return 0;
  });
};
"""

new_sort = """const sortZones = (zones: Zone[]) => {
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
"""
replace_once(BOARD, old_sort, new_sort, "backend_owned_zone_schedule_status")


# Strict local-storage tab contract.
replace_once(
    BOARD,
    """  // +++  (تجاوز TypeScript): توسيع نوع TabId محلياً ليقبل "launch" +++
  const [activeTab, setActiveTab] = useState<string>(() => localStorage.getItem("activeTab") || "routes");
""",
    """  const [activeTab, setActiveTab] = useState<TabId>(() => {
    const stored = localStorage.getItem("activeTab");
    return isTabId(stored) ? stored : "routes";
  });
""",
    "typed_active_tab",
)

replace_once(
    BOARD,
    """  const [unsavedTabPrompt, setUnsavedTabPrompt] = useState<string | null>(null);
""",
    """  const [unsavedTabPrompt, setUnsavedTabPrompt] = useState<TabId | null>(null);
""",
    "typed_unsaved_tab",
)


# Source warehouse is mandatory in the frozen backend contract.
replace_once(
    BOARD,
    """  const [products, setProducts] = useState<{ id: string; name: string }[]>([]);
  const [pendingRoutes, setPendingRoutes] = useState<PendingRoute[]>([]);
""",
    """  const [products, setProducts] = useState<{ id: string; name: string }[]>([]);
  const [warehouses, setWarehouses] = useState<WarehouseOption[]>([]);
  const [selectedSourceWarehouseId, setSelectedSourceWarehouseId] = useState("");
  const [pendingRoutes, setPendingRoutes] = useState<PendingRoute[]>([]);
""",
    "source_warehouse_state",
)


# Initial-data alignment + stale-selection cleanup.
replace_once(
    BOARD,
    """    authenticatedFetch("/dispatch/init", { signal: controller.signal })
      .then(data => {
        const sorted = sortZones(data.zones || []); setZones(sorted); setDrivers(data.drivers || []); setVehicles(data.vehicles || []); setProducts(data.products || []);

        // +++  (UX): الحفاظ على المنطقة المحددة حالياً، وعدم إجبار المستخدم على العودة لأول القائمة بعد الـ Refresh +++
        if (sorted.length > 0) {
          setSelectedZoneIdForZones(prev => prev ? prev : sorted[0].id);
        }

        if (data.products?.length > 0) setNewShortage({ productName: data.products[0].name, quantity: 1 });
      })
      .catch(err => { if (err.name !== 'AbortError') console.warn("تأخير بسيط في جلب البيانات:", err.message); });
""",
    """    authenticatedFetch("/dispatch/init", { signal: controller.signal })
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
            prev.productName
              ? prev
              : { productName: nextProducts[0].name, quantity: 1 }
          );
        }
      })
      .catch((err: unknown) => {
        if (!(err instanceof Error && err.name === "AbortError")) {
          console.warn("تأخير بسيط في جلب البيانات:", getErrorMessage(err));
        }
      });
""",
    "initial_data_contract",
)

replace_once(
    BOARD,
    """    authenticatedFetch("/dispatch/shops", { signal })
      .then(data => setShops(Array.isArray(data) ? data : []))
      .catch(err => { if (err.name !== 'AbortError') console.error(err); });
""",
    """    authenticatedFetch("/dispatch/shops", { signal })
      .then((data) => setShops(normalizeShops(data)))
      .catch((err: unknown) => {
        if (!(err instanceof Error && err.name === "AbortError")) console.error(err);
      });
""",
    "normalize_dispatch_shops",
)

replace_once(
    BOARD,
    """    // CS-WH-03: Check warehouse lock status on mount
    authenticatedFetch("/warehouse/status", { signal })
      .then((data: any) => setIsWarehouseLocked(data?.status === 'AUDIT_LOCK'))
      .catch(err => { if (err.name !== 'AbortError') console.error(err); });
""",
    """    authenticatedFetch("/warehouse/locations", { signal })
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
          options.some((warehouse) => warehouse.id === prev)
            ? prev
            : (options[0]?.id || "")
        );
      })
      .catch((err: unknown) => {
        if (!(err instanceof Error && err.name === "AbortError")) console.error(err);
      });

    // CS-WH-03: Check warehouse lock status on mount
    authenticatedFetch("/warehouse/status", { signal })
      .then((data) => {
        const status =
          typeof data === "object" && data !== null && "status" in data
            ? String((data as { status: unknown }).status)
            : "";
        setIsWarehouseLocked(status === "AUDIT_LOCK");
      })
      .catch((err: unknown) => {
        if (!(err instanceof Error && err.name === "AbortError")) console.error(err);
      });
""",
    "warehouse_source_and_status_contract",
)


# Realtime: refresh burst coalescing + use latest access token on every reconnect.
old_ws = """  // Step 5.7c: Replace polling with WebSocket for real-time dispatch updates
  useEffect(() => {
    const controller = fetchInitialData();

    // Build WebSocket URL from VITE_API_URL
    const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:5000';
    const token = localStorage.getItem('admin_token');
    // +++ الكي الجراحي: حقن التوكن في الرابط لمنع اختراق الـ WebSocket +++
    const wsUrl = apiUrl.replace(/\\/+$/, '').replace(/^http/, 'ws') + '/ws/dispatch' + (token ? `?token=${token}` : '');

    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let retryCount = 0;

    const connectWS = () => {
      ws = new WebSocket(wsUrl);

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.event) {
            if (data.event === "STALE_HANDSHAKE_WARNING" && data.message) {
              toast.warning(data.message);
            } else if (data.event === "STALE_HANDSHAKE_CRITICAL" && data.message) {
              toast.error(data.message);
            } else if (data.event === "STALE_SESSION_WARNING" && data.message) {
              toast.warning(data.message);
            } else if (data.event === "STALE_SESSION_CRITICAL" && data.message) {
              toast.error(data.message);
            } else if (data.event === "INTEGRITY_ALERT" && data.message) {
              toast.error(data.message);
            }
            authenticatedFetch("/dispatch/active_routes")
              .then(res => setPendingRoutes(Array.isArray(res) ? res : []))
              .catch(() => {});
            authenticatedFetch("/dispatch/shortages")
              .then(res => setShortages(Array.isArray(res) ? res : []))
              .catch(() => {});
            // +++ E-07: تحديث جميع النطاقات والمحلات والمناديب لمنع الـ Split-Brain بين المشرفين +++
            authenticatedFetch("/dispatch/init")
              .then((res: any) => {
                if(res.zones) setZones(sortZones(res.zones));
                if(res.drivers) setDrivers(res.drivers);
                if(res.vehicles) setVehicles(res.vehicles);
              }).catch(() => {});
            authenticatedFetch("/dispatch/shops")
              .then(res => setShops(Array.isArray(res) ? res : []))
              .catch(() => {});
          }
        } catch (err) {
          console.error("WS Parse error", err);
        }
      };

      ws.onclose = () => {
        // +++ الكي الجراحي: إيقاف محاولات الاتصال إذا كان التبويب مخفياً لتوفير موارد متصفح المشرف +++
        if (document.visibilityState === 'hidden') return;
        const backoff = Math.min(1000 * Math.pow(2, retryCount), 30000);
        retryCount++;
        reconnectTimer = setTimeout(connectWS, backoff);
      };
      ws.onopen = () => { retryCount = 0; };
      ws.onerror = () => {}; // التقاط أخطاء الاتصال بصمت لمنع امتلاء الكونسول باللون الأحمر
    };

    connectWS();

    // +++ إعادة تشغيل الـ WebSocket فور عودة المشرف للتبويب إذا كان الاتصال مفصولاً +++
    const handleVisChange = () => {
      if (document.visibilityState === 'visible' && (!ws || ws.readyState === WebSocket.CLOSED)) {
        retryCount = 0;
        connectWS();
      }
    };
    document.addEventListener('visibilitychange', handleVisChange);

    return () => {
      controller.abort();
      clearTimeout(reconnectTimer);
      document.removeEventListener('visibilitychange', handleVisChange);
      if (ws) {
        ws.onclose = null; // Prevent reconnect loop on unmount
        ws.close();
      }
    };
  }, [fetchInitialData, authenticatedFetch]);
"""

new_ws = """  // Realtime dispatch updates: authenticate each reconnect with the latest token
  // and coalesce event bursts into one dashboard refresh.
  useEffect(() => {
    const controller = fetchInitialData();
    const apiUrl = (import.meta.env.VITE_API_URL || "").replace(/\\/+$/, "");

    let ws: WebSocket | undefined;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    let realtimeRefreshController: AbortController | null = null;
    let retryCount = 0;

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

          if (data.event === "STALE_HANDSHAKE_WARNING" && data.message) {
            toast.warning(data.message);
          } else if (data.event === "STALE_HANDSHAKE_CRITICAL" && data.message) {
            toast.error(data.message);
          } else if (data.event === "STALE_SESSION_WARNING" && data.message) {
            toast.warning(data.message);
          } else if (data.event === "STALE_SESSION_CRITICAL" && data.message) {
            toast.error(data.message);
          } else if (data.event === "INTEGRITY_ALERT" && data.message) {
            toast.error(data.message);
          }

          scheduleRealtimeRefresh();
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
      document.removeEventListener("visibilitychange", handleVisChange);
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    };
  }, [fetchInitialData]);
"""
replace_once(BOARD, old_ws, new_ws, "websocket_coalescing_and_latest_token")


# Prevent stale vehicle A inventory from overwriting vehicle B selection.
replace_once(
    BOARD,
    """  useEffect(() => {
    if (selectedVehicleId) {
      authenticatedFetch(`/dispatch/inventory/${selectedVehicleId}`)
        .then(data => { const inv: Record<string, number> = {}; data.forEach((item: any) => { inv[item.product_id] = item.current_quantity; }); setPreloadQuantities(inv); })
        .catch(err => toast.error("خطأ في جلب مخزون المركبة: " + err.message));
    } else setPreloadQuantities({});
  }, [selectedVehicleId]);
""",
    """  useEffect(() => {
    if (!selectedVehicleId) {
      setPreloadQuantities({});
      return;
    }

    const controller = new AbortController();
    authenticatedFetch(`/dispatch/inventory/${selectedVehicleId}`, {
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
      })
      .catch((err: unknown) => {
        if (err instanceof Error && err.name === "AbortError") return;
        toast.error("خطأ في جلب مخزون المركبة: " + getErrorMessage(err));
      });

    return () => controller.abort();
  }, [selectedVehicleId, authenticatedFetch]);
""",
    "vehicle_inventory_race_guard",
)


# Archived zones + restore: no fake local schedule, refresh canonical data.
old_archived = """  const fetchArchivedZones = async () => {
    try {
      const data = await authenticatedFetch("/dispatch/zones/archived");
      setArchivedZones(data.map((z: any) => ({ id: z.id, name: z.name, frequency: "", visitDay: "", startDate: "" })));
    } catch (err: any) {
      toast.error("خطأ في جلب أرشيف المناطق: " + err.message);
    }
  };

  const handleRestoreZone = async (zoneId: string) => {
    try {
      await authenticatedFetch(`/dispatch/zones/${zoneId}/restore`, { method: "PUT" });
      const restored = archivedZones.find(z => z.id === zoneId);
      if (restored) {
        setZones(prev => [...prev, { ...restored, frequency: "أسبوعي", visitDay: "غير محدد", startDate: "", shopsCount: 0 }]); // Using defaults, backend handles the real logic on init
        setArchivedZones(prev => prev.filter(z => z.id !== zoneId));
      }
      toast.success("تم استعادة المنطقة بنجاح");
      if (archivedZones.length <= 1) setIsZoneRecycleBinOpen(false);

      // re-fetch init data to get correct shopsCount and full zone details
      const initData = await authenticatedFetch("/dispatch/init");
      setZones(sortZones(initData.zones));
    } catch (err: any) {
      toast.error("خطأ في الاستعادة: " + err.message);
    }
  };
"""

new_archived = """  const fetchArchivedZones = async () => {
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
            frequency: "",
            visitDay: "",
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
"""
replace_once(BOARD, old_archived, new_archived, "archived_zone_canonical_refresh")


replace_once(
    BOARD,
    """  const handleTabChange = useCallback((tabId: string) => {
""",
    """  const handleTabChange = useCallback((tabId: TabId) => {
""",
    "typed_tab_change",
)


# Route create: explicit source warehouse is mandatory.
replace_once(
    BOARD,
    """  const handleDispatchRoute = () => {
    if (!selectedZoneId || !selectedDriverId || !selectedVehicleId) return toast.error("⚠️ يرجى تحديد المنطقة والمندوب والسيارة");
""",
    """  const handleDispatchRoute = () => {
    if (
      !selectedZoneId ||
      !selectedDriverId ||
      !selectedVehicleId ||
      !selectedSourceWarehouseId
    ) {
      return toast.error("⚠️ يرجى تحديد المنطقة والمندوب والسيارة ومستودع المصدر");
    }
""",
    "route_requires_source_warehouse",
)

replace_once(
    BOARD,
    """        vehicle_id: selectedVehicleId,
        inventory: preloadQuantities // +++ إرسال جرد الحمولة للسيرفر +++
""",
    """        vehicle_id: selectedVehicleId,
        source_location_id: selectedSourceWarehouseId,
        inventory: preloadQuantities
""",
    "route_source_location_payload",
)


# Frozen backend schedule contract: intervalDays + startDate only.
old_schedule = """  const handleUpdateScheduling = async () => {
    const targetIds = schedulingType === "bulk" ? selectedBulkZoneIds : [selectedZoneIdForZones];
    setIsSchedulingModalOpen(false); // +++ UX: إغلاق النافذة فوراً +++

    // +++ E-05: استخدام allSettled لتحديث الواجهة بناءً على النجاح الفعلي فقط لمنع تخريب الجدولة +++
    const results = await Promise.allSettled(targetIds.map(id =>
      authenticatedFetch(`/dispatch/zones/${id}`, {
        method: "PUT",
        body: JSON.stringify({
          frequency: schedulingForm.frequency,
          visitDay: schedulingForm.visitDay,
          startDate: schedulingForm.startDate,
          // +++ الكي الجراحي: إرسال الأيام المخصصة للباك-إند إذا اختار المدير جدولة مخصصة +++
          customDays: schedulingForm.frequency.includes("مخصص") ? customDays : null
        })
      })
    ));

    const successIds = targetIds.filter((_, index) => results[index].status === 'fulfilled');
    const failedCount = targetIds.length - successIds.length;

    if (successIds.length > 0) {
      setZones(prev => sortZones(prev.map(z => successIds.includes(z.id) ? { ...z, ...schedulingForm } : z)));
      toast.success(`تم تحديث إعدادات الجدولة بنجاح لـ ${successIds.length} منطقة`);
    }
    if (failedCount > 0) {
      toast.error(`فشل تحديث ${failedCount} منطقة. يرجى إدخال تاريخ البدء بشكل صحيح.`);
    }
  };
"""

new_schedule = """  const handleUpdateScheduling = async () => {
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
"""
replace_once(BOARD, old_schedule, new_schedule, "numeric_schedule_contract")


# New zone must remain unscheduled until backend schedule call succeeds.
replace_once(
    BOARD,
    """        const newZone = {
          id: String(res.zone_id),
          name: zoneFormName,
          scheduleStatus: null,
          frequency: "أسبوعي",
          visitDay: "السبت",
          startDate: new Date().toISOString().split('T')[0],
          shopsCount: 0
        };
""",
    """        const newZone: Zone = {
          id: String(res.zone_id),
          name: zoneFormName,
          scheduleStatus: "null",
          frequency: "",
          visitDay: "",
          startDate: "",
          intervalDays: null,
          shopsCount: 0,
        };
""",
    "new_zone_unscheduled_truth",
)

replace_once(
    BOARD,
    """        setSchedulingForm({ frequency: newZone.frequency, visitDay: newZone.visitDay, startDate: newZone.startDate });
""",
    """        setSchedulingForm({
          frequency: "أسبوعي (مرة في الأسبوع)",
          visitDay: "السبت",
          startDate: "",
        });
        setCustomDays(14);
""",
    "new_zone_schedule_form_defaults",
)


# Launch UI: explicit warehouse selector.
replace_once(
    BOARD,
    """              <div className="relative grid grid-cols-1 md:grid-cols-3 gap-5 bg-slate-50 p-6 pt-7 rounded-2xl border border-slate-200 shadow-sm transition-all hover:border-[#1e87bb]/30 mt-3">
""",
    """              <div className="relative grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-5 bg-slate-50 p-6 pt-7 rounded-2xl border border-slate-200 shadow-sm transition-all hover:border-[#1e87bb]/30 mt-3">
""",
    "launch_grid_for_source_warehouse",
)

replace_once(
    BOARD,
    """                <CustomSelect labelBg="bg-slate-50" label="السيارة" options={vehicles.map(v => ({ id: v.id, label: v.label }))} value={selectedVehicleId} onChange={setSelectedVehicleId} placeholder="اختر السيارة" />
              </div>
""",
    """                <CustomSelect labelBg="bg-slate-50" label="السيارة" options={vehicles.map(v => ({ id: v.id, label: v.label }))} value={selectedVehicleId} onChange={setSelectedVehicleId} placeholder="اختر السيارة" />
                <CustomSelect
                  labelBg="bg-slate-50"
                  label="مستودع المصدر"
                  options={warehouses}
                  value={selectedSourceWarehouseId}
                  onChange={setSelectedSourceWarehouseId}
                  placeholder="اختر مستودع المصدر"
                />
              </div>
""",
    "launch_source_warehouse_selector",
)


# Zone display no longer relies on legacy visitDay string.
replace_once(
    BOARD,
    """                          {(!zone.startDate || zone.visitDay === "غير محدد") && (
""",
    """                          {(!zone.startDate || !zone.intervalDays) && (
""",
    "zone_schedule_warning_contract",
)

replace_once(
    BOARD,
    """                          <span className={zone.dateColor || "text-slate-400"}>{zone.visitDay} ({zone.startDate})</span>
""",
    """                          <span className={zone.dateColor || "text-slate-400"}>
                            {zone.intervalDays ? `كل ${zone.intervalDays} يوم` : "غير مجدول"}
                            {zone.startDate ? ` (${zone.startDate})` : ""}
                          </span>
""",
    "zone_schedule_display_contract",
)

replace_once(
    BOARD,
    """setSchedulingForm({ frequency: zone.frequency, visitDay: zone.visitDay, startDate: zone.startDate }); setIsSchedulingModalOpen(true);
""",
    """setSchedulingForm({ frequency: frequencyFromIntervalDays(zone.intervalDays), visitDay: "السبت", startDate: zone.startDate }); setCustomDays(zone.intervalDays && ![7, 14, 30].includes(zone.intervalDays) ? zone.intervalDays : 14); setIsSchedulingModalOpen(true);
""",
    "zone_schedule_editor_contract",
)


# Cancel reorder must normalize wire money types too.
replace_once(
    BOARD,
    """      const freshShops = await authenticatedFetch("/dispatch/shops");
      setShops(freshShops);
""",
    """      const freshShops = await authenticatedFetch("/dispatch/shops");
      setShops(normalizeShops(freshShops));
""",
    "cancel_reorder_shop_normalization",
)


# ------------------------------------------------------------------
# Static contract gates
# ------------------------------------------------------------------
board = BOARD.read_text(encoding="utf-8")
backend = BACKEND.read_text(encoding="utf-8")

checks = {
    "SOURCE_WAREHOUSE_REQUIRED": "source_location_id: selectedSourceWarehouseId" in board,
    "SOURCE_WAREHOUSE_FETCHED": 'authenticatedFetch("/warehouse/locations"' in board,
    "NO_LEGACY_SCHEDULE_PAYLOAD": (
        "frequency: schedulingForm.frequency" not in board
        and "customDays:" not in board[board.find("const handleUpdateScheduling"):board.find("const handleSaveZone")]
    ),
    "NUMERIC_SCHEDULE_PAYLOAD": "intervalDays," in board,
    "BACKEND_STATUS_OWNED": "const today = new Date();" not in board,
    "WS_CURRENT_TOKEN": 'const token = localStorage.getItem("admin_token");' in board,
    "WS_COALESCED": "scheduleRealtimeRefresh" in board,
    "VEHICLE_ABORT_GUARD": "return () => controller.abort();" in board,
    "ARCHIVED_SHOPS_VISIBLE": "Shop.is_archived == False" not in backend[
        backend.find('@router.get("/dispatch/shops"'):
        backend.find("# PATCH: DISPATCH_CONCURRENCY_EMERGENCY_INTEGRITY")
    ],
    "WIRE_SHOPS_NORMALIZED": "normalizeShops" in board,
    "TYPED_TAB": "useState<TabId>" in board,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail(f"Static verification failed: {failed}")

print("DISPATCH_SOURCE_WAREHOUSE_CONTRACT=OK")
print("DISPATCH_NUMERIC_SCHEDULING_CONTRACT=OK")
print("DISPATCH_COMPANY_TIME_STATUS_CONTRACT=OK")
print("DISPATCH_WEBSOCKET_BURST_GUARD=OK")
print("DISPATCH_WEBSOCKET_LATEST_TOKEN=OK")
print("DISPATCH_VEHICLE_FETCH_RACE_GUARD=OK")
print("DISPATCH_ARCHIVED_SHOPS_READ_CONTRACT=OK")
print("DISPATCH_SHOP_WIRE_NORMALIZATION=OK")
print("DASHBOARD_DISPATCHBOARD_ALIGNMENT_V1=OK")
