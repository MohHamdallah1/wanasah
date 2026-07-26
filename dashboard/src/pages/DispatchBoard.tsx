import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Truck, LayoutGrid, ClipboardList, Calendar, Search, Pencil, Trash2, Plus, RotateCcw, X, Upload, Eye, Eraser, Save, XCircle, Loader2, AlertCircle, Rocket } from "lucide-react";
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
// Utils
const sortZones = (zones: Zone[]) => {
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

export default function DispatchBoard() {
  // +++ النسف المعماري (تجاوز TypeScript): توسيع نوع TabId محلياً ليقبل "launch" +++
  const [activeTab, setActiveTab] = useState<string>(() => localStorage.getItem("activeTab") || "routes");
  const [confirmDialog, setConfirmDialog] = useState<{ isOpen: boolean, title: string, message: string, onConfirm: () => void }>({ isOpen: false, title: "", message: "", onConfirm: () => { } });
  const [unsavedTabPrompt, setUnsavedTabPrompt] = useState<string | null>(null);

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
  const [pendingRoutes, setPendingRoutes] = useState<PendingRoute[]>([]);
  const [shortages, setShortages] = useState<Shortage[]>([]);
  const [shops, setShops] = useState<Shop[]>([]);

  // +++ الدرع المعماري للـ UX: ربط المنطقة المحددة بالذاكرة المحلية لمنع ضياعها عند الـ Refresh +++
  const [selectedZoneIdForZones, setSelectedZoneIdForZones] = useState(() => localStorage.getItem("wanasah_selected_zone") || "");

  useEffect(() => {
    if (selectedZoneIdForZones) {
      localStorage.setItem("wanasah_selected_zone", selectedZoneIdForZones);
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
  const [schedulingForm, setSchedulingForm] = useState({ frequency: "أسبوعي (مرة في الأسبوع)", visitDay: "السبت", startDate: new Date().toISOString().split('T')[0] });

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
  const [duplicateWarning, setDuplicateWarning] = useState<{ show: boolean, shopData: any, apiPayload: any, localState: any } | null>(null);
  const [restorePromptShop, setRestorePromptShop] = useState<Shop | null>(null);

  // Snapshot of shops taken when entering edit mode — used for Cancel/revert
  const savedShopsRef = useRef<Shop[]>([]);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isSuicideModalOpen, setIsSuicideModalOpen] = useState(false);
  const [zoneToKill, setZoneToKill] = useState<Zone | null>(null);
  const [confirmName, setConfirmName] = useState("");

  // C-03: React-state product search filter (replaces DOM manipulation)
  const [productSearch, setProductSearch] = useState("");

  // CS-WH-03: Warehouse audit lock status for dispatch warning banner
  const [isWarehouseLocked, setIsWarehouseLocked] = useState(false);

  const fetchInitialData = useCallback(() => {
    const controller = new AbortController();
    authenticatedFetch("/dispatch/init", { signal: controller.signal })
      .then(data => {
        const sorted = sortZones(data.zones || []); setZones(sorted); setDrivers(data.drivers || []); setVehicles(data.vehicles || []); setProducts(data.products || []);

        // +++ الكي الجراحي (UX): الحفاظ على المنطقة المحددة حالياً، وعدم إجبار المستخدم على العودة لأول القائمة بعد الـ Refresh +++
        if (sorted.length > 0) {
          setSelectedZoneIdForZones(prev => prev ? prev : sorted[0].id);
        }

        if (data.products?.length > 0) setNewShortage({ productName: data.products[0].name, quantity: 1 });
      })
      .catch(err => err.name !== 'AbortError' && toast.error("خطأ في الاتصال بالخادم (Init): " + err.message));

    // H-02: Pass abort signal to all parallel fetches for clean unmount cleanup
    // H-03: Add Array.isArray guards to prevent .map is not a function crashes
    const signal = controller.signal;
    authenticatedFetch("/dispatch/shops", { signal })
      .then(data => setShops(Array.isArray(data) ? data : []))
      .catch(err => { if (err.name !== 'AbortError') console.error(err); });
    authenticatedFetch("/dispatch/active_routes", { signal })
      .then(data => setPendingRoutes(Array.isArray(data) ? data : []))
      .catch(err => { if (err.name !== 'AbortError') console.error(err); });
    authenticatedFetch("/dispatch/shortages", { signal })
      .then(data => setShortages(Array.isArray(data) ? data : []))
      .catch(err => { if (err.name !== 'AbortError') console.error(err); });

    // CS-WH-03: Check warehouse lock status on mount
    authenticatedFetch("/warehouse/status", { signal })
      .then((data: any) => setIsWarehouseLocked(data?.status === 'AUDIT_LOCK'))
      .catch(err => { if (err.name !== 'AbortError') console.error(err); });

    return controller;
  }, []);

  // Step 5.7c: Replace polling with WebSocket for real-time dispatch updates
  useEffect(() => {
    const controller = fetchInitialData();

    // Build WebSocket URL from VITE_API_URL
    const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:5000';
    const wsUrl = apiUrl.replace(/^http/, 'ws') + '/ws/dispatch';

    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const connectWS = () => {
      ws = new WebSocket(wsUrl);

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.event) {
            authenticatedFetch("/dispatch/active_routes")
              .then(res => setPendingRoutes(Array.isArray(res) ? res : []))
              .catch(() => {});
            authenticatedFetch("/dispatch/shortages")
              .then(res => setShortages(Array.isArray(res) ? res : []))
              .catch(() => {});
          }
        } catch (err) {
          console.error("WS Parse error", err);
        }
      };

      ws.onclose = () => {
        // Auto-reconnect after 3 seconds if disconnected
        reconnectTimer = setTimeout(connectWS, 3000);
      };
    };

    connectWS();

    return () => {
      controller.abort();
      clearTimeout(reconnectTimer);
      if (ws) {
        ws.onclose = null; // Prevent reconnect loop on unmount
        ws.close();
      }
    };
  }, [fetchInitialData, authenticatedFetch]);

  useEffect(() => {
    if (selectedVehicleId) {
      authenticatedFetch(`/dispatch/inventory/${selectedVehicleId}`)
        .then(data => { const inv: Record<string, number> = {}; data.forEach((item: any) => { inv[item.product_id] = item.current_quantity; }); setPreloadQuantities(inv); })
        .catch(err => toast.error("خطأ في جلب مخزون المركبة: " + err.message));
    } else setPreloadQuantities({});
  }, [selectedVehicleId]);

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
    } catch (err: any) {
      toast.error("خطأ في حفظ التعديلات: " + err.message);
    } finally {
      setIsSaving(false);
    }
  }, [shops, selectedZoneIdForZones]);

  // Helper: cancel edits and revert by re-fetching from server
  const handleCancelReorder = useCallback(async () => {
    try {
      const freshShops = await authenticatedFetch("/dispatch/shops");
      setShops(freshShops);
    } catch (e) {
      // fallback to snapshot if fetch fails
      setShops(savedShopsRef.current);
    }
    setHasUnsavedChanges(false);
    setIsEditMode(false);
    setSelectedShopIds([]);
  }, []);

  const fetchArchivedZones = async () => {
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

  // Helper: handle tab switch with dirty-state guard
  const handleTabChange = useCallback((tabId: string) => {
    if (tabId === activeTab) return;
    if (hasUnsavedChanges) {
      setUnsavedTabPrompt(tabId); // تفعيل النافذة الذكية بدل العادية
      return;
    }
    setActiveTab(tabId);
  }, [activeTab, hasUnsavedChanges]);

  const handleDispatchRoute = () => {
    if (!selectedZoneId || !selectedDriverId || !selectedVehicleId) return toast.error("⚠️ يرجى تحديد المنطقة والمندوب والسيارة");
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
        inventory: preloadQuantities // +++ إرسال جرد الحمولة للسيرفر +++
      })
    })
      .then(() => {
        toast.success("تم إطلاق خط السير بنجاح");
        setSelectedZoneId(""); setSelectedDriverId(""); setSelectedVehicleId(""); setPreloadQuantities({});
        // +++ التحديث الفوري للقائمة بدون ريفرش +++
        authenticatedFetch("/dispatch/active_routes").then(data => setPendingRoutes(data)).catch(err => console.error(err));
      })
      .catch(err => toast.error("خطأ في إطلاق خط السير: " + err.message));
  };

  const handleConfirmRouteAction = async () => {
    if (!activeRoute) return;
    const totalInventory = Object.values(preloadQuantities).reduce((acc, q) => acc + (typeof q === 'number' ? q : 0), 0);
    if (totalInventory === 0) {
      toast.error("⚠️ لا يمكن إطلاق خط السير بحمولة صفر.");
      return;
    }

    const newDriverId = routeModalType === "transfer" ? transferDriverId : activeRoute.driverId;

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

      // +++ التحديث الفوري للقائمة بدون ريفرش من السيرفر مباشرة لضمان الدقة +++
      const freshRoutes = await authenticatedFetch("/dispatch/active_routes");
      setPendingRoutes(freshRoutes);

      toast.success("تم تفعيل خط السير بنجاح");
      setIsRouteModalOpen(false);
    } catch (err: any) {
      toast.error(err.message);
    }
  };

  const handleUpdateScheduling = async () => {
    const targetIds = schedulingType === "bulk" ? selectedBulkZoneIds : [selectedZoneIdForZones];
    const zoneNames = zones.filter(z => targetIds.includes(z.id)).map(z => z.name).join("، ");
    try {
      await Promise.all(targetIds.map(id =>
        authenticatedFetch(`/dispatch/zones/${id}`, {
          method: "PUT",
          body: JSON.stringify({
            frequency: schedulingForm.frequency,
            visitDay: schedulingForm.visitDay,
            startDate: schedulingForm.startDate
          })
        })
      ));
      setZones(prev => sortZones(prev.map(z => targetIds.includes(z.id) ? { ...z, ...schedulingForm } : z)));
      toast.success(`تم تحديث إعدادات الجدولة لـ ${zoneNames}`);
      setIsSchedulingModalOpen(false);
    } catch (err: any) {
      toast.error("يرجى ادخال تاريخ البدء : " + err.message);
    }
  };

  const handleSaveZone = async () => {
    if (!zoneFormName.trim()) return toast.error("⚠️ يرجى إدخال اسم المنطقة");

    try {
      if (editingZoneId) {
        await authenticatedFetch(`/dispatch/zones/${editingZoneId}`, { method: "PUT", body: JSON.stringify({ name: zoneFormName }) });
        setZones(prev => prev.map(z => z.id === editingZoneId ? { ...z, name: zoneFormName } : z));
        setIsZoneModalOpen(false); setZoneFormName(""); setEditingZoneId(null);
        toast.success("تم الحفظ بنجاح");
      } else {
        const res = await authenticatedFetch("/dispatch/zones", { method: "POST", body: JSON.stringify({ name: zoneFormName }) });
        const newZone = {
          id: String(res.zone_id),
          name: zoneFormName,
          scheduleStatus: null,
          frequency: "أسبوعي",
          visitDay: "السبت",
          startDate: new Date().toISOString().split('T')[0],
          shopsCount: 0
        };
        setZones(prev => [...prev, newZone]);
        setIsZoneModalOpen(false); setZoneFormName(""); setEditingZoneId(null);
        toast.success("تم إضافة المنطقة ✅. يرجى تحديد جدولتها الآن.");

        // +++ فتح نافذة الجدولة تلقائياً للمنطقة الجديدة +++
        setSelectedZoneIdForZones(newZone.id);
        setSchedulingType("local");
        setSchedulingForm({ frequency: newZone.frequency, visitDay: newZone.visitDay, startDate: newZone.startDate });
        setIsSchedulingModalOpen(true);
      }
    } catch (err: any) {
      toast.error("خطأ في حفظ المنطقة: " + err.message);
    }
  };

  const handleSaveShop = async () => {
    if (!shopForm.name.trim() || !shopForm.phone.trim() || !shopForm.mapLink.trim() || !shopForm.zoneId) {
      toast.error("⚠️ يرجى إكمال جميع البيانات");
      return;
    }

    const apiPayload = {
      name: shopForm.name,
      owner: shopForm.owner,
      phone: shopForm.phone,
      initial_debt: Number(shopForm.initialDebt) || 0,
      max_debt_limit: Number(shopForm.maxDebtLimit) || 0,
      map_link: shopForm.mapLink,
      zone_id: shopForm.zoneId
    };

    const localShopState = {
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
        setShops(prev => prev.map(s => s.id === editingShopId ? { ...s, ...localShopState } : s));
        if (isEditMode) setHasUnsavedChanges(true);
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
    } catch (error: any) {
      // +++ اصطياد بيانات التطابق من "الدرع المطور" +++
      if (error.status === 409 && error.data?.is_duplicate) {
        setDuplicateWarning({
          show: true,
          shopData: error.data.existing_shop,
          apiPayload: { ...apiPayload, force_save: true },
          localState: localShopState
        });
      } else {
        toast.error(`❌ خطأ: ${error.message}`);
      }
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
    } catch (error: any) {
      toast.error(error.message || "حدث خطأ أثناء فرض الحفظ");
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

  const handleAddShortage = async () => {
    if (!shortageZoneId || !shortageShopId || shortageDraft.length === 0) return toast.error("⚠️ يرجى إكمال بيانات الطلب");
    const zone = zones.find(z => z.id === shortageZoneId);
    const shop = shops.find(s => s.id === shortageShopId);

    const newShortages = shortageDraft.map(item => ({
      zoneId: shortageZoneId,
      zoneName: zone?.name || "",
      shopId: shortageShopId,
      shopName: shop?.name || "",
      driverId: shortageDriverId || null,
      driverName: drivers.find(d => d.id === shortageDriverId)?.name || "بدون مندوب (معلقة)",
      productName: item.productName,
      quantity: Number(item.quantity),
      status: "pending",
      waitTime: "الآن"
    }));
    try {
      // إذا كنا في وضع التعديل: احذف الطلبات القديمة أولاً ثم أنشئ الجديدة (Delete-then-Insert)
      if (editingShortageIds.length > 0) {
        await Promise.all(
          editingShortageIds.map(id =>
            authenticatedFetch(`/dispatch/shortages/${id}`, { method: "DELETE" })
          )
        );
        setEditingShortageIds([]);
      }
      await authenticatedFetch("/dispatch/shortages", {
        method: "POST",
        body: JSON.stringify(newShortages)
      });
      const data = await authenticatedFetch("/dispatch/shortages");
      setShortages(data);
      setShortageDraft([]);
      if (products.length > 0) setNewShortage({ productName: products[0].name, quantity: 1 });
      toast.success("تم تسجيل الطلبات بنجاح");
    } catch (err: any) {
      toast.error(err.message);
    }
  };

  const handleAddProductToDraft = () => {
    if (!newShortage.productName || !newShortage.quantity) return toast.error("⚠️ اختر منتج وكمية");
    const product = products.find(pr => pr.name === newShortage.productName);
    setShortageDraft(prev => {
      const existing = prev.findIndex(d => d.productName === newShortage.productName);
      if (existing !== -1) {
        // دمج الكمية بدل إضافة سطر جديد
        return prev.map((d, i) => i === existing ? { ...d, quantity: d.quantity + newShortage.quantity! } : d);
      }
      return [...prev, { productId: product?.id || "", productName: newShortage.productName!, quantity: newShortage.quantity! }];
    });
    setNewShortage(p => ({ ...p, quantity: 1 }));
  };

  const handleEditShortageGroup = (shopId: string) => {
    const shopShortages = shortages.filter(s => s.shopId === shopId);
    if (shopShortages.length === 0) return;

    const first = shopShortages[0];

    // 1. تحديد المنطقة والمحل في قوائم الاختيار
    setShortageZoneId(first.zoneId);
    setShortageShopId(first.shopId);

    // 2. نقل المنتجات للـ Draft
    const draft = shopShortages.map(s => ({
      productId: products.find(p => p.name === s.productName)?.id || "",
      productName: s.productName,
      quantity: s.quantity,
    }));
    setShortageDraft(draft);

    // 3. حفظ IDs القديمة للحذف لاحقاً عند تأكيد الطلب فقط (لا حذف الآن)
    setEditingShortageIds(shopShortages.map(s => s.id));

    toast.info("تم تحميل الطلب للتعديل — عدّل الكميات ثم اضغط تأكيد الطلب");
  };

  const handleCloseShortageModal = () => {
    setIsShortageModalOpen(false);
    setShortageDraft([]);
    setShortageZoneId("");
    setShortageShopId("");
    setEditingShortageIds([]);
  };

  return (
    <div className="w-full flex flex-col animate-in fade-in duration-500">
      <div className="bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between sticky top-0 z-20">
        <div className="flex items-center gap-6">
          <div className="flex bg-slate-100 p-1 rounded-xl">
            {/* +++ النسف المعماري: فصل الإطلاق عن المراقبة בـ 3 تبويبات +++ */}
            {[
              { id: "routes", label: "الخطوط النشطة", icon: Truck },
              { id: "launch", label: "إطلاق خط جديد", icon: Plus },
              { id: "zones", label: "هيكلة المناطق", icon: LayoutGrid }
            ].map(tab => (
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

      {/* +++ النسف المعماري: تقليل الـ padding الخارجي ليتمدد المحتوى لليمين واليسار +++ */}
      <div className="pt-6 pb-6 px-0 w-full">
        <AnimatePresence mode="wait">
          {activeTab === "routes" ? (
            <motion.div key="routes" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="flex justify-center w-full">
              {/* +++ النسف المعماري: جمع العناصر التائهة داخل حاوية "عصرية" موحدة +++ */}
              <div className="bg-white border border-slate-200 rounded-2xl p-5 md:p-6 shadow-xl w-full mt-[-15px]">
                <div className="flex items-center justify-between mb-6 pb-3 border-b border-slate-100">
                  <h2 className="text-xl font-black text-slate-800 flex items-center gap-3">
                    <Truck className="w-6 h-6 text-[#1e87bb]" /> مناطق قيد العمل (الخطوط النشطة)
                  </h2>
                  {(() => {
                    const hasPostponed = pendingRoutes.some(r => r.status === "postponed");
                    return (
                      <button
                        onClick={() => setIsShowPostponedModalOpen(true)}
                        className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold shadow-sm transition-all ${hasPostponed ? "bg-orange-50 border border-orange-500 text-orange-700 hover:bg-orange-100" : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50"}`}
                      >
                        <Eye className="w-4 h-4" />
                        {hasPostponed && (
                          <span className="relative flex h-2.5 w-2.5">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-orange-400 opacity-75" />
                            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-orange-500" />
                          </span>
                        )}
                        👁️ عرض المؤجل ({pendingRoutes.filter(r => r.status === "postponed").length})
                      </button>
                    );
                  })()}
                </div>
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
                  onOpenRouteModal={(r, t) => { setActiveRoute(r); setRouteModalType(t); setTransferDriverId(r.driverId); setSelectedVehicleId(r.vehicleId); setIsRouteModalOpen(true); }}
                  onPostponeRoute={async (id) => {
                    try {
                      await authenticatedFetch(`/dispatch/route/${id}/status`, {
                        method: "PUT",
                        body: JSON.stringify({ status: "postponed" })
                      });
                      setPendingRoutes(prev => prev.map(r => r.id === id ? { ...r, status: "postponed" } : r));
                      toast.info("تم تأجيل المنطقة");
                    } catch (e: any) {
                      toast.error(e.message);
                    }
                  }}
                  onCloseZone={route => {
                    const isAlmostDone = route.shopsRemaining > 0 && route.shopsRemaining <= 5;
                    const message = isAlmostDone
                      ? `تنبيه: باقي ${route.shopsRemaining} محلات فقط لإنهاء المنطقة! هل أنت متأكد من الإغلاق والتصفير؟`
                      : "هل أنت متأكد من إغلاق وتصفير هذه المنطقة؟";

                    setConfirmDialog({
                      isOpen: true,
                      title: "تأكيد الإغلاق والتصفير",
                      message: message,
                      onConfirm: async () => {
                        try {
                          await authenticatedFetch(`/dispatch/route/${route.id}/status`, {
                            method: "PUT",
                            body: JSON.stringify({ status: "closed" })
                          });
                          setPendingRoutes(prev => prev.filter(r => r.id !== route.id));
                          fetchInitialData();
                          toast.success("تم إغلاق المنطقة وتصفير السيارة");
                        } catch (e: any) {
                          toast.error(e.message);
                        } finally {
                          setConfirmDialog(d => ({ ...d, isOpen: false }));
                        }
                      }
                    })
                  }}
                  onForceWithdraw={route => {
                    const isAlmostDone = route.shopsRemaining > 0 && route.shopsRemaining <= 5;
                    const message = isAlmostDone
                      ? `تنبيه: باقي ${route.shopsRemaining} محلات فقط! هل أنت متأكد من إيقاف وسحب المنطقة؟`
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
                          setPendingRoutes(prev => prev.map(r => r.id === route.id ? { ...r, status: "waiting", driverId: "", vehicleId: "" } : r));
                          fetchInitialData();
                          toast.success("تم إيقاف المنطقة وسحبها بنجاح");
                        } catch (e: any) {
                          toast.error(e.message);
                        } finally {
                          setConfirmDialog(d => ({ ...d, isOpen: false }));
                        }
                      }
                    })
                  }}
                  driverShortagesMap={driverShortagesMap}
                />
              </div>
            </motion.div>
          ) : activeTab === "launch" ? (
            <motion.div key="launch" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }} className="flex justify-center w-full">
              {/* +++ النسف المعماري: إزالة max-w ليأخذ عرض الشاشة بالكامل، وسحبه للأعلى أكثر +++ */}
              <div className="bg-white border border-slate-200 rounded-2xl p-5 md:p-6 shadow-xl w-full mt-[-15px]">

                {/* 1. تقليل المسافة أسفل العنوان (mb-4 بدلاً من mb-8) */}
                <div className="flex items-center justify-between mb-4 pb-3 border-b border-slate-100">
                  <h2 className="text-xl font-black text-slate-800 flex items-center gap-3">
                    <Rocket className="w-6 h-6 text-[#1e87bb]" /> إطلاق خط سير جديد
                  </h2>
                </div>

                {/* 2. تقليل المسافة أسفل مستطيل الاختيارات (mb-4 بدلاً من mb-8) وتقليل حشوته الداخلية (p-4 بدلاً من p-6) */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4 bg-slate-50 p-4 rounded-xl border border-slate-200">
                  <CustomSelect label="المنطقة" options={zones.map(z => ({ id: z.id, label: z.name, scheduleStatus: z.scheduleStatus }))} value={selectedZoneId} onChange={setSelectedZoneId} placeholder="اختر المنطقة" />
                  <CustomSelect label="المندوب" options={drivers.map(d => ({ id: d.id, label: d.name }))} value={selectedDriverId} onChange={setSelectedDriverId} placeholder="اختر المندوب" />
                  <CustomSelect label="السيارة" options={vehicles.map(v => ({ id: v.id, label: v.label }))} value={selectedVehicleId} onChange={setSelectedVehicleId} placeholder="اختر السيارة" />
                </div>

                <div className="bg-slate-50 rounded-2xl overflow-hidden border border-slate-200 flex flex-col">
                  <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between bg-white">
                    <span className="text-base font-bold text-slate-700">جرد الحمولة (كرتونة)</span>
                    <div className="flex items-center gap-4">
                      {/* +++ مربع البحث السريع في المنتجات +++ */}
                      {/* C-03: React-state based filtering — replaces DOM manipulation */}
                      <div className="relative">
                        <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                        <input
                          type="search"
                          placeholder="ابحث عن منتج..."
                          value={productSearch}
                          onChange={(e) => setProductSearch(e.target.value)}
                          className="pl-4 pr-9 py-2 text-sm border border-slate-200 rounded-xl outline-none focus:border-[#1e87bb] w-64 bg-slate-50 transition-all"
                        />
                      </div>
                      <button onClick={() => setPreloadQuantities({})} className="text-sm font-bold text-red-500 hover:text-red-700 flex items-center gap-1 bg-red-50 px-3 py-1.5 rounded-lg transition-colors"><Eraser className="w-4 h-4" /> تصفير الكل</button>
                    </div>
                  </div>

                  {/* +++ النسف المعماري: تقييد الارتفاع بـ 50vh مع Scrollbar أنيق +++ */}
                  <div className="max-h-[50vh] overflow-y-auto custom-scrollbar bg-white">
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 z-10 bg-slate-100 shadow-sm border-b border-slate-200">
                        <tr className="text-slate-500 text-xs uppercase">
                          <th className="text-start py-3 px-6 font-extrabold w-2/3">المنتج</th>
                          <th className="text-center py-3 px-6 font-extrabold">الكمية (كرتونة)</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {products
                          .filter(prod => !productSearch.trim() || prod.name.toLowerCase().includes(productSearch.toLowerCase()))
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

                <button
                  onClick={handleDispatchRoute}
                  className="w-full mt-8 bg-gradient-to-r from-[#1e87bb] to-[#166a94] hover:opacity-90 text-white py-4 rounded-2xl text-lg font-black shadow-xl transition-all active:scale-[0.99] flex items-center justify-center gap-3"
                >
                  <Rocket className="w-6 h-6" /> اعتماد وإطلاق خط السير
                </button>
              </div>
            </motion.div>
          ) : (
            <motion.div key="zones" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="flex gap-4 h-[calc(100vh-120px)] w-full mt-[-10px]">
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
                          {(!zone.startDate || zone.visitDay === "غير محدد") && (
                            <span title="تنبيه: لم يتم ضبط إعدادات الجدولة لهذه المنطقة" className="text-amber-500 bg-amber-50 rounded-full p-0.5 animate-pulse cursor-help"><AlertCircle className="w-3.5 h-3.5" /></span>
                          )}
                        </span>
                        <p className="text-[10px] mt-1 flex items-center gap-1">
                          <span className={zone.dateColor || "text-slate-400"}>{zone.visitDay} ({zone.startDate})</span>
                          <span className="text-slate-300">•</span>
                          <span className="text-[#1e87bb] font-bold">{zone.shopsCount || 0} محلات</span>
                        </p>
                      </div><div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"><button onClick={e => { e.stopPropagation(); setZoneFormName(zone.name); setEditingZoneId(zone.id); setIsZoneModalOpen(true); }} className="p-1 hover:bg-white rounded-md text-slate-400 hover:text-[#1e87bb]"><Pencil className="w-3.5 h-3.5" /></button><button onClick={e => { e.stopPropagation(); setSelectedZoneIdForZones(zone.id); setSchedulingType("local"); setSchedulingForm({ frequency: zone.frequency, visitDay: zone.visitDay, startDate: zone.startDate }); setIsSchedulingModalOpen(true); }} className="p-1 hover:bg-white rounded-md text-slate-400 hover:text-[#1e87bb]"><Calendar className="w-3.5 h-3.5" /></button><button
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
                  <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between shrink-0"><div className="flex items-center gap-4"><h2 className="text-lg font-bold text-slate-800">المحلات</h2><div className="relative"><Search className="absolute end-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" /><input type="search" value={shopSearchQuery} onChange={e => setShopSearchQuery(e.target.value)} placeholder="بحث..." className="rounded-xl border border-slate-200 bg-slate-50 pe-9 ps-4 py-2 text-sm focus:ring-2 focus:ring-[#1e87bb]/20 outline-none w-80 transition-all" /></div></div><div className="flex items-center gap-3">{isEditMode ? (<><button onClick={handleCancelReorder} disabled={isSaving} className="px-4 py-2.5 rounded-xl text-sm font-bold flex items-center gap-2 transition-all shadow-sm border border-slate-200 text-slate-600 hover:bg-red-50 hover:text-red-600 hover:border-red-200 disabled:opacity-50"><XCircle className="w-4 h-4" /> إلغاء</button><button onClick={handleSaveReorder} disabled={isSaving || !hasUnsavedChanges} className={`px-4 py-2.5 rounded-xl text-sm font-bold flex items-center gap-2 transition-all shadow-sm ${hasUnsavedChanges ? 'bg-emerald-500 hover:bg-emerald-600 text-white' : 'bg-slate-100 text-slate-400 cursor-not-allowed'} disabled:opacity-60`}>{isSaving ? <><Loader2 className="w-4 h-4 animate-spin" /> جاري الحفظ...</> : <><Save className="w-4 h-4" /> حفظ</>}</button></>) : (<button onClick={() => { savedShopsRef.current = shops; setIsEditMode(true); }} className="px-4 py-2.5 rounded-xl text-sm font-bold flex items-center gap-2 transition-all shadow-sm border border-slate-200 text-slate-600 hover:bg-slate-50"><Pencil className="w-4 h-4" />ترتيب وإدارة</button>)}<button
                    onClick={() => setShowRecycleBin(true)}
                    className="p-2.5 rounded-xl border border-slate-200 text-slate-500 hover:bg-slate-50 shadow-sm transition-all hover:text-red-500"
                    title="فتح أرشيف المحلات المؤرشفة"
                  >
                    <Trash2 className="w-5 h-5" />
                  </button><button onClick={() => { setEditingShopId(null); setShopForm({ name: "", owner: "", phone: "", mapLink: "", zoneId: selectedZoneIdForZones, initialDebt: 0, maxDebtLimit: 0 }); setIsShopModalOpen(true); }} className="bg-[#1e87bb] hover:bg-[#0f766e] text-white px-4 py-2.5 rounded-xl text-sm font-bold flex items-center gap-2 shadow-sm transition-colors"><Plus className="w-4 h-4" /> إضافة محل</button></div></div>
                  <ShopTable shops={shopsInSelectedZone} zones={zones} isEditMode={isEditMode} selectedShopIds={selectedShopIds} allFilteredShops={shopSearchQuery.trim() ? shopsInSelectedZone : null} selectedZoneIdForZones={selectedZoneIdForZones} onToggleSelectAll={() => setSelectedShopIds(selectedShopIds.length === shopsInSelectedZone.length ? [] : shopsInSelectedZone.map(s => s.id))} onToggleSelectShop={id => setSelectedShopIds(prev => prev.includes(id) ? prev.filter(sid => sid !== id) : [...prev, id])} onSequenceChange={(id, n) => { const list = [...shopsInSelectedZone]; const from = list.findIndex(s => s.id === id); const to = Math.max(0, Math.min(n - 1, list.length - 1)); const [item] = list.splice(from, 1); list.splice(to, 0, item); const reordered = list.map((s, i) => ({ ...s, sequence: i + 1 })); setShops(prev => prev.map(s => { if (s.zoneId !== selectedZoneIdForZones || s.archived) return s; return reordered.find(r => r.id === s.id) || s; })); setHasUnsavedChanges(true); }} onEditShop={s => { setShopForm({ ...s }); setEditingShopId(s.id); setIsShopModalOpen(true); }} onArchiveShop={id => {
                    if (isEditMode) {
                      // +++ التصفيح: إضافة تأكيد قبل "الإخفاء" لمنع الأخطاء الطائشة +++
                      if (!window.confirm("⚠️ هل أنت متأكد من رغبتك في أرشفة هذا المحل؟")) return;
                      setShops(prev => prev.map(s => s.id === id ? { ...s, archived: true } : s));
                      setZones(prev => sortZones(prev.map(z => z.id === shops.find(s => s.id === id)?.zoneId ? { ...z, shopsCount: Math.max(0, (z.shopsCount || 0) - 1) } : z)));
                      setHasUnsavedChanges(true);
                      toast.info("تم إخفاء المحل محلياً. اضغط 'حفظ التعديلات' لتأكيد النقل للأرشيف.");
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
                            toast.success("تم أرشفة المحل بنجاح");
                          } catch (err: any) { toast.error("خطأ في الأرشفة: " + err.message); }
                          finally { setConfirmDialog(d => ({ ...d, isOpen: false })); }
                        }
                      });
                    }
                  }} onDragStart={(e, id) => e.dataTransfer.setData("shopId", id)} onDrop={(e, targetId) => { const draggedId = e.dataTransfer.getData("shopId"); if (draggedId === targetId) return; const list = [...shopsInSelectedZone]; const from = list.findIndex(s => s.id === draggedId); const to = list.findIndex(s => s.id === targetId); const [item] = list.splice(from, 1); list.splice(to, 0, item); const reordered = list.map((s, i) => ({ ...s, sequence: i + 1 })); setShops(prev => prev.map(s => { if (s.zoneId !== selectedZoneIdForZones || s.archived) return s; return reordered.find(r => r.id === s.id) || s; })); setHasUnsavedChanges(true); }} />
                  <AnimatePresence>{isEditMode && selectedShopIds.length > 0 && (<motion.div initial={{ opacity: 0, y: 50, x: "-50%" }} animate={{ opacity: 1, y: 0, x: "-50%" }} exit={{ opacity: 0, y: 50, x: "-50%" }} className="absolute bottom-6 left-1/2 -translate-x-1/2 z-20"><div className="bg-slate-900/90 backdrop-blur border border-slate-700 px-6 py-3 rounded-full shadow-2xl flex items-center gap-6 whitespace-nowrap text-white"><p className="text-sm font-bold">تحديد <span className="text-amber-400">{selectedShopIds.length}</span> محلات</p><div className="w-px h-6 bg-slate-700" /><div className="flex items-center gap-2"><button onClick={() => setIsBulkTransferModalOpen(true)} className="bg-[#1e87bb] text-white px-4 py-2 rounded-xl text-xs font-bold hover:bg-[#166a94] flex items-center gap-2 transition-all"><RotateCcw className="w-3.5 h-3.5" /> نقل 🔄</button><button onClick={() => setConfirmDialog({ isOpen: true, title: "أرشفة المحلات", message: `أرشفة ${selectedShopIds.length} محلات؟`, onConfirm: async () => { try { const payload = selectedShopIds.map(id => ({ id, archived: true })); await authenticatedFetch("/dispatch/shops/bulk_update", { method: "PUT", body: JSON.stringify(payload) }); setShops(prev => prev.map(s => selectedShopIds.includes(s.id) ? { ...s, archived: true } : s)); setSelectedShopIds([]); toast.success("تم أرشفة المحلات بنجاح"); } catch (err: any) { toast.error("خطأ في الأرشفة: " + err.message); } finally { setConfirmDialog(d => ({ ...d, isOpen: false })); } } })} className="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-2 transition-all"><Trash2 className="w-3.5 h-3.5" /> أرشفة 🗑️</button></div><button onClick={() => setSelectedShopIds([])} className="text-slate-400 hover:text-slate-200"><X className="w-4 h-4" /></button></div></motion.div>)}</AnimatePresence>
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
            </motion.div>
          )}
        </AnimatePresence>
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
        onCancelEdit={() => { setShortageDraft([]); setEditingShortageIds([]); setShortageZoneId(""); setShortageShopId(""); }}
        onDeleteShortage={id => setConfirmDialog({ isOpen: true, title: "تأكيد الحذف", message: "هل أنت متأكد من حذف هذا الطلب نهائياً؟", onConfirm: async () => { try { await authenticatedFetch(`/dispatch/shortages/${id}`, { method: "DELETE" }); setShortages(prev => prev.filter(s => s.id !== id)); toast.success("تم حذف الطلب بنجاح"); } catch (e: any) { toast.error("خطأ في الحذف: " + e.message); } finally { setConfirmDialog(d => ({ ...d, isOpen: false })); } } })}
        onDeleteShortageGroup={ids => setConfirmDialog({ isOpen: true, title: "حذف طلبات المحل", message: `هل أنت متأكد من حذف جميع طلبات هذا المحل (${ids.length} منتجات) نهائياً؟`, onConfirm: async () => { try { await Promise.all(ids.map(id => authenticatedFetch(`/dispatch/shortages/${id}`, { method: "DELETE" }))); setShortages(prev => prev.filter(s => !ids.includes(s.id))); toast.success("تم حذف جميع طلبات المحل بنجاح"); } catch (e: any) { toast.error("خطأ في الحذف: " + e.message); } finally { setConfirmDialog(d => ({ ...d, isOpen: false })); } } })}
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
        onClearInventory={() => setConfirmDialog({ isOpen: true, title: "تأكيد التصفير", message: "تصفير؟", onConfirm: () => { setPreloadQuantities({}); setConfirmDialog(d => ({ ...d, isOpen: false })); } })}
        onConfirmAction={handleConfirmRouteAction}
      />
      <ShopFormModal isOpen={isShopModalOpen} onClose={() => setIsShopModalOpen(false)} editingShopId={editingShopId} shopForm={shopForm} onShopFormChange={setShopForm} zones={zones} onSave={handleSaveShop} />
      <RecycleBinModal
        isOpen={showRecycleBin}
        onClose={() => setShowRecycleBin(false)}
        recycleSearchQuery={recycleSearchQuery}
        onRecycleSearchQueryChange={setRecycleSearchQuery}
        filteredRecycleBin={filteredRecycleBin}
        zones={zones}
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
            toast.success("تم استعادة المحل بنجاح");
          } catch (err: any) { toast.error(err.message); }
        }}
      />
      <BulkTransferModal isOpen={isBulkTransferModalOpen} onClose={() => setIsBulkTransferModalOpen(false)} selectedShopIds={selectedShopIds} zones={zones} selectedZoneIdForZones={selectedZoneIdForZones} targetTransferZoneId={targetTransferZoneId} onTargetTransferZoneChange={setTargetTransferZoneId} onConfirm={async () => { if (!targetTransferZoneId) return toast.error("⚠️ اختر المنطقة"); try { const payload = selectedShopIds.map(id => ({ id, zoneId: targetTransferZoneId, sequence: 999 })); await authenticatedFetch("/dispatch/shops/bulk_update", { method: "PUT", body: JSON.stringify(payload) }); setShops(prev => prev.map(s => selectedShopIds.includes(s.id) ? { ...s, zoneId: targetTransferZoneId, sequence: 999 } : s)); setSelectedShopIds([]); setIsBulkTransferModalOpen(false); setTargetTransferZoneId(""); toast.success("تم نقل المحلات بنجاح"); } catch (err: any) { toast.error("خطأ في النقل: " + err.message); } }} />
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
        authenticatedFetch={authenticatedFetch} // +++ تمرير دالة الحماية لقتل الخطأ +++
      />

      <ZoneModal isOpen={isZoneModalOpen} onClose={() => { setIsZoneModalOpen(false); setZoneFormName(""); setEditingZoneId(null); }} editingZoneId={editingZoneId} zoneFormName={zoneFormName} onZoneFormNameChange={setZoneFormName} onSave={handleSaveZone} />
      <PostponedRoutesModal isOpen={isShowPostponedModalOpen} onClose={() => setIsShowPostponedModalOpen(false)} routes={pendingRoutes.filter(r => r.status === "postponed")} drivers={drivers} onUpdateDriver={(id, drvId) => { const d = drivers.find(drv => drv.id === drvId); setPendingRoutes(prev => prev.map(r => r.id === id ? { ...r, driverId: drvId, driverName: d?.name || "" } : r)); }} onRestore={async (id) => { try { await authenticatedFetch(`/dispatch/route/${id}/status`, { method: "PUT", body: JSON.stringify({ status: "waiting" }) }); setPendingRoutes(prev => prev.map(r => r.id === id ? { ...r, status: "waiting" } : r)); toast.success("تم استعادة المنطقة بنجاح"); } catch (e: any) { toast.error(e.message); } }} />
      <ZoneRecycleBinModal isOpen={isZoneRecycleBinOpen} onClose={() => setIsZoneRecycleBinOpen(false)} recycleSearchQuery={zoneRecycleSearchQuery} onRecycleSearchQueryChange={setZoneRecycleSearchQuery} filteredRecycleBin={filteredZoneRecycleBin} onRestoreZone={handleRestoreZone} />
      <ShopBulkImportModal
        isOpen={isBulkImportModalOpen}
        onClose={() => setIsBulkImportModalOpen(false)}
        zones={zones}
        activeShops={activeShops}
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
                  await handleSaveReorder();
                  setActiveTab(unsavedTabPrompt);
                  setUnsavedTabPrompt(null);
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
                    await handleRestoreZone(restorePromptShop.zoneId); // استعادة المنطقة
                    await authenticatedFetch("/dispatch/shops/bulk_update", { method: "PUT", body: JSON.stringify([{ id: restorePromptShop.id, archived: false }]) }); // استعادة المحل
                    setShops(prev => prev.map(s => s.id === restorePromptShop.id ? { ...s, archived: false } : s));
                    setRestorePromptShop(null);
                    toast.success("تم استعادة المنطقة والمحل بنجاح ✅");
                  } catch (e: any) { toast.error("خطأ: " + e.message); }
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
                  setIsSuicideModalOpen(false);
                  toast.success(`تم أرشفة المنطقة (${zoneToKill?.name}) وكل محلاتها بنجاح ✅`);
                } catch (err: any) { toast.error(err.message); }
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

