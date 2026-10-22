import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Building2, Pencil, Plus, Power, PowerOff, RefreshCcw, Search, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import { apiErrorCode, apiErrorContext, apiErrorMessage } from "@/lib/apiErrors";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess, useLocationCapabilities } from "@/hooks/useInventoryAccess";
import { StockMinimumManager } from "./StockMinimumManager";
import { QualityHandlingDestinationsCard } from "./warehouse-locations/QualityHandlingDestinationsCard";
import {
  formatInventoryDateTime,
  formatInventoryInteger,
  formatWarehouseDeactivationBlocker,
  warehouseLocationsCopy,
  type WarehouseOperatorIssue,
} from "./warehouse-locations/i18n";
import { warehousePresentationCopy } from "./warehouse-locations/presentationI18n";

interface WarehouseLocationItem {
  id: number;
  name: string;
  code: string;
  address: string | null;
  location_link: string | null;
  latitude: number | null;
  longitude: number | null;
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

interface WarehouseLocationCodeSuggestionResponse {
  code: string;
}

interface WarehouseFormState {
  name: string;
  code: string;
  address: string;
  location_link: string;
  latitude: string;
  longitude: string;
}

interface Props {
  selectedLocationId: number | null;
  onLocationsChanged: () => void | Promise<void>;
  onMinimumApplied: () => void;
}

type FormMode = "create" | "edit";
type StateAction = "activate" | "deactivate";
type FormFieldIssue = { field: "name" | "code" | "address" | "coordinates"; message: string } | null;

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
  if (rawItems.length > 200) warehouseLocationContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");

  const items: WarehouseLocationItem[] = rawItems.map((raw) => {
    if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
      warehouseLocationContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
    }
    const row = raw as Record<string, unknown>;
    const id = row.id;
    const name = row.name;
    const code = row.code;
    const address = row.address === undefined ? null : row.address;
    const locationLink = row.location_link === undefined ? null : row.location_link;
    const latitude = row.latitude === undefined ? null : row.latitude;
    const longitude = row.longitude === undefined ? null : row.longitude;
    const branchId = row.branch_id;
    const branchName = row.branch_name;
    const isActive = row.is_active;
    const version = row.version;
    const createdAt = row.created_at;
    const updatedAt = row.updated_at;

    if (
      typeof id !== "number" || !Number.isSafeInteger(id) || id <= 0 ||
      typeof name !== "string" || !name.trim() ||
      typeof code !== "string" || !code.trim() ||
      (address !== null && typeof address !== "string") ||
      (locationLink !== null && typeof locationLink !== "string") ||
      (latitude !== null && (typeof latitude !== "number" || !Number.isFinite(latitude) || latitude < -90 || latitude > 90)) ||
      (longitude !== null && (typeof longitude !== "number" || !Number.isFinite(longitude) || longitude < -180 || longitude > 180)) ||
      ((latitude === null) !== (longitude === null)) ||
      (branchId !== null && (typeof branchId !== "number" || !Number.isSafeInteger(branchId) || branchId <= 0)) ||
      (branchName !== null && typeof branchName !== "string") ||
      typeof isActive !== "boolean" ||
      typeof version !== "number" || !Number.isSafeInteger(version) || version <= 0 ||
      typeof createdAt !== "string" || !createdAt.trim() ||
      typeof updatedAt !== "string" || !updatedAt.trim()
    ) warehouseLocationContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");

    return {
      id: id as number,
      name: name as string,
      code: code as string,
      address: address as string | null,
      location_link: locationLink as string | null,
      latitude: latitude as number | null,
      longitude: longitude as number | null,
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
  return { items, next_cursor: nextCursor, has_more: hasMore as boolean, total };
};

const asMutationResponse = (value: unknown): WarehouseLocationMutationResponse => {
  if (
    typeof value !== "object" || value === null ||
    typeof (value as { message?: unknown }).message !== "string" ||
    typeof (value as { location?: unknown }).location !== "object" ||
    (value as { location?: unknown }).location === null
  ) warehouseLocationContractError("WAREHOUSE_LOCATION_MUTATION_RESPONSE_INVALID");
  return value as WarehouseLocationMutationResponse;
};

const asCodeSuggestion = (value: unknown): WarehouseLocationCodeSuggestionResponse => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    warehouseLocationContractError("WAREHOUSE_LOCATION_CODE_SUGGESTION_INVALID");
  }
  const code = (value as { code?: unknown }).code;
  if (typeof code !== "string" || !code.trim() || code.length > 50 || !WAREHOUSE_CODE_RE.test(code)) {
    warehouseLocationContractError("WAREHOUSE_LOCATION_CODE_SUGGESTION_INVALID");
  }
  return { code };
};

