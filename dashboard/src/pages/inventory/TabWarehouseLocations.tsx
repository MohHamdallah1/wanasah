import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Building2, ChevronLeft, ChevronRight, GitBranch, Pencil, Plus, Power, PowerOff, RefreshCcw, Search } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import { apiErrorMessage } from "@/lib/apiErrors";
import { useAuthFetch } from "@/hooks/useAuthFetch";

import { useInventoryAccess, useLocationCapabilities } from "@/hooks/useInventoryAccess";
import { BranchManagementModal } from "./warehouse-locations/BranchManagementModal";
import { BranchSelector } from "./warehouse-locations/BranchSelector";

interface WarehouseLocationItem {
  id: number;
  name: string;
  code: string;
  branch_id: number | null;
  branch_name: string | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

interface WarehouseLocationCursorPage {
  items: WarehouseLocationItem[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
}

interface WarehouseLocationMutationResponse {
  message: string;
  location: WarehouseLocationItem;
}

interface WarehouseFormState {
  name: string;
  code: string;
  branch_id: number | null;
}

interface Props {
  onLocationsChanged: () => void | Promise<void>;
}

type FormMode = "create" | "edit";
type StateAction = "activate" | "deactivate";

const WAREHOUSE_CODE_RE = /^[A-Z0-9][A-Z0-9_-]*$/;

type WarehouseLocationContractError = Error & { code: string };

const warehouseLocationContractError = (code: string): never => {
  const error = new Error(code) as WarehouseLocationContractError;
  error.code = code;
  throw error;
};

const asWarehousePage = (value: unknown): WarehouseLocationCursorPage => {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value)
  ) {
    warehouseLocationContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
  }

  const page = value as Record<string, unknown>;
  const rawItems = page.items;
  if (!Array.isArray(rawItems) || rawItems.length > 200) {
    warehouseLocationContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
  }

  const items: WarehouseLocationItem[] = rawItems.map((raw) => {
    if (
      typeof raw !== "object" ||
      raw === null ||
      Array.isArray(raw)
    ) {
      warehouseLocationContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
    }

    const row = raw as Record<string, unknown>;
    const id = row.id;
    const name = row.name;
    const code = row.code;
    const branchId = row.branch_id;
    const branchName = row.branch_name;
    const isActive = row.is_active;
    const version = row.version;
    const createdAt = row.created_at;
    const updatedAt = row.updated_at;

    if (
      typeof id !== "number" ||
      !Number.isSafeInteger(id) ||
      id <= 0 ||
      typeof name !== "string" ||
      !name.trim() ||
      typeof code !== "string" ||
      !code.trim() ||
      (
        branchId !== null &&
        (
          typeof branchId !== "number" ||
          !Number.isSafeInteger(branchId) ||
          branchId <= 0
        )
      ) ||
      (
        branchName !== null &&
        typeof branchName !== "string"
      ) ||
      typeof isActive !== "boolean" ||
      typeof version !== "number" ||
      !Number.isSafeInteger(version) ||
      version <= 0 ||
      typeof createdAt !== "string" ||
      !createdAt.trim() ||
      typeof updatedAt !== "string" ||
      !updatedAt.trim()
    ) {
      warehouseLocationContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
    }

    return {
      id: id as number,
      name: name as string,
      code: code as string,
      branch_id: branchId as number | null,
      branch_name: branchName as string | null,
      is_active: isActive as boolean,
      version: version as number,
      created_at: createdAt as string,
      updated_at: updatedAt as string,
    };
  });

  const nextCursor =
    typeof page.next_cursor === "string"
      ? page.next_cursor
      : page.next_cursor === null
        ? null
        : warehouseLocationContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
  const hasMore = page.has_more;
  if (
    typeof hasMore !== "boolean" ||
    hasMore !== (nextCursor !== null)
  ) {
    warehouseLocationContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
  }

  const total = page.total === null
    ? null
    : typeof page.total === "number" &&
        Number.isSafeInteger(page.total) &&
        page.total >= 0
      ? page.total
      : warehouseLocationContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");

  return {
    items,
    next_cursor: nextCursor,
    has_more: hasMore as boolean,
    total,
  };
};

