import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Building2, ChevronLeft, ChevronRight, GitBranch, Pencil, Plus, Power, PowerOff, RefreshCcw, Search } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import { apiErrorCode, apiErrorContext, apiErrorMessage } from "@/lib/apiErrors";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess, useLocationCapabilities } from "@/hooks/useInventoryAccess";
import { BranchManagementModal } from "./warehouse-locations/BranchManagementModal";
import { BranchSelector } from "./warehouse-locations/BranchSelector";
import { StockMinimumManager } from "./StockMinimumManager";
import { QualityHandlingDestinationsCard } from "./warehouse-locations/QualityHandlingDestinationsCard";
import {
  formatInventoryDateTime,
  formatInventoryInteger,
  formatWarehouseDeactivationBlocker,
  warehouseLocationsCopy,
  type WarehouseOperatorIssue,
} from "./warehouse-locations/i18n";

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
  selectedLocationId: number | null;
  onLocationsChanged: () => void | Promise<void>;
  onMinimumApplied: () => void;
}

type FormMode = "create" | "edit";
type StateAction = "activate" | "deactivate";

const WAREHOUSE_CODE_RE = /^[A-Z0-9][A-Z0-9_-]*$/;
const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30";

type WarehouseLocationContractError = Error & { code: string };

const warehouseLocationContractError = (code: string): never => {
  const error = new Error(code) as WarehouseLocationContractError;
  error.code = code;
  throw error;
};

