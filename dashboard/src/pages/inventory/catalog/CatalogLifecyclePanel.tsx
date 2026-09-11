import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Archive, Link2, PauseCircle, PlayCircle, ShieldAlert, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import {
  buildLifecycleCommand,
  parseArchivePreflight,
  parseMutationMessage,
  parseProductLocations,
  parseVariantMutation,
  type ArchivePreflight,
  type CatalogVariant,
  type ProductLocationAssignment,
} from "./contracts";

interface LocationOption { id: number; code: string; name: string }
interface Props {
  variant: CatalogVariant;
  locations: LocationOption[];
  onVariantChanged: (variant: CatalogVariant) => void | Promise<void>;
  onVariantDeleted: (variantId: number) => void | Promise<void>;
}

const BLOCKER_LABELS: Record<string, string> = {
  INVENTORY_BALANCE: "رصيد أو حجز مخزون",
  PRODUCT_LOCATION: "ربط تشغيلي بموقع",
  STOCK_POLICY: "سياسة مخزون فعالة",
  OPEN_TRANSFER: "حوالة مفتوحة",
  ACTIVE_ROUTE_LOAD: "حمولة مسار فعالة",
  OPEN_STOCKTAKE: "جرد مفتوح",
  ACTIVE_INVENTORY_LOCK: "قفل مخزون فعال",
  OPEN_CUSTODY: "عهدة مندوب مفتوحة",
  OPEN_SHORTAGE: "طلب نقص مفتوح",
  ACTIVE_OFFER: "عرض فعال",
};