const asMutationResponse = (value: unknown): WarehouseLocationMutationResponse => {
  if (
    typeof value !== "object" ||
    value === null ||
    typeof (value as { message?: unknown }).message !== "string" ||
    typeof (value as { location?: unknown }).location !== "object" ||
    (value as { location?: unknown }).location === null
  ) {
    warehouseLocationContractError("WAREHOUSE_LOCATION_MUTATION_RESPONSE_INVALID");
  }
  return value as WarehouseLocationMutationResponse;
};

export function TabWarehouseLocations({ onLocationsChanged }: Props) {
  const authenticatedFetch = useAuthFetch();
  const { t } = useTranslation();

  const [items, setItems] = useState<WarehouseLocationItem[]>([]);
  const access = useInventoryAccess();
  const canAt = useLocationCapabilities(items.map(item => item.id));
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const requestSeq = useRef(0);

  const [formOpen, setFormOpen] = useState(false);
  const [formMode, setFormMode] = useState<FormMode>("create");
  const [editingLocation, setEditingLocation] = useState<WarehouseLocationItem | null>(null);
  const [form, setForm] = useState<WarehouseFormState>({ name: "", code: "", branch_id: null });
  const [formRequestId, setFormRequestId] = useState(() => crypto.randomUUID());
  const [formSubmitting, setFormSubmitting] = useState(false);
  const [branchManagerOpen, setBranchManagerOpen] = useState(false);
  const [branchRefreshKey, setBranchRefreshKey] = useState(0);

  const [stateAction, setStateAction] = useState<StateAction | null>(null);
  const [stateLocation, setStateLocation] = useState<WarehouseLocationItem | null>(null);
  const [stateReason, setStateReason] = useState("");
  const [stateRequestId, setStateRequestId] = useState(() => crypto.randomUUID());
  const [stateSubmitting, setStateSubmitting] = useState(false);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      const clean = searchInput.trim();
      setSearch(clean.length >= 2 ? clean : "");
      setCursor(null);
      setCursorHistory([]);
      setNextCursor(null);
    }, 300);
    return () => window.clearTimeout(timeoutId);
  }, [searchInput]);

  const fetchPage = useCallback(async () => {
    const seq = ++requestSeq.current;
    setLoading(true);
    try {
      const params = new URLSearchParams({ include_inactive: "true", limit: "50" });
      if (cursor) params.set("cursor", cursor);
      if (search) params.set("search", search);

      const raw = await authenticatedFetch(`/warehouse/locations/manage?${params.toString()}`);
      if (seq !== requestSeq.current) return;

      const page = asWarehousePage(raw);
      setItems(page.items);
      setNextCursor(page.next_cursor);
      if (page.total !== null) setTotal(page.total);
    } catch (error: unknown) {
      if (seq !== requestSeq.current) return;
      setItems([]);
      setNextCursor(null);
      toast.error(apiErrorMessage(error, t("inventoryWarehouses.errors.loadFailed")));
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [authenticatedFetch, cursor, search, t]);

  useEffect(() => {
    void fetchPage();
  }, [fetchPage, refreshKey]);

  const activeCount = useMemo(
    () => items.filter((item) => item.is_active).length,
    [items]
  );

  const resetToFirstPageAndRefresh = useCallback(() => {
    setCursor(null);
    setCursorHistory([]);
    setNextCursor(null);
    setRefreshKey((value) => value + 1);
  }, []);

  const openCreate = () => {
    setFormMode("create");
    setEditingLocation(null);
    setForm({ name: "", code: "", branch_id: null });
    setFormRequestId(crypto.randomUUID());
    setFormOpen(true);
  };

  const openEdit = (location: WarehouseLocationItem) => {
    setFormMode("edit");
    setEditingLocation(location);
    setForm({ name: location.name, code: location.code, branch_id: location.branch_id });
    setFormRequestId(crypto.randomUUID());
    setFormOpen(true);
  };

  const updateForm = (patch: Partial<WarehouseFormState>) => {
    setForm((prev) => ({ ...prev, ...patch }));
    setFormRequestId(crypto.randomUUID());
  };

  const handleSave = async () => {
    if (formMode === 'create' ? !access.can('location.create') :
        !editingLocation || !canAt(editingLocation.id, 'location.update')) return;
    const name = form.name.trim();
    const code = form.code.trim().toUpperCase();

    if (!name || name.length > 150) {
      toast.error(t("inventoryWarehouses.errors.nameInvalid"));
      return;
    }
    if (!code || code.length > 50 || !WAREHOUSE_CODE_RE.test(code)) {
      toast.error(t("inventoryWarehouses.errors.codeInvalid"));
      return;
    }
    if (code === "TRANSIT-SYS") {
      toast.error(t("inventoryWarehouses.errors.systemCodeReserved"));
      return;
    }
    if (
      formMode === "edit" &&
      editingLocation &&
      editingLocation.name === name &&
      editingLocation.code === code &&
      editingLocation.branch_id === form.branch_id
    ) {
      toast.info(t("inventoryWarehouses.noChanges"));
      return;
    }

    setFormSubmitting(true);
    try {
      const mutationBody: Record<string, unknown> = {
        request_id: formRequestId,
        name,
        code,
      };
      if (formMode === "edit" && editingLocation) {
        mutationBody.expected_version = editingLocation.version;
      }
      if (formMode === "create" || editingLocation?.branch_id !== form.branch_id) {
        mutationBody.branch_id = form.branch_id;
      }

      const raw = await authenticatedFetch(
        formMode === "create"
          ? "/warehouse/locations"
          : `/warehouse/locations/${editingLocation?.id}`,
        {
          method: formMode === "create" ? "POST" : "PATCH",
          body: JSON.stringify(mutationBody),
        }
      );

      const response = asMutationResponse(raw);
      toast.success(response.message);
      setFormOpen(false);
      if (formMode === "create") resetToFirstPageAndRefresh();
      else setRefreshKey((value) => value + 1);
      await onLocationsChanged();
    } catch (error: unknown) {
      toast.error(apiErrorMessage(error, t("inventoryWarehouses.errors.saveFailed")));
    } finally {
      setFormSubmitting(false);
    }
  };

  const openStateAction = (location: WarehouseLocationItem, action: StateAction) => {
    setStateLocation(location);
    setStateAction(action);
    setStateReason("");
    setStateRequestId(crypto.randomUUID());
  };

  const handleStateChange = async () => {
    if (!stateLocation || !stateAction || !canAt(stateLocation.id, 'location.state')) return;

    const reason = stateReason.trim();
    if (stateAction === "deactivate" && !reason) {
      toast.error(t("inventoryWarehouses.errors.deactivationReasonRequired"));
      return;
    }
    if (reason.length > 1000) {
      toast.error(t("inventoryWarehouses.errors.reasonTooLong"));
      return;
    }

    setStateSubmitting(true);
    try {
      const raw = await authenticatedFetch(
        `/warehouse/locations/${stateLocation.id}/${stateAction}`,
        {
          method: "POST",
          body: JSON.stringify({
            request_id: stateRequestId,
            expected_version: stateLocation.version,
            reason: reason || null,
          }),
        }
      );

      const response = asMutationResponse(raw);
      toast.success(response.message);
      setStateAction(null);
      setStateLocation(null);
      setRefreshKey((value) => value + 1);
      await onLocationsChanged();
    } catch (error: unknown) {
      toast.error(
        apiErrorMessage(
          error,
          t(
            "inventoryWarehouses.errors.stateFailed"
          )
        )
      );
    } finally {
      setStateSubmitting(false);
    }
  };

  const handleNext = () => {
    if (!nextCursor) return;
    setCursorHistory((prev) => [...prev, cursor]);
    setCursor(nextCursor);
  };

  const handlePrevious = () => {
    if (cursorHistory.length === 0) return;
    const previous = cursorHistory[cursorHistory.length - 1] ?? null;
    setCursorHistory((prev) => prev.slice(0, -1));
    setCursor(previous);
  };

  return (
    <div className="inventory-view inventory-locations flex flex-col gap-4 min-h-0 flex-1">
      <div className="glass-card inventory-section-header rounded-2xl p-4 flex items-center justify-between gap-4">
        <div>
          <h2 className="font-black text-slate-800 flex items-center gap-2">
            <Building2 className="w-5 h-5 text-blue-600" />
            إدارة المستودعات
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            {total !== null ? `${total} مستودع` : "—"} · {activeCount} فعال في الصفحة الحالية
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {access.isCompanyAdmin && (
            <button
              type="button"
              onClick={() => setBranchManagerOpen(true)}
              className="px-4 py-2 rounded-xl border border-slate-200 bg-white text-slate-700 font-bold text-sm flex items-center gap-2"
            >
              <GitBranch className="w-4 h-4" />
              إدارة الفروع
            </button>
          )}
          <button
            onClick={() => setRefreshKey((value) => value + 1)}
            disabled={loading}
            className="px-3 py-2 rounded-xl border border-slate-200 bg-white text-slate-600 font-bold text-xs disabled:opacity-50"
            title="تحديث"
          >
            <RefreshCcw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </button>
          <button
            disabled={!access.can("location.create")}
            onClick={openCreate}
            className="px-4 py-2 rounded-xl bg-blue-600 text-white font-bold text-sm flex items-center gap-2"
          >
            <Plus className="w-4 h-4" />
            مستودع جديد
          </button>
        </div>
      </div>

      <div className="glass-card inventory-toolbar rounded-2xl p-4">
        <div className="relative">
          <Search className="w-4 h-4 absolute right-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="بحث بالاسم أو الكود (حرفان على الأقل)"
            maxLength={100}
            className="w-full pr-10 pl-3 py-2.5 rounded-xl border border-slate-200 bg-white text-sm outline-none focus:ring-2 focus:ring-blue-500/20"
          />
        </div>
      </div>

      <div className="glass-card inventory-data-panel rounded-2xl overflow-hidden min-h-0 flex-1">
        <div className="overflow-auto h-full">
          <table className="w-full text-sm text-right">
            <thead className="bg-slate-50 sticky top-0 z-10">
              <tr>
                <th className="p-3">المستودع</th>
                <th className="p-3">الكود</th>
                <th className="p-3">الفرع</th>
                <th className="p-3">الحالة</th>
                <th className="p-3">آخر تحديث</th>
                <th className="p-3 text-center">إجراءات</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((location) => (
                <tr key={location.id} className="hover:bg-slate-50/70">
                  <td className="p-3 font-bold text-slate-800">{location.name}</td>
                  <td className="p-3 font-mono text-xs text-slate-600">{location.code}</td>
                  <td className="p-3 text-slate-600">{location.branch_name || "غير مرتبط"}</td>
                  <td className="p-3">
                    <span className={`px-2 py-1 rounded-lg text-xs font-bold ${
                      location.is_active
                        ? "bg-emerald-50 text-emerald-700"
                        : "bg-slate-100 text-slate-500"
                    }`}>
                      {location.is_active ? "فعال" : "متوقف"}
                    </span>
                  </td>
                  <td className="p-3 text-xs text-slate-500">
                    {new Date(location.updated_at).toLocaleString("ar-EG")}
                  </td>
                  <td className="p-3">
                    <div className="flex justify-center gap-2">
                      <button
                        disabled={!canAt(location.id, "location.update")}
                        onClick={() => openEdit(location)}
                        className="p-2 rounded-lg border border-slate-200 text-slate-600 hover:text-blue-600"
                        title="تعديل"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>

                      {location.is_active ? (
                        <button
                          disabled={!canAt(location.id, "location.state")}
                          onClick={() => openStateAction(location, "deactivate")}
                          className="p-2 rounded-lg border border-red-200 text-red-600 hover:bg-red-50"
                          title="تعطيل"
                        >
                          <PowerOff className="w-4 h-4" />
                        </button>
                      ) : (
                        <button
                          disabled={!canAt(location.id, "location.state")}
                          onClick={() => openStateAction(location, "activate")}
                          className="p-2 rounded-lg border border-emerald-200 text-emerald-600 hover:bg-emerald-50"
                          title="تفعيل"
                        >
                          <Power className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}

              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={6} className="p-12 text-center text-slate-400">
                    {search
                      ? "لا توجد مستودعات مطابقة للبحث."
                      : access.can("location.create")
                        ? "لم تُنشئ الشركة أي مستودع بعد. ابدأ بإنشاء مستودع من زر الإضافة."
                        : "لا توجد مستودعات متاحة لحسابك."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-500">الصفحة {cursorHistory.length + 1}</span>
        <div className="flex gap-2">
          <button
            onClick={handlePrevious}
            disabled={cursorHistory.length === 0 || loading}
            className="px-3 py-2 rounded-xl border border-slate-200 bg-white disabled:opacity-40"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
          <button
            onClick={handleNext}
            disabled={!nextCursor || loading}
            className="px-3 py-2 rounded-xl border border-slate-200 bg-white disabled:opacity-40"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
        </div>
      </div>

      <Modal
        isOpen={formOpen}
        onClose={() => {
          if (!formSubmitting) setFormOpen(false);
        }}
        title={formMode === "create" ? "إضافة مستودع" : "تعديل المستودع"}
      >
        <div className="space-y-4">
          <div>
            <label className="text-xs font-bold text-slate-600">اسم المستودع</label>
            <input
              value={form.name}
              onChange={(event) => updateForm({ name: event.target.value })}
              maxLength={150}
              className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5 outline-none focus:ring-2 focus:ring-blue-500/20"
            />
          </div>

          <div>
            <label className="text-xs font-bold text-slate-600">كود المستودع</label>
            <input
              value={form.code}
              onChange={(event) => updateForm({ code: event.target.value.toUpperCase() })}
              maxLength={50}
              dir="ltr"
              className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5 font-mono outline-none focus:ring-2 focus:ring-blue-500/20"
              placeholder="AMMAN-01"
            />
          </div>

          <BranchSelector
            value={form.branch_id}
            currentLabel={editingLocation?.branch_name ?? null}
            disabled={formSubmitting}
            refreshKey={branchRefreshKey}
            onChange={(branchId) => updateForm({ branch_id: branchId })}
          />

          <button
            onClick={handleSave}
            disabled={formSubmitting}
            className="w-full py-3 rounded-xl bg-blue-600 text-white font-bold disabled:opacity-50"
          >
            {formSubmitting ? t("common.saving") : t("common.save")}
          </button>
        </div>
      </Modal>

      {access.isCompanyAdmin && (
        <BranchManagementModal
          isOpen={branchManagerOpen}
          onClose={() => setBranchManagerOpen(false)}
          onBranchesChanged={async () => {
            setBranchRefreshKey((value) => value + 1);
            setRefreshKey((value) => value + 1);
            await onLocationsChanged();
          }}
        />
      )}

      <Modal
        isOpen={stateAction !== null && stateLocation !== null}
        onClose={() => {
          if (!stateSubmitting) {
            setStateAction(null);
            setStateLocation(null);
          }
        }}
        title={stateAction === "deactivate" ? "تعطيل المستودع" : "تفعيل المستودع"}
      >
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            المستودع: <span className="font-bold">{stateLocation?.name}</span>
          </p>

          <div>
            <label className="text-xs font-bold text-slate-600">
              {stateAction === "deactivate"
                ? "سبب التعطيل - إجباري"
                : "ملاحظة التفعيل - اختيارية"}
            </label>
            <textarea
              value={stateReason}
              onChange={(event) => {
                setStateReason(event.target.value);
                setStateRequestId(crypto.randomUUID());
              }}
              maxLength={1000}
              className="mt-1 w-full min-h-28 rounded-xl border border-slate-200 px-3 py-2.5 outline-none focus:ring-2 focus:ring-blue-500/20"
            />
          </div>

          <button
            onClick={handleStateChange}
            disabled={stateSubmitting}
            className={`w-full py-3 rounded-xl text-white font-bold disabled:opacity-50 ${
              stateAction === "deactivate" ? "bg-red-600" : "bg-emerald-600"
            }`}
          >
            {stateSubmitting
              ? t("inventoryWarehouses.processing")
              : stateAction === "deactivate"
                ? "تأكيد التعطيل"
                : "تأكيد التفعيل"}
          </button>
        </div>
      </Modal>
    </div>
  );
}