const contextNumber = (context: Record<string, unknown> | null, key: string) => {
  const value = context?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
};

export function TabWarehouseLocations({ selectedLocationId, onLocationsChanged, onMinimumApplied }: Props) {
  const authenticatedFetch = useAuthFetch();
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage ?? i18n.language;
  const isArabic = (language ?? "").toLowerCase().startsWith("ar");
  const dir = i18n.dir();
  const copy = warehouseLocationsCopy(language);
  const presentation = warehousePresentationCopy(language);
  const loadFailedMessage = t("inventoryWarehouses.errors.loadFailed");

  const [items, setItems] = useState<WarehouseLocationItem[]>([]);
  const access = useInventoryAccess();
  const canReadLocations = access.canAny("location.read");
  const canManageQualityDestinations = access.can("inventory.transfer_policy.manage");
  const canAt = useLocationCapabilities(items.map((item) => item.id));
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadIssue, setLoadIssue] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [qualityDestinationsOpen, setQualityDestinationsOpen] = useState(false);
  const requestSeq = useRef(0);
  const loadMoreRef = useRef<HTMLDivElement>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [formMode, setFormMode] = useState<FormMode>("create");
  const [editingLocation, setEditingLocation] = useState<WarehouseLocationItem | null>(null);
  const [form, setForm] = useState<WarehouseFormState>({ name: "", code: "", address: "", location_link: "", latitude: "", longitude: "" });
  const [formRequestId, setFormRequestId] = useState(() => crypto.randomUUID());
  const [formSubmitting, setFormSubmitting] = useState(false);
  const [formIssue, setFormIssue] = useState<string | null>(null);
  const [fieldIssue, setFieldIssue] = useState<FormFieldIssue>(null);
  const nameInputRef = useRef<HTMLInputElement>(null);
  const codeInputRef = useRef<HTMLInputElement>(null);
  const addressInputRef = useRef<HTMLTextAreaElement>(null);
  const latitudeInputRef = useRef<HTMLInputElement>(null);

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
      setLoadIssue(null);
      setLoading(false);
      return;
    }
    const seq = ++requestSeq.current;
    setLoading(true);
    setLoadIssue(null);
    try {
      const params = new URLSearchParams({ include_inactive: "true", limit: "50" });
      if (cursor) params.set("cursor", cursor);
      if (search) params.set("search", search);
      const raw = await authenticatedFetch(`/warehouse/locations/manage?${params.toString()}`);
      if (seq !== requestSeq.current) return;
      const page = asWarehousePage(raw);
      setItems((current) => {
        if (cursor === null) return page.items;
        const merged = new Map(current.map((item) => [item.id, item]));
        page.items.forEach((item) => merged.set(item.id, item));
        return Array.from(merged.values());
      });
      setNextCursor(page.next_cursor);
      if (page.total !== null) setTotal(page.total);
    } catch (error: unknown) {
      if (seq !== requestSeq.current) return;
      if (cursor === null) setItems([]);
      setNextCursor(null);
      const message = apiErrorMessage(error, loadFailedMessage) || presentation.listLoadFailed;
      setLoadIssue(message);
      toast.error(message);
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [authenticatedFetch, canReadLocations, cursor, loadFailedMessage, presentation.listLoadFailed, search]);

  useEffect(() => { void fetchPage(); }, [fetchPage, refreshKey]);
  useEffect(() => {
    if (!nextCursor || loading || typeof IntersectionObserver === "undefined") return;
    const target = loadMoreRef.current;
    if (!target) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) setCursor(nextCursor);
    }, { rootMargin: "240px 0px" });
    observer.observe(target);
    return () => observer.disconnect();
  }, [loading, nextCursor]);
  useEffect(() => {
    if (!canManageQualityDestinations) setQualityDestinationsOpen(false);
  }, [canManageQualityDestinations]);

  const activeCount = useMemo(() => items.filter((item) => item.is_active).length, [items]);
  const minimumStockLocations = items
    .filter(
      (item) =>
        item.is_active &&
        canAt(item.id, "inventory.minimum_stock.manage") &&
        canAt(item.id, "inventory.read"),
    )
    .map((item) => ({ id: item.id, name: item.name, code: item.code }));
  const showFirstWarehouseStart = canReadLocations && total === 0 && !loading && !loadIssue && !search && cursor === null && items.length === 0;

  const resetToFirstPageAndRefresh = useCallback(() => {
    setCursor(null);
    setNextCursor(null);
    setRefreshKey((value) => value + 1);
  }, []);

  const openCreate = () => {
    setFormMode("create");
    setEditingLocation(null);
    setForm({ name: "", code: "", address: "", location_link: "", latitude: "", longitude: "" });
    setFormIssue(null);
    setFieldIssue(null);
    setFormRequestId(crypto.randomUUID());
    setFormOpen(true);

    void (async () => {
      try {
        const raw = await authenticatedFetch("/warehouse/locations/code-suggestion");
        const suggestion = asCodeSuggestion(raw);
        setForm((current) => current.code.trim() ? current : { ...current, code: suggestion.code });
      } catch {
        // Code suggestion is a convenience only; manual code entry remains available.
      }
    })();
  };

  const openEdit = (location: WarehouseLocationItem) => {
    setFormMode("edit");
    setEditingLocation(location);
    setForm({
      name: location.name,
      code: location.code,
      address: location.address ?? "",
      location_link: location.location_link ?? "",
      latitude: location.latitude === null ? "" : String(location.latitude),
      longitude: location.longitude === null ? "" : String(location.longitude),
    });
    setFormIssue(null);
    setFieldIssue(null);
    setFormRequestId(crypto.randomUUID());
    setFormOpen(true);
  };

  const updateForm = (patch: Partial<WarehouseFormState>) => {
    setForm((prev) => ({ ...prev, ...patch }));
    setFormIssue(null);
    setFieldIssue(null);
    setFormRequestId(crypto.randomUUID());
  };

  const failField = (field: "name" | "code" | "address" | "coordinates", message: string) => {
    setFieldIssue({ field, message });
    window.requestAnimationFrame(() => {
      if (field === "name") nameInputRef.current?.focus();
      else if (field === "code") codeInputRef.current?.focus();
      else if (field === "address") addressInputRef.current?.focus();
      else latitudeInputRef.current?.focus();
    });
  };

  const handleSave = async () => {
    if (formMode === "create" ? !access.can("location.create") : !editingLocation || !canAt(editingLocation.id, "location.update")) return;
    const name = form.name.trim();
    const code = form.code.trim().toUpperCase();
    const address = form.address.trim();
    const locationLink = form.location_link.trim();
    const latitudeText = form.latitude.trim();
    const longitudeText = form.longitude.trim();
    const hasLatitude = latitudeText.length > 0;
    const hasLongitude = longitudeText.length > 0;
    const latitude = hasLatitude ? Number(latitudeText) : null;
    const longitude = hasLongitude ? Number(longitudeText) : null;

    if (!name || name.length > 150) return failField("name", t("inventoryWarehouses.errors.nameInvalid"));
    if (!code || code.length > 50 || !WAREHOUSE_CODE_RE.test(code)) return failField("code", t("inventoryWarehouses.errors.codeInvalid"));
    if (code === "TRANSIT-SYS") return failField("code", t("inventoryWarehouses.errors.systemCodeReserved"));
    if (formMode === "create" && (!address || address.length > 2000)) return failField("address", copy.addressRequired);
    if (address.length > 2000) return failField("address", copy.addressRequired);
    if (hasLatitude !== hasLongitude || (hasLatitude && (latitude === null || longitude === null || !Number.isFinite(latitude) || !Number.isFinite(longitude) || latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180))) {
      return failField("coordinates", copy.coordinatesInvalid);
    }

    if (
      formMode === "edit" && editingLocation &&
      editingLocation.name === name &&
      editingLocation.code === code &&
      (editingLocation.address ?? "") === address &&
      (editingLocation.location_link ?? "") === locationLink &&
      editingLocation.latitude === latitude &&
      editingLocation.longitude === longitude
    ) {
      toast.info(t("inventoryWarehouses.noChanges"));
      return;
    }

    setFormSubmitting(true);
    setFormIssue(null);
    setFieldIssue(null);
    try {
      const mutationBody: Record<string, unknown> = {
        request_id: formRequestId,
        name,
        code,
        address: address || null,
        location_link: locationLink || null,
        latitude,
        longitude,
      };
      if (formMode === "edit" && editingLocation) mutationBody.expected_version = editingLocation.version;
      const raw = await authenticatedFetch(
        formMode === "create" ? "/warehouse/locations" : `/warehouse/locations/${editingLocation?.id}`,
        { method: formMode === "create" ? "POST" : "PATCH", body: JSON.stringify(mutationBody) },
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
        if (currentVersion !== null) setEditingLocation((current) => current ? { ...current, version: currentVersion } : current);
        setFormRequestId(crypto.randomUUID());
        setFormIssue(copy.versionChanged);
        toast.error(copy.versionChanged);
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
      const raw = await authenticatedFetch(`/warehouse/locations/${stateLocation.id}/${stateAction}`, {
        method: "POST",
        body: JSON.stringify({ request_id: stateRequestId, expected_version: stateLocation.version, reason: reason || null }),
      });
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
        if (currentVersion !== null) setStateLocation((current) => current ? { ...current, version: currentVersion } : current);
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

  const totalText = total === null ? "—" : formatInventoryInteger(total, language);
  const activeText = formatInventoryInteger(activeCount, language);

  const rowActions = (location: WarehouseLocationItem) => (
    <div className="flex items-center justify-end gap-1.5">
      <button
        type="button"
        disabled={!canAt(location.id, "location.update")}
        onClick={() => openEdit(location)}
        className={`inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white p-2 text-xs font-bold text-slate-600 hover:text-blue-600 disabled:opacity-40 ${focusRing}`}
        title={copy.editAction}
        aria-label={`${copy.editAction}: ${location.name}`}
      >
        <Pencil aria-hidden="true" className="h-4 w-4" />
        <span className="md:hidden">{copy.editAction}</span>
      </button>
      {location.is_active ? (
        <button
          type="button"
          disabled={!canAt(location.id, "location.state")}
          onClick={() => openStateAction(location, "deactivate")}
          className={`inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-white p-2 text-xs font-bold text-red-700 hover:bg-red-50 disabled:opacity-40 ${focusRing}`}
          title={copy.deactivateAction}
          aria-label={`${copy.deactivateAction}: ${location.name}`}
        >
          <PowerOff aria-hidden="true" className="h-4 w-4" />
          <span className="md:hidden">{copy.deactivateAction}</span>
        </button>
      ) : (
        <button
          type="button"
          disabled={!canAt(location.id, "location.state")}
          onClick={() => openStateAction(location, "activate")}
          className={`inline-flex items-center gap-1.5 rounded-lg border border-emerald-200 bg-white p-2 text-xs font-bold text-emerald-700 hover:bg-emerald-50 disabled:opacity-40 ${focusRing}`}
          title={copy.activateAction}
          aria-label={`${copy.activateAction}: ${location.name}`}
        >
          <Power aria-hidden="true" className="h-4 w-4" />
          <span className="md:hidden">{copy.activateAction}</span>
        </button>
      )}
    </div>
  );

  const stateBadge = (location: WarehouseLocationItem) => (
    <span className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-bold ${location.is_active ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
      {location.is_active ? <Power aria-hidden="true" className="h-3.5 w-3.5" /> : <PowerOff aria-hidden="true" className="h-3.5 w-3.5" />}
      {location.is_active ? copy.active : copy.inactive}
    </span>
  );

  return (
    <div dir={dir} className="inventory-view inventory-locations flex h-full min-h-0 flex-1 flex-col gap-0">
      {showFirstWarehouseStart ? (
        <section
          data-testid="warehouse-first-empty"
          aria-labelledby="warehouse-first-empty-title"
          className="relative isolate flex min-h-[58vh] items-center justify-center overflow-hidden rounded-[28px] border border-slate-200/90 bg-[#fbfcfe] px-5 py-12 sm:px-8"
        >
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 opacity-[0.42]"
            style={{
              backgroundImage: "linear-gradient(to right, rgba(15,23,42,.055) 1px, transparent 1px), linear-gradient(to bottom, rgba(15,23,42,.055) 1px, transparent 1px)",
              backgroundSize: "28px 28px",
            }}
          />
          <div aria-hidden="true" className="pointer-events-none absolute inset-x-6 top-6 flex items-center justify-between text-[9px] font-black tracking-[0.22em] text-slate-300 sm:inset-x-9">
            <span>WH / 001</span>
            <span>00°00′</span>
          </div>
          <div className="relative mx-auto flex w-full max-w-[680px] flex-col items-center text-center">
            <div aria-hidden="true" className="relative mb-7 h-32 w-52 text-slate-700">
              <div className="absolute inset-x-4 bottom-2 h-[78px] border-x border-b-2 border-t border-slate-300 bg-white/90 shadow-[8px_8px_0_0_rgba(226,232,240,0.75)]">
                <div className="absolute inset-x-0 top-5 border-t border-dashed border-slate-200" />
                <div className="absolute bottom-0 start-1/2 h-11 w-12 -translate-x-1/2 border-x border-t-2 border-slate-500 bg-slate-50">
                  <div className="mx-auto mt-3 h-px w-5 bg-blue-500" />
                </div>
              </div>
              <div className="absolute start-1/2 top-2 h-8 w-px -translate-x-1/2 bg-blue-500" />
              <div className="absolute start-1/2 top-9 -translate-x-1/2 bg-[#fbfcfe] px-2">
                <Building2 className="h-11 w-11 stroke-[1.35] text-slate-800" />
              </div>
              <span className="absolute start-0 top-7 border-s border-t border-slate-300 px-2 py-1 text-[9px] font-black tracking-[0.16em] text-slate-400">01</span>
              <span className="absolute end-0 bottom-4 border-b border-e border-slate-300 px-2 py-1 text-[9px] font-black tracking-[0.16em] text-slate-400">START</span>
            </div>
            <h2 id="warehouse-first-empty-title" className="max-w-[620px] text-balance text-2xl font-black leading-tight text-slate-950 sm:text-[32px]">
              {copy.firstWarehouseTitle}
            </h2>
            <p className="mt-3 max-w-[590px] text-pretty text-sm font-medium leading-7 text-slate-600 sm:text-[15px]">
              {copy.firstWarehouseDescription}
            </p>

            <button
              type="button"
              disabled={!access.can("location.create")}
              onClick={openCreate}
              className={`group mt-7 inline-flex min-h-12 items-center gap-3 rounded-full bg-slate-950 px-5 py-2.5 text-sm font-black text-white shadow-[0_8px_0_0_rgba(15,23,42,0.10)] transition-transform hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0 ${focusRing}`}
            >
              <span className="grid h-7 w-7 place-items-center rounded-full border border-white/20 bg-white/10">
                <Plus aria-hidden="true" className="h-4 w-4" />
              </span>
              <span>{copy.createFirstWarehouse}</span>
              <span aria-hidden="true" className="h-px w-5 bg-white/45 transition-[width] duration-200 group-hover:w-8" />
            </button>
          </div>
        </section>
      ) : (
        <>
      <section className="glass-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl" aria-labelledby="warehouse-setup-title" data-cp13-density="compact">
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-3 sm:p-4">
          <div className="min-w-fit shrink-0">
            <h2 id="warehouse-setup-title" className="flex items-center gap-2 break-words font-black text-slate-800">
              <Building2 aria-hidden="true" className="h-5 w-5 shrink-0 text-blue-600" />
              {copy.title}
            </h2>
            <p className="mt-0.5 break-words text-xs text-slate-500">
              {copy.summary(totalText, activeText)}
            </p>
          </div>

          <div className="flex min-w-[260px] flex-1 items-center gap-2">
            <div className="relative min-w-0 flex-1">
              <Search aria-hidden="true" className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                disabled={!canReadLocations}
                aria-label={copy.search}
                placeholder={copy.search}
                maxLength={100}
                className={`w-full rounded-xl border border-slate-200 bg-white py-2.5 ps-10 pe-3 text-sm disabled:opacity-50 ${focusRing}`}
              />
            </div>
            <button
              type="button"
              onClick={() => setRefreshKey((value) => value + 1)}
              disabled={loading || !canReadLocations}
              className={`inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-600 disabled:opacity-40 ${focusRing}`}
              aria-label={copy.refresh}
              title={copy.refresh}
            >
              <RefreshCcw aria-hidden="true" className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>

          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
            {minimumStockLocations.length > 0 && (
              <StockMinimumManager
                locations={minimumStockLocations}
                preferredLocationId={selectedLocationId}
                onApplied={onMinimumApplied}
              />
            )}
            {canManageQualityDestinations ? (
              <button type="button" onClick={() => setQualityDestinationsOpen(true)} className={`inline-flex items-center gap-2 rounded-xl border border-blue-200 bg-white px-3 py-2 text-xs font-bold text-blue-700 hover:bg-blue-50 sm:text-sm ${focusRing}`}>
                <ShieldCheck aria-hidden="true" className="h-4 w-4" /><span>{copy.qualityDestinationsView}</span>
              </button>
            ) : null}
            <button type="button" disabled={!access.can("location.create")} onClick={openCreate} className={`inline-flex items-center gap-2 rounded-xl bg-blue-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-40 sm:text-sm ${focusRing}`}>
              <Plus aria-hidden="true" className="h-4 w-4" /><span>{copy.newWarehouse}</span>
            </button>
          </div>
        </div>

        {loadIssue ? (
          <div role="alert" className="m-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold text-red-700">
            <span className="break-words">{loadIssue}</span>
            <button type="button" onClick={() => setRefreshKey((value) => value + 1)} className={`inline-flex items-center gap-1 rounded-lg border border-red-200 bg-white px-2 py-1 font-bold ${focusRing}`}>
              <RefreshCcw aria-hidden="true" className="h-3.5 w-3.5" />{presentation.retry}
            </button>
          </div>
        ) : null}

        {loading && items.length === 0 ? <p role="status" className="p-6 text-center text-xs font-semibold text-slate-500">{t("common.loading")}</p> : null}

        <div className="min-h-0 flex-1 overflow-auto" data-cp13-phone-list="true">
          <table className={`w-full min-w-0 text-sm md:min-w-[760px] ${isArabic ? "text-right" : "text-left"}`}>
            <thead className="hidden bg-slate-50/95 md:table-header-group">
              <tr className="h-10 text-xs text-slate-600">
                <th className="w-16 px-3 py-2 text-center">{copy.number}</th>
                <th className="px-3 py-2">{copy.warehouse}</th>
                <th className="px-3 py-2">{copy.code}</th>
                <th className="px-3 py-2">{copy.address}</th>
                <th className="px-3 py-2">{copy.status}</th>
                <th className="px-3 py-2">{copy.updated}</th>
                <th className="px-3 py-2 text-center">{copy.actions}</th>
              </tr>
            </thead>
            <tbody className="grid gap-2 p-2 md:table-row-group md:divide-y md:divide-slate-100 md:p-0">
              {items.map((location, index) => (
                <tr
                  key={location.id}
                  className={`block rounded-xl border p-2 md:table-row md:h-14 md:rounded-none md:border-0 md:p-0 md:hover:bg-slate-50/70 ${selectedLocationId === location.id ? "border-blue-200 bg-blue-50/60" : "border-slate-100 bg-white md:bg-transparent"}`}
                >
                  <td className="block px-2 py-1 text-xs font-black text-slate-500 md:table-cell md:w-16 md:px-3 md:py-2 md:text-center">
                    <span className="me-2 text-[10px] font-bold text-slate-400 md:hidden">{copy.number}</span>
                    {formatInventoryInteger(index + 1, language)}
                  </td>
                  <td className="block px-2 py-1 md:table-cell md:px-3 md:py-2">
                    <div className="font-bold text-slate-800">{location.name}</div>
                  </td>
                  <td className="block px-2 py-1 font-mono text-xs text-slate-600 md:table-cell md:px-3 md:py-2">
                    <span className="me-2 font-sans text-[10px] font-bold text-slate-400 md:hidden">{copy.code}</span>{location.code}
                  </td>
                  <td className="block max-w-[320px] px-2 py-1 text-xs text-slate-600 md:table-cell md:px-3 md:py-2 md:text-sm">
                    <span className="me-2 text-[10px] font-bold text-slate-400 md:hidden">{copy.address}</span>
                    <span className="line-clamp-2">{location.address || "—"}</span>
                  </td>
                  <td className="block px-2 py-1 md:table-cell md:px-3 md:py-2">{stateBadge(location)}</td>
                  <td className="block px-2 py-1 text-xs text-slate-500 md:table-cell md:px-3 md:py-2">
                    <span className="me-2 text-[10px] font-bold text-slate-400 md:hidden">{copy.updated}</span>{formatInventoryDateTime(location.updated_at, language)}
                  </td>
                  <td className="mt-1 block border-t border-slate-100 px-2 pt-2 md:table-cell md:border-0 md:px-3 md:py-2">{rowActions(location)}</td>
                </tr>
              ))}
              {!loading && items.length === 0 && !loadIssue && (
                <tr className="block md:table-row">
                  <td colSpan={7} className="block p-8 text-center text-sm text-slate-400 md:table-cell md:p-10">
                    {search ? copy.emptySearch : access.can("location.create") ? copy.emptyCreate : copy.emptyNoAccess}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          <div ref={loadMoreRef} className="min-h-2" aria-hidden="true" />
          {loading && items.length > 0 ? (
            <p role="status" className="border-t border-slate-100 px-3 py-2 text-center text-xs font-semibold text-slate-500">{t("common.loading")}</p>
          ) : null}
        </div>
      </section>
        </>
      )}

      <Modal
        isOpen={qualityDestinationsOpen && canManageQualityDestinations}
        onClose={() => setQualityDestinationsOpen(false)}
        title={copy.qualityDestinationsView}
      >
        <QualityHandlingDestinationsCard compact />
      </Modal>

      <Modal
        isOpen={formOpen}
        onClose={() => { if (!formSubmitting) setFormOpen(false); }}
        title={formMode === "create" ? copy.add : copy.edit}
      >
        <form noValidate className="space-y-3" dir={dir} onSubmit={(event) => { event.preventDefault(); void handleSave(); }}>
          <section className="rounded-xl border border-slate-100 bg-slate-50/60 p-3" aria-labelledby="warehouse-identity-heading">
            <h3 id="warehouse-identity-heading" className="mb-3 text-xs font-black text-slate-800">{presentation.identityTitle}</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block text-xs font-bold text-slate-600">
                {copy.name}<span aria-hidden="true" className="ms-1 text-red-600">*</span>
                <input ref={nameInputRef} autoFocus value={form.name} onChange={(event) => updateForm({ name: event.target.value })} maxLength={150} aria-invalid={fieldIssue?.field === "name"} className={`mt-1 w-full rounded-xl border px-3 py-2.5 ${fieldIssue?.field === "name" ? "border-red-300" : "border-slate-200"} ${focusRing}`} />
                {fieldIssue?.field === "name" ? <span role="alert" className="mt-1 block text-[10px] font-semibold text-red-600">{fieldIssue.message}</span> : null}
              </label>
              <label className="block text-xs font-bold text-slate-600">
                {copy.warehouseCode}<span aria-hidden="true" className="ms-1 text-red-600">*</span>
                <input ref={codeInputRef} value={form.code} onChange={(event) => updateForm({ code: event.target.value.toUpperCase() })} maxLength={50} dir="ltr" aria-invalid={fieldIssue?.field === "code"} className={`mt-1 w-full rounded-xl border px-3 py-2.5 font-mono ${fieldIssue?.field === "code" ? "border-red-300" : "border-slate-200"} ${focusRing}`} placeholder={copy.codePlaceholder} />
                {fieldIssue?.field === "code" ? <span role="alert" className="mt-1 block text-[10px] font-semibold text-red-600">{fieldIssue.message}</span> : <span className="mt-1 block text-[10px] font-semibold leading-4 text-slate-400">{copy.codeHint}</span>}
              </label>
            </div>
          </section>

          <section className="rounded-xl border border-slate-100 p-3" aria-labelledby="warehouse-location-heading">
            <h3 id="warehouse-location-heading" className="mb-3 text-xs font-black text-slate-800">{presentation.locationTitle}</h3>
            <label className="block text-xs font-bold text-slate-600">
              {copy.address}{formMode === "create" ? <span aria-hidden="true" className="ms-1 text-red-600">*</span> : null}
              <textarea ref={addressInputRef} value={form.address} onChange={(event) => updateForm({ address: event.target.value })} maxLength={2000} aria-invalid={fieldIssue?.field === "address"} placeholder={copy.addressPlaceholder} className={`mt-1 min-h-20 w-full rounded-xl border px-3 py-2.5 ${fieldIssue?.field === "address" ? "border-red-300" : "border-slate-200"} ${focusRing}`} />
              {fieldIssue?.field === "address" ? <span role="alert" className="mt-1 block text-[10px] font-semibold text-red-600">{fieldIssue.message}</span> : null}
            </label>
            <label className="mt-3 block text-xs font-bold text-slate-600">
              {copy.locationLink}
              <input value={form.location_link} onChange={(event) => updateForm({ location_link: event.target.value })} maxLength={500} dir="ltr" className={`mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5 ${focusRing}`} placeholder="https://maps.google.com/..." />
            </label>
            <p className="mt-3 text-[10px] font-semibold leading-4 text-slate-500">{copy.coordinatesHint}</p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <label className="block text-xs font-bold text-slate-600">
                {copy.latitude}
                <input ref={latitudeInputRef} value={form.latitude} onChange={(event) => updateForm({ latitude: event.target.value })} inputMode="decimal" dir="ltr" aria-invalid={fieldIssue?.field === "coordinates"} className={`mt-1 w-full rounded-xl border px-3 py-2.5 ${fieldIssue?.field === "coordinates" ? "border-red-300" : "border-slate-200"} ${focusRing}`} placeholder="31.9539" />
              </label>
              <label className="block text-xs font-bold text-slate-600">
                {copy.longitude}
                <input value={form.longitude} onChange={(event) => updateForm({ longitude: event.target.value })} inputMode="decimal" dir="ltr" aria-invalid={fieldIssue?.field === "coordinates"} className={`mt-1 w-full rounded-xl border px-3 py-2.5 ${fieldIssue?.field === "coordinates" ? "border-red-300" : "border-slate-200"} ${focusRing}`} placeholder="35.9106" />
              </label>
            </div>
            {fieldIssue?.field === "coordinates" ? <span role="alert" className="mt-1 block text-[10px] font-semibold text-red-600">{fieldIssue.message}</span> : null}
          </section>

          {formIssue ? <p role="alert" className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-900">{formIssue}</p> : null}
          <button type="submit" disabled={formSubmitting} className={`w-full rounded-xl bg-blue-600 py-3 font-bold text-white disabled:opacity-50 ${focusRing}`}>{formSubmitting ? t("common.saving") : t("common.save")}</button>
        </form>
      </Modal>


      <Modal isOpen={stateAction !== null && stateLocation !== null} onClose={() => { if (!stateSubmitting) { setStateAction(null); setStateLocation(null); setStateIssue(null); } }} title={stateAction === "deactivate" ? copy.deactivate : copy.activate}>
        <form className="space-y-4" dir={dir} onSubmit={(event) => { event.preventDefault(); void handleStateChange(); }}>
          <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="break-words text-sm text-slate-600">{copy.warehouse}: <span className="font-bold text-slate-900">{stateLocation?.name}</span></p>
              {stateLocation ? stateBadge(stateLocation) : null}
            </div>
            <p className="mt-2 text-[10px] font-semibold leading-4 text-slate-500">{stateAction === "deactivate" ? presentation.deactivationCheck : presentation.activationCheck}</p>
          </div>
          <label className="block text-xs font-bold text-slate-600">
            {stateAction === "deactivate" ? copy.deactivateReason : copy.activateNote}
            <textarea autoFocus value={stateReason} onChange={(event) => { setStateReason(event.target.value); setStateIssue(null); setStateRequestId(crypto.randomUUID()); }} maxLength={1000} className={`mt-1 min-h-24 w-full rounded-xl border border-slate-200 px-3 py-2.5 ${focusRing}`} />
          </label>
          {stateIssue ? (
            <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-950">
              <p className="break-words font-black">{stateIssue.title}</p>
              {stateIssue.details.length ? <ul className="mt-2 list-disc space-y-1 ps-5 font-semibold">{stateIssue.details.map((detail) => <li key={detail}>{detail}</li>)}</ul> : null}
              {stateAction === "deactivate" ? <p className="mt-2 border-t border-amber-200 pt-2 font-semibold">{presentation.deactivationNextStep}</p> : null}
            </div>
          ) : null}
          <button type="submit" disabled={stateSubmitting} className={`w-full rounded-xl py-3 font-bold text-white disabled:opacity-50 ${focusRing} ${stateAction === "deactivate" ? "bg-red-600" : "bg-emerald-600"}`}>{stateSubmitting ? t("inventoryWarehouses.processing") : stateAction === "deactivate" ? copy.confirmDeactivate : copy.confirmActivate}</button>
        </form>
      </Modal>
    </div>
  );
}