export function CatalogLifecyclePanel({ variant, locations, onVariantChanged, onVariantDeleted }: Props) {
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [preflight, setPreflight] = useState<ArchivePreflight | null>(null);
  const [assignments, setAssignments] = useState<ProductLocationAssignment[]>([]);
  const [assignmentsLoading, setAssignmentsLoading] = useState(false);
  const [locationId, setLocationId] = useState("");
  const [inboundEnabled, setInboundEnabled] = useState(true);
  const [outboundEnabled, setOutboundEnabled] = useState(true);

  const canReadAssignments = access.canAny("product_location.read");
  const canManageAssignments = access.canAny("product_location.manage");

  const loadAssignments = useCallback(async () => {
    if (!canReadAssignments) {
      setAssignments([]);
      return;
    }
    setAssignmentsLoading(true);
    try {
      const page = parseProductLocations(await authFetch(
        `/warehouse/product-locations?product_variant_id=${variant.id}&limit=200`,
      ));
      if (page.has_more) throw new Error("عدد روابط الصنف تجاوز الحد الآمن للواجهة.");
      setAssignments(page.items);
    } catch (error) {
      setAssignments([]);
      toast.error(apiErrorMessage(error, "تعذر جلب روابط الصنف بالمواقع."));
    } finally {
      setAssignmentsLoading(false);
    }
  }, [authFetch, canReadAssignments, variant.id]);

  useEffect(() => { void loadAssignments(); }, [loadAssignments]);
  useEffect(() => { setPreflight(null); setReason(""); }, [variant.id, variant.version]);

  const lifecycleCommand = async (command: string, extra: Record<string, unknown> = {}) => {
    setBusy(true);
    try {
      const payload = { ...buildLifecycleCommand(variant, reason), ...extra };
      if (command === "delete-draft") {
        const message = parseMutationMessage(await authFetch(`/catalog/variants/${variant.id}/${command}`, { method: "POST", body: JSON.stringify(payload) }));
        toast.success(message);
        await onVariantDeleted(variant.id);
        return;
      }
      const result = parseVariantMutation(await authFetch(`/catalog/variants/${variant.id}/${command}`, { method: "POST", body: JSON.stringify(payload) }));
      toast.success(result.message);
      setPreflight(null);
      setReason("");
      await onVariantChanged(result.variant);
    } catch (error) {
      toast.error(apiErrorMessage(error, "تعذر تنفيذ أمر دورة الحياة."));
    } finally {
      setBusy(false);
    }
  };

  const checkArchive = async () => {
    setBusy(true);
    try {
      const result = parseArchivePreflight(await authFetch(`/catalog/variants/${variant.id}/archive-preflight`));
      setPreflight(result);
      if (result.can_archive) toast.success("فحص الأرشفة ناجح؛ لا توجد موانع حالية.");
    } catch (error) {
      toast.error(apiErrorMessage(error, "تعذر فحص موانع الأرشفة."));
    } finally {
      setBusy(false);
    }
  };

  const createAssignment = async () => {
    const selected = Number(locationId);
    if (!Number.isSafeInteger(selected) || selected <= 0) {
      toast.error("اختر مستودعاً صالحاً.");
      return;
    }
    setBusy(true);
    try {
      const message = parseMutationMessage(await authFetch("/warehouse/product-locations", {
        method: "POST",
        body: JSON.stringify({ request_id: crypto.randomUUID(), location_id: selected, product_variant_id: variant.id, operational_flags: { inbound_enabled: inboundEnabled, outbound_enabled: outboundEnabled } }),
      }));
      toast.success(message);
      setLocationId("");
      await loadAssignments();
    } catch (error) {
      toast.error(apiErrorMessage(error, "تعذر ربط الصنف بالمستودع."));
    } finally {
      setBusy(false);
    }
  };

  const updateAssignment = async (assignment: ProductLocationAssignment, flag: "inbound_enabled" | "outbound_enabled", value: boolean) => {
    setBusy(true);
    try {
      const message = parseMutationMessage(await authFetch(`/warehouse/product-locations/${assignment.id}`, {
        method: "PATCH",
        body: JSON.stringify({ request_id: crypto.randomUUID(), expected_version: assignment.version, operational_flags: { ...assignment.operational_flags, [flag]: value } }),
      }));
      toast.success(message);
      await loadAssignments();
    } catch (error) {
      toast.error(apiErrorMessage(error, "تعذر تحديث تشغيل الصنف في المستودع."));
    } finally {
      setBusy(false);
    }
  };

  const removeAssignment = async (assignment: ProductLocationAssignment) => {
    setBusy(true);
    try {
      const message = parseMutationMessage(await authFetch(`/warehouse/product-locations/${assignment.id}`, {
        method: "DELETE",
        body: JSON.stringify({ ...buildLifecycleCommand(variant, reason), expected_version: assignment.version }),
      }));
      toast.success(message);
      setReason("");
      await loadAssignments();
    } catch (error) {
      toast.error(apiErrorMessage(error, "تعذر حذف ربط الصنف بالمستودع."));
    } finally {
      setBusy(false);
    }
  };

  const assignedIds = new Set(assignments.map((item) => item.location.id));
  const availableLocations = locations.filter((item) => !assignedIds.has(item.id));
  const actionClass = "rounded-lg border px-3 py-2 text-xs font-black disabled:cursor-not-allowed disabled:opacity-40";

  return <div className="space-y-4">
    <section className="rounded-xl border border-slate-200 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-black text-slate-800">دورة الحياة والإيقاف التشغيلي</h3>
          <p className="mt-1 text-xs font-bold text-slate-500">الحالة: {variant.lifecycle_status} · الإيقاف: {variant.operational_hold} · الإصدار: {variant.version}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {variant.lifecycle_status === "DRAFT" && access.can("catalog.publish") && <button className={actionClass} disabled={busy} onClick={() => void lifecycleCommand("publish")}><PlayCircle className="ml-1 inline h-4 w-4"/>نشر</button>}
          {variant.lifecycle_status === "DRAFT" && access.can("catalog.manage") && <button className={`${actionClass} border-red-200 text-red-700`} disabled={busy} onClick={() => void lifecycleCommand("delete-draft")}><Trash2 className="ml-1 inline h-4 w-4"/>حذف المسودة</button>}
          {variant.lifecycle_status === "ACTIVE" && access.can("catalog.retire") && <button className={actionClass} disabled={busy} onClick={() => void lifecycleCommand("retire")}><PauseCircle className="ml-1 inline h-4 w-4"/>بدء التقاعد</button>}
          {(["RETIRING", "ARCHIVED"] as const).includes(variant.lifecycle_status as "RETIRING" | "ARCHIVED") && access.can("catalog.restore") && <button className={actionClass} disabled={busy} onClick={() => void lifecycleCommand("restore")}><PlayCircle className="ml-1 inline h-4 w-4"/>استعادة</button>}
          {variant.lifecycle_status === "RETIRING" && access.can("catalog.archive") && <button className={actionClass} disabled={busy} onClick={() => void checkArchive()}><Archive className="ml-1 inline h-4 w-4"/>فحص الأرشفة</button>}
          {variant.lifecycle_status === "RETIRING" && preflight?.can_archive && access.can("catalog.archive") && <button className={`${actionClass} bg-slate-800 text-white`} disabled={busy} onClick={() => void lifecycleCommand("archive")}><Archive className="ml-1 inline h-4 w-4"/>أرشفة نهائية</button>}
          {variant.operational_hold === "NONE" && ["ACTIVE", "RETIRING"].includes(variant.lifecycle_status) && access.can("catalog.hold") && <button className={`${actionClass} border-amber-200 text-amber-700`} disabled={busy} onClick={() => void lifecycleCommand("sales-hold")}><AlertTriangle className="ml-1 inline h-4 w-4"/>إيقاف بيع</button>}
          {variant.operational_hold === "SALES_HOLD" && access.can("catalog.hold") && <button className={actionClass} disabled={busy} onClick={() => void lifecycleCommand("release-sales-hold")}><PlayCircle className="ml-1 inline h-4 w-4"/>تحرير الإيقاف</button>}
          {["NONE", "SALES_HOLD"].includes(variant.operational_hold) && ["ACTIVE", "RETIRING"].includes(variant.lifecycle_status) && access.can("catalog.hold") && <button className={`${actionClass} border-red-200 text-red-700`} disabled={busy} onClick={() => void lifecycleCommand("recall")}><ShieldAlert className="ml-1 inline h-4 w-4"/>استدعاء</button>}
          {variant.operational_hold === "RECALL" && access.can("catalog.hold") && <button className={actionClass} disabled={busy} onClick={() => void lifecycleCommand("close-recall", { target_hold: "NONE" })}>إغلاق الاستدعاء</button>}
        </div>
      </div>
      <label className="mt-3 block text-xs font-bold text-slate-600">سبب الإجراء<input value={reason} maxLength={1000} onChange={(event) => setReason(event.target.value)} placeholder="سبب واضح لا يقل عن 3 أحرف" className="mt-1 w-full rounded-lg border p-2"/></label>
      {preflight && !preflight.can_archive && <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs font-bold text-amber-900"><p>الأرشفة متوقفة حتى معالجة الموانع التالية:</p><ul className="mt-2 space-y-1">{preflight.blockers.map((item) => <li key={item.code}>{BLOCKER_LABELS[item.code] ?? item.code}: {item.count}{item.sample_id ? ` · مثال #${item.sample_id}` : ""}</li>)}</ul></div>}
    </section>

    {canReadAssignments && <section className="rounded-xl border border-slate-200 p-4">
      <h3 className="font-black text-slate-800"><Link2 className="ml-1 inline h-4 w-4"/>تهيئة الصنف للمستودعات</h3>
      <p className="mt-1 text-xs font-bold text-slate-500">الربط لا ينشئ رصيداً أو سياسة مخزون.</p>
      <div className="mt-3 space-y-2">
        {assignmentsLoading && <p className="text-xs text-slate-400">جارٍ تحميل الروابط...</p>}
        {!assignmentsLoading && !assignments.length && <p className="text-xs text-slate-400">الصنف غير مهيأ لأي مستودع.</p>}
        {assignments.map((assignment) => <div key={assignment.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-slate-50 p-3 text-xs font-bold">
          <span>{assignment.location.name} <span className="font-mono text-slate-400">{assignment.location.code}</span></span>
          <div className="flex items-center gap-3">
            <label><input type="checkbox" checked={assignment.operational_flags.inbound_enabled} disabled={busy || !canManageAssignments} onChange={(event) => void updateAssignment(assignment, "inbound_enabled", event.target.checked)}/> استلام</label>
            <label><input type="checkbox" checked={assignment.operational_flags.outbound_enabled} disabled={busy || !canManageAssignments} onChange={(event) => void updateAssignment(assignment, "outbound_enabled", event.target.checked)}/> صرف</label>
            {canManageAssignments && <button type="button" disabled={busy} className="text-red-600 disabled:opacity-40" onClick={() => void removeAssignment(assignment)}><Trash2 className="h-4 w-4"/></button>}
          </div>
        </div>)}
      </div>
      {canManageAssignments && variant.lifecycle_status === "ACTIVE" && availableLocations.length > 0 && <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto_auto_auto]">
        <select value={locationId} onChange={(event) => setLocationId(event.target.value)} className="rounded-lg border p-2 text-xs font-bold"><option value="">اختر مستودعاً...</option>{availableLocations.map((location) => <option key={location.id} value={location.id}>{location.code} — {location.name}</option>)}</select>
        <label className="self-center text-xs font-bold"><input type="checkbox" checked={inboundEnabled} onChange={(event) => setInboundEnabled(event.target.checked)}/> استلام</label>
        <label className="self-center text-xs font-bold"><input type="checkbox" checked={outboundEnabled} onChange={(event) => setOutboundEnabled(event.target.checked)}/> صرف</label>
        <button type="button" disabled={busy || !locationId} onClick={() => void createAssignment()} className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-black text-white disabled:opacity-40">ربط</button>
      </div>}
    </section>}
  </div>;
}
