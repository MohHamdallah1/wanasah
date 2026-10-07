import { Save, Search, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";

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
const formFromPolicy = (policy: PolicyItem | null): FormState => policy ? {
  quarantine: policy.validated_payload.quarantine_location_id,
  disposal: policy.validated_payload.disposal_location_id,
  vendorReturn: policy.validated_payload.vendor_return_staging_location_id,
  allowRetiringBalancing: policy.validated_payload.allow_retiring_warehouse_balancing,
} : emptyForm();

export function QualityHandlingDestinationsCard({ compact = false, onSaved }: { compact?: boolean; onSaved?: () => void | Promise<void> } = {}) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const canManage = access.isCompanyAdmin || access.can("inventory.transfer_policy.manage");
  const [policy, setPolicy] = useState<PolicyState>({ draft: null, published: null });
  const [form, setForm] = useState<FormState>(() => emptyForm());
  const [knownLocations, setKnownLocations] = useState<Record<number, LocationOption>>({});
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [hasMoreLocations, setHasMoreLocations] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const loadPolicy = useCallback(async () => {
    if (!canManage) return;
    setLoading(true);
    try {
      const state = parsePolicyState(await authFetch("/warehouse/operational-policy/transfer-destinations"));
      setPolicy(state);
      setForm(formFromPolicy(state.draft ?? state.published));
    } catch (error) {
      toast.error(apiErrorMessage(error, t("inventoryWarehouses.qualityDestinations.errors.loadPolicy")));
    } finally { setLoading(false); }
  }, [authFetch, canManage, t]);

  const loadLocations = useCallback(async () => {
    if (!canManage) return;
    try {
      const params = new URLSearchParams({ include_inactive: "false", limit: "200" });
      if (search.length >= 2) params.set("search", search);
      const page = parseLocationPage(await authFetch(`/warehouse/locations/manage?${params.toString()}`));
      setKnownLocations((current) => {
        const next = { ...current };
        for (const item of page.items) next[item.id] = item;
        return next;
      });
      setHasMoreLocations(page.has_more);
    } catch (error) {
      toast.error(apiErrorMessage(error, t("inventoryWarehouses.qualityDestinations.errors.loadLocations")));
    }
  }, [authFetch, canManage, search, t]);

  useEffect(() => { void loadPolicy(); }, [loadPolicy]);
  useEffect(() => {
    const timeout = window.setTimeout(() => {
      const clean = searchInput.trim();
      setSearch(clean.length >= 2 ? clean : "");
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [searchInput]);
  useEffect(() => { void loadLocations(); }, [loadLocations]);

  const selectedIds = [form.quarantine, form.disposal, form.vendorReturn].filter((value): value is number => value !== null);
  const options = useMemo(() => {
    const values = Object.values(knownLocations);
    for (const id of selectedIds) if (!knownLocations[id]) values.push({ id, name: `#${id}`, code: "" });
    return values.sort((a, b) => a.name.localeCompare(b.name));
  }, [knownLocations, selectedIds.join(":")]);
  if (!canManage) return null;

  const saveAndPublish = async () => {
    if (form.quarantine === null || form.disposal === null || form.vendorReturn === null) {
      toast.error(t("inventoryWarehouses.qualityDestinations.errors.required"));
      return;
    }
    setSaving(true);
    try {
      const draft = parsePolicyMutation(await authFetch("/warehouse/operational-policy/transfer-destinations/draft", {
        method: "PUT",
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          expected_revision: policy.draft?.revision ?? null,
          payload: {
            quarantine_location_id: form.quarantine,
            disposal_location_id: form.disposal,
            vendor_return_staging_location_id: form.vendorReturn,
            allow_retiring_warehouse_balancing: form.allowRetiringBalancing,
          },
        }),
      }));
      parsePolicyMutation(await authFetch(`/warehouse/operational-policy/transfer-destinations/${draft.id}/publish`, {
        method: "POST",
        body: JSON.stringify({ request_id: crypto.randomUUID(), expected_revision: draft.revision }),
      }));
      toast.success(t("inventoryWarehouses.qualityDestinations.saved"));
      await loadPolicy();
      await onSaved?.();
    } catch (error) {
      toast.error(apiErrorMessage(error, t("inventoryWarehouses.qualityDestinations.errors.save")));
    } finally { setSaving(false); }
  };

  const select = (key: "quarantine" | "disposal" | "vendorReturn", labelKey: string, hintKey: string) => (
    <label className="block min-w-0">
      <span className="text-xs font-black text-slate-800">{t(labelKey)}</span>
      {!compact ? <span className="mt-0.5 block text-[10px] font-semibold leading-4 text-slate-500">{t(hintKey)}</span> : null}
      <select value={form[key] ?? ""} onChange={(event) => setForm((current) => ({ ...current, [key]: event.target.value ? Number(event.target.value) : null }))}
        className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-slate-700 outline-none focus:ring-2 focus:ring-blue-500/20">
        <option value="">{t("inventoryWarehouses.qualityDestinations.choose")}</option>
        {options.map((item) => <option key={item.id} value={item.id}>{item.name}{item.code ? ` · ${item.code}` : ""}</option>)}
      </select>
    </label>
  );

  return <section className="rounded-2xl border border-slate-200 bg-slate-50/60 p-3" aria-labelledby="quality-destinations-title">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h3 id="quality-destinations-title" className="flex items-center gap-2 text-sm font-black text-slate-900"><ShieldCheck className="h-4 w-4 text-blue-600" />{t("inventoryWarehouses.qualityDestinations.title")}</h3>
        {!compact ? <p className="mt-1 max-w-3xl text-[10px] font-semibold leading-5 text-slate-500">{t("inventoryWarehouses.qualityDestinations.hint")}</p> : null}
      </div>
      {!compact ? <span className={`rounded-full px-2.5 py-1 text-[9px] font-black ${policy.published ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>{t(policy.published ? "inventoryWarehouses.qualityDestinations.active" : "inventoryWarehouses.qualityDestinations.notConfigured")}</span> : null}
    </div>
    <div className="mt-3 relative"><Search className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder={t("inventoryWarehouses.qualityDestinations.search")} className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pr-10 pl-3 text-sm outline-none focus:ring-2 focus:ring-blue-500/20" /></div>
    {hasMoreLocations ? <p className="mt-1 text-[9px] font-semibold text-slate-500">{t("inventoryWarehouses.qualityDestinations.searchMore")}</p> : null}
    <div className="mt-3 grid gap-3 lg:grid-cols-3">
      {select("quarantine", "inventoryWarehouses.qualityDestinations.quarantine.label", "inventoryWarehouses.qualityDestinations.quarantine.hint")}
      {select("vendorReturn", "inventoryWarehouses.qualityDestinations.vendorReturn.label", "inventoryWarehouses.qualityDestinations.vendorReturn.hint")}
      {select("disposal", "inventoryWarehouses.qualityDestinations.disposal.label", "inventoryWarehouses.qualityDestinations.disposal.hint")}
    </div>
    <div className="mt-3 flex justify-end"><button type="button" disabled={loading || saving} onClick={() => void saveAndPublish()} className="inline-flex min-h-9 items-center gap-2 rounded-xl bg-slate-950 px-4 text-xs font-black text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"><Save className="h-4 w-4" />{saving ? t("common.loading") : t("inventoryWarehouses.qualityDestinations.saveAndActivate")}</button></div>
  </section>;
}
