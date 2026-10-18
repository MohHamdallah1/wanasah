import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage, apiErrorStatus, isAmbiguousRequestError } from "@/lib/apiErrors";
import {
  completeDurableOperation,
  durableScope,
  getOrCreateDurableCommand,
  readDurableCommand,
  type DurableCommand,
} from "@/lib/durableOperations";
import { toast } from "sonner";

for (const [language, copy] of Object.entries({
  ar: {
    save: "حفظ",
    apply: "تطبيق",
    retry: "إعادة المحاولة",
    pending: "نتيجة الأمر غير مؤكدة. أعد المحاولة لاستعادة النتيجة بنفس معرّف العملية.",
    setup: "وجهات الجودة",
    hint: "تبقى الكمية في نفس موقعها الحالي، وتتغير حالة المخزون فقط. لا تحتاج إلى إنشاء مستودع إضافي.",
    sameLocation: "نفس الموقع الحالي",
    sameLocationHint: "الموقع الفعلي لا يتغير؛ الذي يتغير هو حالة المخزون.",
    quarantine: "الحجر",
    vendorReturn: "الإرجاع للمورد",
    disposal: "التالف / بانتظار الإتلاف",
    active: "الافتراضي الفعّال",
    customActive: "إعداد مخصص فعّال",
    customConfigured: "وجهة مخصصة",
    customHint: "الوجهات المخصصة المنشورة حاليًا تبقى فعّالة كما هي.",
    customReadonly: "يوجد إعداد مخصص منشور مسبقًا. يعرضه النظام للقراءة فقط هنا ولا يغيّره عند فتح النافذة.",
    reference: "الموقع رقم {{id}}",
  },
  en: {
    save: "Save",
    apply: "Apply",
    retry: "Retry",
    pending: "The command result is unconfirmed. Retry with the same operation identity to recover it.",
    setup: "Quality destinations",
    hint: "The quantity stays in its current location and only the stock status changes. No extra warehouse is required.",
    sameLocation: "Same current location",
    sameLocationHint: "Physical location stays unchanged; only stock status changes.",
    quarantine: "Quarantine",
    vendorReturn: "Vendor return",
    disposal: "Damaged / disposal pending",
    active: "Effective default",
    customActive: "Custom configuration active",
    customConfigured: "Custom destination",
    customHint: "The currently published custom destinations remain in effect.",
    customReadonly: "An existing published custom configuration is active. This panel is read-only and opening it does not change that configuration.",
    reference: "Location #{{id}}",
  },
})) i18n.addResourceBundle(language, "translation", { transferDestinationSetup: copy }, true, true);

type PolicyPayload = {
  quarantine_location_id: number | null;
  disposal_location_id: number | null;
  vendor_return_staging_location_id: number | null;
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

const positiveInt = (value: unknown): number | null =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : null;

const optionalPositiveInt = (value: unknown): number | null => {
  if (value === null) return null;
  const parsed = positiveInt(value);
  if (parsed === null) throw new Error("TRANSFER_POLICY_RESPONSE_INVALID");
  return parsed;
};

const parsePayload = (value: unknown): PolicyPayload => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("TRANSFER_POLICY_RESPONSE_INVALID");
  }
  const row = value as Record<string, unknown>;
  if (typeof row.allow_retiring_warehouse_balancing !== "boolean") {
    throw new Error("TRANSFER_POLICY_RESPONSE_INVALID");
  }
  return {
    quarantine_location_id: optionalPositiveInt(row.quarantine_location_id),
    disposal_location_id: optionalPositiveInt(row.disposal_location_id),
    vendor_return_staging_location_id: optionalPositiveInt(row.vendor_return_staging_location_id),
    allow_retiring_warehouse_balancing: row.allow_retiring_warehouse_balancing,
  };
};

const parsePolicyItem = (value: unknown): PolicyItem | null => {
  if (value === null) return null;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("TRANSFER_POLICY_RESPONSE_INVALID");
  }
  const row = value as Record<string, unknown>;
  const id = positiveInt(row.id);
  const revision = positiveInt(row.revision);
  const status = row.status;
  if (
    id === null ||
    revision === null ||
    (status !== "DRAFT" && status !== "PUBLISHED" && status !== "SUPERSEDED")
  ) {
    throw new Error("TRANSFER_POLICY_RESPONSE_INVALID");
  }
  return { id, revision, status, validated_payload: parsePayload(row.validated_payload) };
};

const parsePolicyState = (value: unknown): PolicyState => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("TRANSFER_POLICY_RESPONSE_INVALID");
  }
  const row = value as Record<string, unknown>;
  return {
    draft: parsePolicyItem(row.draft ?? null),
    published: parsePolicyItem(row.published ?? null),
  };
};

const parsePolicyMutation = (value: unknown): PolicyItem => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("TRANSFER_POLICY_RESPONSE_INVALID");
  }
  const item = parsePolicyItem((value as Record<string, unknown>).policy);
  if (!item) throw new Error("TRANSFER_POLICY_RESPONSE_INVALID");
  return item;
};

const isInPlacePayload = (payload: PolicyPayload) =>
  payload.quarantine_location_id === null &&
  payload.disposal_location_id === null &&
  payload.vendor_return_staging_location_id === null;

type Wire = {
  path: string;
  method: "PUT" | "POST";
  body: Record<string, unknown>;
};