const asWarehousePage = (value: unknown): WarehouseLocationCursorPage => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    warehouseLocationContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
  }

  const page = value as Record<string, unknown>;
  const rawItems: unknown[] = Array.isArray(page.items)
    ? page.items
    : warehouseLocationContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
  if (rawItems.length > 200) {
    warehouseLocationContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
  }

  const items: WarehouseLocationItem[] = rawItems.map((raw) => {
    if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
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
      (branchId !== null && (
        typeof branchId !== "number" ||
        !Number.isSafeInteger(branchId) ||
        branchId <= 0
      )) ||
      (branchName !== null && typeof branchName !== "string") ||
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

  const nextCursor = typeof page.next_cursor === "string"
    ? page.next_cursor
    : page.next_cursor === null
      ? null
      : warehouseLocationContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
  const hasMore = page.has_more;
  if (typeof hasMore !== "boolean" || hasMore !== (nextCursor !== null)) {
    warehouseLocationContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
  }

  const total = page.total === null
    ? null
    : typeof page.total === "number" && Number.isSafeInteger(page.total) && page.total >= 0
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

const contextNumber = (context: Record<string, unknown> | null, key: string) => {
  const value = context?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
};

export function TabWarehouseLocations({
  selectedLocationId,
  onLocationsChanged,
  onMinimumApplied,
}: Props) {
  const authenticatedFetch = useAuthFetch();
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage ?? i18n.language;
  const isArabic = (language ?? "").toLowerCase().startsWith("ar");
  const dir = i18n.dir();
  const copy = warehouseLocationsCopy(language);
  const loadFailedMessage = t("inventoryWarehouses.errors.loadFailed");

  const [items, setItems] = useState<WarehouseLocationItem[]>([]);
  const access = useInventoryAccess();
  const minimumStockAccess = useInventoryAccess(selectedLocationId);
  const canReadLocations = access.canAny("location.read");
  const canReadBranches = access.can("branch.read");
  const canAt = useLocationCapabilities(items.map((item) => item.id));
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
  const [formIssue, setFormIssue] = useState<string | null>(null);
  const [branchManagerOpen, setBranchManagerOpen] = useState(false);
  const [branchRefreshKey, setBranchRefreshKey] = useState(0);

  const [stateAction, setStateAction] = useState<StateAction | null>(null);
  const [stateLocation, setStateLocation] = useState<WarehouseLocationItem | null>(null);
  const [stateReason, setStateReason] = useState("");
  const [stateRequestId, setStateRequestId] = useState(() => crypto.randomUUID());
  const [stateSubmitting, setStateSubmitting] = useState(false);
  const [stateIssue, setStateIssue] = useState<WarehouseOperatorIssue | null>(null);

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
    if (!canReadLocations) {
      requestSeq.current += 1;
      setItems([]);
      setNextCursor(null);
      setTotal(null);
      setLoading(false);
      return;
    }
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
      toast.error(apiErrorMessage(error, loadFailedMessage));
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [authenticatedFetch, canReadLocations, cursor, loadFailedMessage, search]);

  useEffect(() => {
    void fetchPage();
  }, [fetchPage, refreshKey]);

  const activeCount = useMemo(
    () => items.filter((item) => item.is_active).length,
    [items],
  );

  const canManageMinimumStock =
    selectedLocationId !== null &&
    access.can("inventory.minimum_stock.manage") &&
    minimumStockAccess.can("inventory.read");

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
    setFormIssue(null);
    setFormRequestId(crypto.randomUUID());
    setFormOpen(true);
  };

  const openEdit = (location: WarehouseLocationItem) => {
    setFormMode("edit");
    setEditingLocation(location);
    setForm({ name: location.name, code: location.code, branch_id: location.branch_id });
    setFormIssue(null);
    setFormRequestId(crypto.randomUUID());
    setFormOpen(true);
  };

  const updateForm = (patch: Partial<WarehouseFormState>) => {
    setForm((prev) => ({ ...prev, ...patch }));
    setFormIssue(null);
    setFormRequestId(crypto.randomUUID());
  };

  const handleSave = async () => {
    if (formMode === "create" ? !access.can("location.create") :
        !editingLocation || !canAt(editingLocation.id, "location.update")) return;
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
    setFormIssue(null);
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
        },
      );

      const response = asMutationResponse(raw);
      toast.success(response.message);
      setFormOpen(false);
      if (formMode === "create") resetToFirstPageAndRefresh();
      else setRefreshKey((value) => value + 1);
      await onLocationsChanged();
    } catch (error: unknown) {
      const codeValue = apiErrorCode(error);
      const context = apiErrorContext(error);
      if (codeValue === "LOCATION_VERSION_CONFLICT" && editingLocation) {
        const currentVersion = contextNumber(context, "current_version");
        await fetchPage();
        if (currentVersion !== null) {
          setEditingLocation((current) => current ? { ...current, version: currentVersion } : current);
        }
        setFormRequestId(crypto.randomUUID());
        setFormIssue(copy.versionChanged);
        toast.error(copy.versionChanged);
      } else if (codeValue === "WAREHOUSE_BRANCH_NOT_FOUND") {
        setBranchRefreshKey((value) => value + 1);
        setFormRequestId(crypto.randomUUID());
        setFormIssue(copy.branchMissing);
        toast.error(copy.branchMissing);
      } else if (codeValue === "WAREHOUSE_BRANCH_INACTIVE") {
        setBranchRefreshKey((value) => value + 1);
        setFormRequestId(crypto.randomUUID());
        setFormIssue(copy.branchInactive);
        toast.error(copy.branchInactive);
      } else {
        toast.error(apiErrorMessage(error, t("inventoryWarehouses.errors.saveFailed")));
      }
    } finally {
      setFormSubmitting(false);
    }
  };

  const openStateAction = (location: WarehouseLocationItem, action: StateAction) => {
    setStateLocation(location);
    setStateAction(action);
    setStateReason("");
    setStateIssue(null);
    setStateRequestId(crypto.randomUUID());
  };

  const handleStateChange = async () => {
    if (!stateLocation || !stateAction || !canAt(stateLocation.id, "location.state")) return;

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
    setStateIssue(null);
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
        },
      );

      const response = asMutationResponse(raw);
      toast.success(response.message);
      setStateAction(null);
      setStateLocation(null);
      setStateIssue(null);
      setRefreshKey((value) => value + 1);
      await onLocationsChanged();
    } catch (error: unknown) {
      const codeValue = apiErrorCode(error);
      const context = apiErrorContext(error);
      if (codeValue === "LOCATION_DEACTIVATION_BLOCKED") {
        const issue = formatWarehouseDeactivationBlocker(context, language);
        setStateIssue(issue);
        toast.error(issue.title);
      } else if (codeValue === "LOCATION_VERSION_CONFLICT") {
        const currentVersion = contextNumber(context, "current_version");
        await fetchPage();
        if (currentVersion !== null) {
          setStateLocation((current) => current ? { ...current, version: currentVersion } : current);
        }
        setStateRequestId(crypto.randomUUID());
        const issue = { title: copy.versionChanged, details: [] };
        setStateIssue(issue);
        toast.error(issue.title);
      } else {
        toast.error(apiErrorMessage(error, t("inventoryWarehouses.errors.stateFailed")));
      }
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

  const totalText = total === null ? "—" : formatInventoryInteger(total, language);
  const activeText = formatInventoryInteger(activeCount, language);
  const pageText = formatInventoryInteger(cursorHistory.length + 1, language);

  return (
    <div dir={dir} className="inventory-view inventory-locations flex min-h-0 flex-1 flex-col gap-4">
      <div className="glass-card inventory-section-header flex flex-wrap items-center justify-between gap-4 rounded-2xl p-4">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 break-words font-black text-slate-800">
            <Building2 aria-hidden="true" className="h-5 w-5 shrink-0 text-blue-600" />
            {copy.title}
          </h2>
          <p className="mt-1 break-words text-xs text-slate-500">
            {copy.summary(totalText, activeText)}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {canManageMinimumStock && (
            <StockMinimumManager
              locationId={selectedLocationId}
              onApplied={onMinimumApplied}
            />
          )}
          {canReadBranches && (
            <button
              type="button"
              onClick={() => setBranchManagerOpen(true)}
              className={`flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-bold text-slate-700 ${focusRing}`}
            >
              <GitBranch aria-hidden="true" className="h-4 w-4" />
              <span className="break-words">{copy.manageBranches}</span>
            </button>
          )}
          <button
            type="button"
            onClick={() => setRefreshKey((value) => value + 1)}
            disabled={loading || !canReadLocations}
            className={`rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-600 disabled:opacity-50 ${focusRing}`}
            title={copy.refresh}
            aria-label={copy.refresh}
          >
            <RefreshCcw aria-hidden="true" className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
          <button
            type="button"
            disabled={!access.can("location.create")}
            onClick={openCreate}
            className={`flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-50 ${focusRing}`}
          >
            <Plus aria-hidden="true" className="h-4 w-4" />
            <span className="break-words">{copy.newWarehouse}</span>
          </button>
        </div>
      </div>

      <QualityHandlingDestinationsCard />

      <div className="glass-card inventory-toolbar rounded-2xl p-4">
        <div className="relative">
          <Search aria-hidden="true" className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            disabled={!canReadLocations}
            aria-label={copy.search}
            placeholder={copy.search}
            maxLength={100}
            className={`w-full rounded-xl border border-slate-200 bg-white py-2.5 ps-10 pe-3 text-sm outline-none disabled:opacity-50 ${focusRing}`}
          />
        </div>
      </div>

      <div className="glass-card inventory-data-panel min-h-0 flex-1 overflow-hidden rounded-2xl">
        <div className="h-full overflow-x-auto overflow-y-auto">
          <table className={`w-full min-w-[760px] text-sm ${isArabic ? "text-right" : "text-left"}`}>
            <thead className="sticky top-0 z-10 bg-slate-50">
              <tr>
                <th className="p-3">{copy.warehouse}</th>
                <th className="p-3">{copy.code}</th>
                <th className="p-3">{copy.branch}</th>
                <th className="p-3">{copy.status}</th>
                <th className="p-3">{copy.updated}</th>
                <th className="p-3 text-center">{copy.actions}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((location) => (
                <tr key={location.id} className="hover:bg-slate-50/70">
                  <td className="p-3 font-bold text-slate-800">{location.name}</td>
                  <td className="p-3 font-mono text-xs text-slate-600">{location.code}</td>
                  <td className="p-3 text-slate-600">{location.branch_name || copy.unassigned}</td>
                  <td className="p-3">
                    <span className={`rounded-lg px-2 py-1 text-xs font-bold ${
                      location.is_active
                        ? "bg-emerald-50 text-emerald-700"
                        : "bg-slate-100 text-slate-500"
                    }`}>
                      {location.is_active ? copy.active : copy.inactive}
                    </span>
                  </td>
                  <td className="p-3 text-xs text-slate-500">
                    {formatInventoryDateTime(location.updated_at, language)}
                  </td>
                  <td className="p-3">
                    <div className="flex justify-center gap-2">
                      <button
                        type="button"
                        disabled={!canAt(location.id, "location.update")}
                        onClick={() => openEdit(location)}
                        className={`rounded-lg border border-slate-200 p-2 text-slate-600 hover:text-blue-600 disabled:opacity-50 ${focusRing}`}
                        title={copy.editAction}
                        aria-label={`${copy.editAction}: ${location.name}`}
                      >
                        <Pencil aria-hidden="true" className="h-4 w-4" />
                      </button>

                      {location.is_active ? (
                        <button
                          type="button"
                          disabled={!canAt(location.id, "location.state")}
                          onClick={() => openStateAction(location, "deactivate")}
                          className={`rounded-lg border border-red-200 p-2 text-red-600 hover:bg-red-50 disabled:opacity-50 ${focusRing}`}
                          title={copy.deactivateAction}
                          aria-label={`${copy.deactivateAction}: ${location.name}`}
                        >
                          <PowerOff aria-hidden="true" className="h-4 w-4" />
                        </button>
                      ) : (
                        <button
                          type="button"
                          disabled={!canAt(location.id, "location.state")}
                          onClick={() => openStateAction(location, "activate")}
                          className={`rounded-lg border border-emerald-200 p-2 text-emerald-600 hover:bg-emerald-50 disabled:opacity-50 ${focusRing}`}
                          title={copy.activateAction}
                          aria-label={`${copy.activateAction}: ${location.name}`}
                        >
                          <Power aria-hidden="true" className="h-4 w-4" />
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
                      ? copy.emptySearch
                      : access.can("location.create")
                        ? copy.emptyCreate
                        : copy.emptyNoAccess}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="flex items-center justify-between gap-3">
        <span className="min-w-0 break-words text-xs text-slate-500">{copy.page(pageText)}</span>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={handlePrevious}
            disabled={cursorHistory.length === 0 || loading || !canReadLocations}
            className={`rounded-xl border border-slate-200 bg-white px-3 py-2 disabled:opacity-40 ${focusRing}`}
            title={copy.previous}
            aria-label={copy.previous}
          >
            {isArabic
              ? <ChevronRight aria-hidden="true" className="h-4 w-4" />
              : <ChevronLeft aria-hidden="true" className="h-4 w-4" />}
          </button>
          <button
            type="button"
            onClick={handleNext}
            disabled={!nextCursor || loading || !canReadLocations}
            className={`rounded-xl border border-slate-200 bg-white px-3 py-2 disabled:opacity-40 ${focusRing}`}
            title={copy.next}
            aria-label={copy.next}
          >
            {isArabic
              ? <ChevronLeft aria-hidden="true" className="h-4 w-4" />
              : <ChevronRight aria-hidden="true" className="h-4 w-4" />}
          </button>
        </div>
      </div>

      <Modal
        isOpen={formOpen}
        onClose={() => {
          if (!formSubmitting) setFormOpen(false);
        }}
        title={formMode === "create" ? copy.add : copy.edit}
      >
        <form
          className="space-y-4"
          dir={dir}
          onSubmit={(event) => {
            event.preventDefault();
            void handleSave();
          }}
        >
          <label className="block text-xs font-bold text-slate-600">
            {copy.name}
            <input
              autoFocus
              value={form.name}
              onChange={(event) => updateForm({ name: event.target.value })}
              maxLength={150}
              className={`mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5 outline-none ${focusRing}`}
            />
          </label>

          <label className="block text-xs font-bold text-slate-600">
            {copy.warehouseCode}
            <input
              value={form.code}
              onChange={(event) => updateForm({ code: event.target.value.toUpperCase() })}
              maxLength={50}
              dir="ltr"
              className={`mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5 font-mono outline-none ${focusRing}`}
              placeholder={copy.codePlaceholder}
            />
          </label>

          <BranchSelector
            value={form.branch_id}
            currentLabel={editingLocation?.branch_name ?? null}
            disabled={formSubmitting}
            refreshKey={branchRefreshKey}
            canReadBranches={canReadBranches}
            onChange={(branchId) => updateForm({ branch_id: branchId })}
          />

          {formIssue ? (
            <p role="alert" className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-900">
              {formIssue}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={formSubmitting}
            className={`w-full rounded-xl bg-blue-600 py-3 font-bold text-white disabled:opacity-50 ${focusRing}`}
          >
            {formSubmitting ? t("common.saving") : t("common.save")}
          </button>
        </form>
      </Modal>

      {canReadBranches && (
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
            setStateIssue(null);
          }
        }}
        title={stateAction === "deactivate" ? copy.deactivate : copy.activate}
      >
        <form
          className="space-y-4"
          dir={dir}
          onSubmit={(event) => {
            event.preventDefault();
            void handleStateChange();
          }}
        >
          <p className="break-words text-sm text-slate-600">
            {copy.warehouse}: <span className="font-bold">{stateLocation?.name}</span>
          </p>

          <label className="block text-xs font-bold text-slate-600">
            {stateAction === "deactivate" ? copy.deactivateReason : copy.activateNote}
            <textarea
              autoFocus
              value={stateReason}
              onChange={(event) => {
                setStateReason(event.target.value);
                setStateIssue(null);
                setStateRequestId(crypto.randomUUID());
              }}
              maxLength={1000}
              className={`mt-1 min-h-28 w-full rounded-xl border border-slate-200 px-3 py-2.5 outline-none ${focusRing}`}
            />
          </label>

          {stateIssue ? (
            <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-950">
              <p className="break-words font-black">{stateIssue.title}</p>
              {stateIssue.details.length ? (
                <ul className="mt-2 list-disc space-y-1 ps-5 font-semibold">
                  {stateIssue.details.map((detail) => <li key={detail}>{detail}</li>)}
                </ul>
              ) : null}
            </div>
          ) : null}

          <button
            type="submit"
            disabled={stateSubmitting}
            className={`w-full rounded-xl py-3 font-bold text-white disabled:opacity-50 ${focusRing} ${
              stateAction === "deactivate" ? "bg-red-600" : "bg-emerald-600"
            }`}
          >
            {stateSubmitting
              ? t("inventoryWarehouses.processing")
              : stateAction === "deactivate"
                ? copy.confirmDeactivate
                : copy.confirmActivate}
          </button>
        </form>
      </Modal>
    </div>
  );
}
