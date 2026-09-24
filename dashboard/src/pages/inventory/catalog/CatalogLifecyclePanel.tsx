import { useCallback, useEffect, useState } from "react";
import { Link2, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import {
  buildLifecycleCommand,
  parseMutationMessage,
  parseProductLocations,
  type CatalogVariant,
  type ProductLocationAssignment,
} from "./contracts";
import { CatalogLifecycleActions } from "./CatalogLifecycleActions";

interface LocationOption { id: number; code: string; name: string }
interface Props {
  variant: CatalogVariant;
  locations: LocationOption[];
  onVariantChanged: (variant: CatalogVariant) => void | Promise<void>;
  onVariantDeleted: (variantId: number) => void | Promise<void>;
}

export function CatalogLifecyclePanel({ variant, locations, onVariantChanged, onVariantDeleted }: Props) {
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const [assignmentReason, setAssignmentReason] = useState("");
  const [busy, setBusy] = useState(false);
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
        body: JSON.stringify({ ...buildLifecycleCommand(variant, assignmentReason), expected_version: assignment.version }),
      }));
      toast.success(message);
      setAssignmentReason("");
      await loadAssignments();
    } catch (error) {
      toast.error(apiErrorMessage(error, "تعذر حذف ربط الصنف بالمستودع."));
    } finally {
      setBusy(false);
    }
  };

  const assignedIds = new Set(assignments.map((item) => item.location.id));
  const availableLocations = locations.filter((item) => !assignedIds.has(item.id));
  return <div className="space-y-4">
    <CatalogLifecycleActions
      variant={variant}
      onVariantChanged={onVariantChanged}
      onVariantDeleted={onVariantDeleted}
    />

    {canReadAssignments && <section className="rounded-xl border border-slate-200 p-4">
      <h3 className="font-black text-slate-800"><Link2 className="ml-1 inline h-4 w-4"/>تهيئة الصنف للمستودعات</h3>
      <p className="mt-1 text-xs font-bold text-slate-500">الربط لا ينشئ رصيداً أو سياسة مخزون.</p>
      {canManageAssignments && assignments.length > 0 && <label className="mt-3 block text-xs font-bold text-slate-600">سبب إزالة الربط<input value={assignmentReason} maxLength={1000} onChange={(event) => setAssignmentReason(event.target.value)} placeholder="مطلوب فقط عند إزالة ربط قائم" className="mt-1 w-full rounded-lg border p-2"/></label>}
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
