import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage, apiErrorStatus, isAmbiguousRequestError } from "@/lib/apiErrors";
import { completeDurableOperation, durableScope, getOrCreateDurableCommand, readDurableCommand, type DurableCommand } from "@/lib/durableOperations";
import { toast } from "sonner";

for (const [language, copy] of Object.entries({
  ar: { saveDraft: "حفظ المسودة", publish: "نشر السياسة", retry: "إعادة المحاولة", pending: "نتيجة الأمر غير مؤكدة. أعد المحاولة لاستعادة النتيجة بنفس معرّف العملية.", setup: "إعداد وجهات الجودة", hint: "هذه إعدادات الوجهات فقط. إجراءات الجودة تنفذ من مسار المخزون المختص." },
  en: { saveDraft: "Save draft", publish: "Publish policy", retry: "Retry", pending: "The command result is unconfirmed. Retry with the same operation identity to recover it.", setup: "Quality destination setup", hint: "Configure destinations here. Quality actions remain in their inventory workflow." },
})) i18n.addResourceBundle(language, "translation", { transferDestinationSetup: copy }, true, true);

type PolicyPayload = {
  quarantine_location_id: number;
  disposal_location_id: number;
  vendor_return_staging_location_id: number;
  allow_retiring_warehouse_balancing: boolean;
};

type PolicyItem = {
  id: number;
  revision: number;
  status: "DRAFT" | "PUBLISHED" | "SUPERSEDED";
  validated_payload: PolicyPayload;
};

type PolicyState = {
  draft: PolicyItem | null;
  published: PolicyItem | null;
};

type LocationOption = { id: number; name: string; code: string };
type LocationPage = { items: LocationOption[]; has_more: boolean };
type FormState = {
  quarantine: number | null;
  disposal: number | null;
  vendorReturn: number | null;
  allowRetiringBalancing: boolean;
};

const emptyForm = (): FormState => ({
  quarantine: null,
  disposal: null,
  vendorReturn: null,
  allowRetiringBalancing: false,
});
const positiveInt = (value: unknown): number | null =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : null;

const parsePayload = (value: unknown): PolicyPayload => {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("TRANSFER_POLICY_RESPONSE_INVALID");
  const row = value as Record<string, unknown>;
  const quarantine = positiveInt(row.quarantine_location_id);
  const disposal = positiveInt(row.disposal_location_id);
  const vendor = positiveInt(row.vendor_return_staging_location_id);
  if (quarantine === null || disposal === null || vendor === null || typeof row.allow_retiring_warehouse_balancing !== "boolean") {
    throw new Error("TRANSFER_POLICY_RESPONSE_INVALID");
  }
  return {
    quarantine_location_id: quarantine,
    disposal_location_id: disposal,
    vendor_return_staging_location_id: vendor,
    allow_retiring_warehouse_balancing: row.allow_retiring_warehouse_balancing,
  };
};
const parsePolicyItem = (value: unknown): PolicyItem | null => {
  if (value === null) return null;
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("TRANSFER_POLICY_RESPONSE_INVALID");
  const row = value as Record<string, unknown>;
  const id = positiveInt(row.id);
  const revision = positiveInt(row.revision);
  const status = row.status;
  if (id === null || revision === null || (status !== "DRAFT" && status !== "PUBLISHED" && status !== "SUPERSEDED")) {
    throw new Error("TRANSFER_POLICY_RESPONSE_INVALID");
  }
  return { id, revision, status, validated_payload: parsePayload(row.validated_payload) };
};
const parsePolicyState = (value: unknown): PolicyState => {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("TRANSFER_POLICY_RESPONSE_INVALID");
  const row = value as Record<string, unknown>;
  return { draft: parsePolicyItem(row.draft ?? null), published: parsePolicyItem(row.published ?? null) };
};
const parsePolicyMutation = (value: unknown): PolicyItem => {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("TRANSFER_POLICY_RESPONSE_INVALID");
  const item = parsePolicyItem((value as Record<string, unknown>).policy);
  if (!item) throw new Error("TRANSFER_POLICY_RESPONSE_INVALID");
  return item;
};
const parseLocationPage = (value: unknown): LocationPage => {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("WAREHOUSE_LOCATION_RESPONSE_INVALID");
  const row = value as Record<string, unknown>;
  if (!Array.isArray(row.items) || typeof row.has_more !== "boolean" || row.items.length > 200) throw new Error("WAREHOUSE_LOCATION_RESPONSE_INVALID");
  return {
    has_more: row.has_more,
    items: row.items.map((raw) => {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("WAREHOUSE_LOCATION_RESPONSE_INVALID");
      const item = raw as Record<string, unknown>;
      const id = positiveInt(item.id);
      if (id === null || typeof item.name !== "string" || typeof item.code !== "string") throw new Error("WAREHOUSE_LOCATION_RESPONSE_INVALID");
      return { id, name: item.name, code: item.code };
    }),
  };
};
const parseFormDraft = (raw: string): FormState => {
  const value = JSON.parse(raw) as Record<string, unknown>;
  const id = (field: string) => value[field] === null ? null : positiveInt(value[field]);
  if (!value || typeof value !== "object" || typeof value.allow_retiring_warehouse_balancing !== "boolean") throw new Error("TRANSFER_POLICY_RESPONSE_INVALID");
  return { quarantine: id("quarantine_location_id"), disposal: id("disposal_location_id"),
    vendorReturn: id("vendor_return_staging_location_id"), allowRetiringBalancing: value.allow_retiring_warehouse_balancing };
};
const formFromPolicy = (policy: PolicyItem | null): FormState => policy ? {
  quarantine: policy.validated_payload.quarantine_location_id,
  disposal: policy.validated_payload.disposal_location_id,
  vendorReturn: policy.validated_payload.vendor_return_staging_location_id,
  allowRetiringBalancing: policy.validated_payload.allow_retiring_warehouse_balancing,
} : emptyForm();