export function useTransferDestinationPolicy(onSaved?: () => void | Promise<void>) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const canManage = access.can("inventory.transfer_policy.manage");
  const company = Number(localStorage.getItem("company_id"));
  const principal = Number(localStorage.getItem("principal_id"));
  const scope =
    Number.isSafeInteger(company) &&
    company > 0 &&
    Number.isSafeInteger(principal) &&
    principal > 0
      ? durableScope(company, principal, "TRANSFER_POLICY")
      : null;
  const scopeRef = useRef(scope);
  scopeRef.current = scope;

  const [policy, setPolicy] = useState<PolicyState>({ draft: null, published: null });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [pending, setPending] = useState<DurableCommand<Wire> | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const ready = useRef(false);
  const loadedScope = useRef<string | null>(null);
  const activeScopes = useRef(new Set<string>());
  const policySeq = useRef(0);

  const loadPolicy = useCallback(async () => {
    const seq = ++policySeq.current;
    if (!canManage || !scope) {
      setLoading(false);
      return;
    }
    setLoading(true);
    if (loadedScope.current !== scope) {
      // Fail closed on company/principal switches: old tenant policy must never
      // remain visible while the new scope is resolving.
      loadedScope.current = null;
      setPolicy({ draft: null, published: null });
      setSaving(false);
      setPending(null);
    }
    setLoadError(null);
    ready.current = false;
    try {
      const state = parsePolicyState(
        await authFetch("/warehouse/operational-policy/transfer-destinations"),
      );
      const command = await readDurableCommand<Wire>(scope);
      if (seq !== policySeq.current || scopeRef.current !== scope) return;
      loadedScope.current = scope;
      setPolicy(state);
      setPending(command);
      ready.current = true;
    } catch (error) {
      if (seq === policySeq.current) {
        setLoadError(
          apiErrorMessage(
            error,
            t("inventoryWarehouses.qualityDestinations.errors.loadPolicy"),
          ),
        );
      }
    } finally {
      if (seq === policySeq.current) setLoading(false);
    }
  }, [authFetch, canManage, scope, t]);

  const invalidatePolicy = useCallback(() => {
    ++policySeq.current;
  }, []);

  useEffect(() => {
    void loadPolicy();
    return invalidatePolicy;
  }, [loadPolicy, invalidatePolicy]);

  const execute = async (wire?: Wire) => {
    if (
      !canManage ||
      !scope ||
      loadedScope.current !== scope ||
      !ready.current ||
      activeScopes.current.has(scope)
    ) {
      return;
    }
    activeScopes.current.add(scope);
    setSaving(true);
    let command: DurableCommand<Wire> | null = null;
    try {
      command = wire
        ? await getOrCreateDurableCommand(scope, wire)
        : await readDurableCommand<Wire>(scope);
      if (!command) return;
      setPending(command);
      const item = parsePolicyMutation(
        await authFetch(command.payload.path, {
          method: command.payload.method,
          body: JSON.stringify({
            ...command.payload.body,
            request_id: command.requestId,
          }),
        }),
      );
      completeDurableOperation(scope, command.requestId);
      if (scopeRef.current !== scope) return;
      setPending(null);
      setPolicy((current) =>
        item.status === "DRAFT"
          ? { ...current, draft: item }
          : { draft: null, published: item },
      );
      toast.success(t("inventoryWarehouses.qualityDestinations.saved"));
      if (item.status === "PUBLISHED") await onSaved?.();
    } catch (error) {
      const status = apiErrorStatus(error);
      if (
        command &&
        status &&
        status >= 400 &&
        status < 500 &&
        !isAmbiguousRequestError(error)
      ) {
        completeDurableOperation(scope, command.requestId);
        if (scopeRef.current === scope) setPending(null);
      }
      if (scopeRef.current === scope) {
        toast.error(
          apiErrorMessage(
            error,
            t("inventoryWarehouses.qualityDestinations.errors.save"),
          ),
        );
      }
    } finally {
      activeScopes.current.delete(scope);
      if (scopeRef.current === scope) setSaving(false);
    }
  };

  const saveDraft = async () => {
    const current = policy.draft ?? policy.published;
    await execute({
      path: "/warehouse/operational-policy/transfer-destinations/draft",
      method: "PUT",
      body: {
        expected_revision: policy.draft?.revision ?? null,
        payload: {
          quarantine_location_id: null,
          disposal_location_id: null,
          vendor_return_staging_location_id: null,
          allow_retiring_warehouse_balancing:
            current?.validated_payload.allow_retiring_warehouse_balancing ?? false,
        },
      },
    });
  };

  const canPublish =
    policy.draft !== null && isInPlacePayload(policy.draft.validated_payload);

  const publish = async () => {
    if (!policy.draft || !canPublish) return;
    await execute({
      path: `/warehouse/operational-policy/transfer-destinations/${policy.draft.id}/publish`,
      method: "POST",
      body: { expected_revision: policy.draft.revision },
    });
  };

  const inScope = loadedScope.current === scope;
  const resolved = inScope && ready.current && !loading && loadError === null;
  const visiblePolicy = resolved ? policy : { draft: null, published: null };
  const publishedPayload = visiblePolicy.published?.validated_payload ?? null;
  const customConfigured =
    resolved &&
    publishedPayload !== null &&
    !isInPlacePayload(publishedPayload);
  const effectivePayload: PolicyPayload | null = resolved
    ? publishedPayload ?? {
        quarantine_location_id: null,
        disposal_location_id: null,
        vendor_return_staging_location_id: null,
        allow_retiring_warehouse_balancing: false,
      }
    : null;
  const inPlaceActive =
    resolved &&
    effectivePayload !== null &&
    isInPlacePayload(effectivePayload);

  return {
    canManage,
    policy: visiblePolicy,
    resolved,
    inPlaceActive,
    customConfigured,
    effectivePayload,
    loading: !resolved,
    saving,
    pending: inScope ? pending : null,
    loadError,
    loadPolicy,
    saveDraft,
    publish,
    canPublish: inScope && canPublish,
    retry: () => execute(),
  };
}