type Wire = { path: string; method: "PUT" | "POST"; body: Record<string, unknown> };
export function useTransferDestinationPolicy(onSaved?: () => void | Promise<void>) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const canManage = access.can("inventory.transfer_policy.manage");
  const company = Number(localStorage.getItem("company_id"));
  const principal = Number(localStorage.getItem("principal_id"));
  const scope = Number.isSafeInteger(company) && company > 0 && Number.isSafeInteger(principal) && principal > 0
    ? durableScope(company, principal, "TRANSFER_POLICY") : null;
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  const [policy, setPolicy] = useState<PolicyState>({ draft: null, published: null });
  const [form, setForm] = useState<FormState>(emptyForm);
  const [knownLocations, setKnownLocations] = useState<Record<number, LocationOption>>({});
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [hasMoreLocations, setHasMoreLocations] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [pending, setPending] = useState<DurableCommand<Wire> | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const ready = useRef(false);
  const loadedScope = useRef<string | null>(null);
  const locationsScope = useRef<string | null>(null);
  const activeScopes = useRef(new Set<string>());
  const policySeq = useRef(0);

  const loadPolicy = useCallback(async () => {
    const seq = ++policySeq.current;
    if (!canManage || !scope) return;
    setLoading(true);
    if (loadedScope.current !== scope) { setSaving(false); setPending(null); }
    setLoadError(null);
    ready.current = false;
    try {
      const state = parsePolicyState(await authFetch("/warehouse/operational-policy/transfer-destinations"));
      const command = await readDurableCommand<Wire>(scope);
      if (seq !== policySeq.current || scopeRef.current !== scope) return;
      const saved = localStorage.getItem(scope + ":draft");
      setForm(saved ? parseFormDraft(saved) : formFromPolicy(state.draft ?? state.published));
      loadedScope.current = scope;
      setPolicy(state);
      setPending(command);
      ready.current = true;
    } catch (error) {
      if (seq === policySeq.current) setLoadError(apiErrorMessage(error, t("inventoryWarehouses.qualityDestinations.errors.loadPolicy")));
    } finally { if (seq === policySeq.current) setLoading(false); }
  }, [authFetch, canManage, scope, t]);
  const invalidatePolicy = useCallback(() => { ++policySeq.current; }, []);
  useEffect(() => { void loadPolicy(); return invalidatePolicy; }, [loadPolicy, invalidatePolicy]);
  useEffect(() => {
    const timer = window.setTimeout(() => { const clean = searchInput.trim(); setSearch(clean.length >= 2 ? clean : ""); }, 250);
    return () => window.clearTimeout(timer);
  }, [searchInput]);
  useEffect(() => {
    let current = true;
    if (!canManage) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ include_inactive: "false", limit: "200" });
    if (search) params.set("search", search);
    void authFetch(`/warehouse/locations/manage?${params}`, { signal: controller.signal }).then(raw => {
      if (!current || scopeRef.current !== scope) return;
      const page = parseLocationPage(raw);
      locationsScope.current = scope;
      setKnownLocations(Object.fromEntries(page.items.map(item => [item.id, item])));
      setHasMoreLocations(page.has_more);
    }).catch(error => { if (current) toast.error(apiErrorMessage(error, t("inventoryWarehouses.qualityDestinations.errors.loadLocations"))); });
    return () => { current = false; controller.abort(); };
  }, [authFetch, canManage, scope, search, t]);
  useEffect(() => {
    if (!scope || !ready.current) return;
    try {
      localStorage.setItem(scope + ":draft", JSON.stringify({
        quarantine_location_id: form.quarantine, disposal_location_id: form.disposal,
        vendor_return_staging_location_id: form.vendorReturn, allow_retiring_warehouse_balancing: form.allowRetiringBalancing,
      }));
    } catch (error) { setLoadError(apiErrorMessage(error, t("inventoryWarehouses.qualityDestinations.errors.save"))); }
  }, [scope, form, t]);
  const execute = async (wire?: Wire) => {
    if (!canManage || !scope || loadedScope.current !== scope || !ready.current || activeScopes.current.has(scope)) return;
    activeScopes.current.add(scope);
    setSaving(true);
    let command: DurableCommand<Wire> | null = null;
    try {
      command = wire ? await getOrCreateDurableCommand(scope, wire) : await readDurableCommand<Wire>(scope);
      if (!command) return;
      setPending(command);
      const item = parsePolicyMutation(await authFetch(command.payload.path, { method: command.payload.method,
        body: JSON.stringify({ ...command.payload.body, request_id: command.requestId }) }));
      completeDurableOperation(scope, command.requestId);
      if (scopeRef.current !== scope) return;
      setPending(null);
      setPolicy(current => item.status === "DRAFT" ? { ...current, draft: item } : { draft: null, published: item });
      setForm(formFromPolicy(item));
      toast.success(t("inventoryWarehouses.qualityDestinations.saved"));
      if (item.status === "PUBLISHED") await onSaved?.();
    } catch (error) {
      const status = apiErrorStatus(error);
      if (command && status && status >= 400 && status < 500 && !isAmbiguousRequestError(error)) {
        completeDurableOperation(scope, command.requestId);
        if (scopeRef.current === scope) setPending(null);
      }
      if (scopeRef.current === scope) toast.error(apiErrorMessage(error, t("inventoryWarehouses.qualityDestinations.errors.save")));
    } finally { activeScopes.current.delete(scope); if (scopeRef.current === scope) setSaving(false); }
  };
  const saveDraft = async () => {
    if (form.quarantine === null || form.disposal === null || form.vendorReturn === null) {
      toast.error(t("inventoryWarehouses.qualityDestinations.errors.required")); return;
    }
    await execute({ path: "/warehouse/operational-policy/transfer-destinations/draft", method: "PUT", body: {
      expected_revision: policy.draft?.revision ?? null, payload: {
        quarantine_location_id: form.quarantine, disposal_location_id: form.disposal,
        vendor_return_staging_location_id: form.vendorReturn, allow_retiring_warehouse_balancing: form.allowRetiringBalancing,
      },
    } });
  };
  const canPublish = policy.draft !== null && JSON.stringify(form) === JSON.stringify(formFromPolicy(policy.draft));
  const publish = async () => {
    if (!policy.draft || !canPublish) return;
    await execute({ path: `/warehouse/operational-policy/transfer-destinations/${policy.draft.id}/publish`, method: "POST",
      body: { expected_revision: policy.draft.revision } });
  };
  const ids = [form.quarantine, form.disposal, form.vendorReturn].filter((id): id is number => id !== null);
  const options = Object.values(knownLocations);
  for (const id of ids) if (!knownLocations[id]) options.push({ id, name: "#" + new Intl.NumberFormat(i18n.language + "-u-nu-latn").format(id), code: "" });
  const inScope = loadedScope.current === scope;
  return { canManage, policy: inScope ? policy : { draft: null, published: null }, form: inScope ? form : emptyForm(),
    setForm, options: inScope && locationsScope.current === scope ? options : [], searchInput, setSearchInput, hasMoreLocations,
    loading: loading || !inScope, saving, pending: inScope ? pending : null, loadError, loadPolicy, saveDraft, publish,
    canPublish: inScope && canPublish, retry: () => execute() };
}
