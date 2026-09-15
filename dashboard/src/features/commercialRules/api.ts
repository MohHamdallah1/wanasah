import type {
  ApprovalPolicy,
  CursorPage,
  OfferCatalogVariant,
  OfferDefinition,
  OfferPreview,
  OfferVersion,
  TaxJurisdiction,
  TaxPreview,
  TaxRuleSet,
  TaxVersion,
} from "./contracts";

export type AuthFetch = (
  path: string,
  opts?: RequestInit
) => Promise<unknown>;

const assertPage = <T>(value: unknown, label: string): CursorPage<T> => {
  if (!value || typeof value !== "object") {
    throw new Error(`عقد ${label} غير صالح.`);
  }
  const page = value as Partial<CursorPage<T>>;
  if (
    !Array.isArray(page.items) ||
    typeof page.has_more !== "boolean" ||
    (page.next_cursor !== null && typeof page.next_cursor !== "string")
  ) {
    throw new Error(`عقد صفحة ${label} غير صالح.`);
  }
  if (page.has_more && !page.next_cursor) {
    throw new Error(`السيرفر أعلن عن صفحة تالية لـ${label} بدون cursor.`);
  }
  return page as CursorPage<T>;
};

const isPositiveInteger = (value: unknown): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0;

const isNonEmptyString = (value: unknown): value is string =>
  typeof value === "string" && value.trim().length > 0;

const isPositiveDecimalString = (value: unknown): value is string => {
  if (typeof value !== "string" || !/^\d+(?:\.\d+)?$/.test(value)) return false;
  return !/^0+(?:\.0+)?$/.test(value);
};

const isCatalogUom = (value: unknown): value is OfferCatalogVariant["base_uom"] => {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  return (
    isPositiveInteger(row.id) &&
    isNonEmptyString(row.code) &&
    isNonEmptyString(row.name)
  );
};

const assertOfferCatalogVariant = (
  value: unknown,
  label: string
): OfferCatalogVariant => {
  if (!value || typeof value !== "object") {
    throw new Error(`عقد ${label} غير صالح.`);
  }
  const row = value as Record<string, unknown>;
  if (
    !isPositiveInteger(row.id) ||
    !isPositiveInteger(row.product_id) ||
    !isNonEmptyString(row.sku) ||
    !isNonEmptyString(row.name) ||
    !isCatalogUom(row.base_uom) ||
    !Array.isArray(row.uoms) ||
    row.uoms.length === 0 ||
    !row.uoms.every(isCatalogUom) ||
    typeof row.quantity_scale !== "number" ||
    !Number.isInteger(row.quantity_scale) ||
    row.quantity_scale < 0 ||
    row.quantity_scale > 6 ||
    !isPositiveDecimalString(row.quantity_step) ||
    !isNonEmptyString(row.lifecycle_status) ||
    !isNonEmptyString(row.operational_hold) ||
    !isPositiveInteger(row.version)
  ) {
    throw new Error(`عقد ${label} غير صالح.`);
  }

  const baseUom = row.base_uom as OfferCatalogVariant["base_uom"];
  const uoms = row.uoms as OfferCatalogVariant["uoms"];
  const uomIds = uoms.map((uom) => uom.id);
  if (new Set(uomIds).size !== uomIds.length) {
    throw new Error(`عقد ${label} يحتوي وحدات قياس مكررة.`);
  }
  const matchingBase = uoms.filter(
    (uom) =>
      uom.id === baseUom.id &&
      uom.code === baseUom.code &&
      uom.name === baseUom.name
  );
  if (matchingBase.length !== 1) {
    throw new Error(`عقد ${label} لا يطابق وحدة القياس الأساسية.`);
  }

  return row as OfferCatalogVariant;
};

const assertOfferCatalogPage = (value: unknown, label: string): CursorPage<OfferCatalogVariant> => {
  const page = assertPage<unknown>(value, label);
  return {
    ...page,
    items: page.items.map((item, index) =>
      assertOfferCatalogVariant(item, `${label} — الصنف ${index + 1}`)
    ),
  };
};

export const pagePath = (base: string, cursor: string | null, limit = 50) => {
  const separator = base.includes("?") ? "&" : "?";
  return `${base}${separator}limit=${limit}${
    cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""
  }`;
};

export async function fetchOfferDefinitions(
  authFetch: AuthFetch,
  cursor: string | null,
  signal?: AbortSignal
) {
  return assertPage<OfferDefinition>(
    await authFetch(pagePath("/offers/definitions", cursor), { signal }),
    "تعريفات العروض"
  );
}

export async function fetchOfferVersions(
  authFetch: AuthFetch,
  definitionId: number,
  cursor: string | null,
  signal?: AbortSignal
) {
  return assertPage<OfferVersion>(
    await authFetch(
      pagePath(`/offers/definitions/${definitionId}/versions`, cursor),
      { signal }
    ),
    "نسخ العرض"
  );
}

export async function fetchOfferCatalogVariants(
  authFetch: AuthFetch,
  cursor: string | null,
  signal?: AbortSignal
) {
  return assertOfferCatalogPage(
    await authFetch(pagePath("/offers/references/variants", cursor, 100), { signal }),
    "مراجع أصناف العروض"
  );
}

export async function resolveOfferCatalogVariants(
  authFetch: AuthFetch,
  ids: number[],
  signal?: AbortSignal
) {
  return assertOfferCatalogPage(
    await authFetch("/offers/references/variants/resolve", {
      method: "POST",
      signal,
      body: JSON.stringify({ ids }),
    }),
    "مراجع أصناف العرض المطلوبة"
  );
}

export async function fetchTaxJurisdictions(
  authFetch: AuthFetch,
  cursor: string | null,
  signal?: AbortSignal
) {
  return assertPage<TaxJurisdiction>(
    await authFetch(pagePath("/taxation/jurisdictions", cursor), { signal }),
    "النطاقات الضريبية"
  );
}

export async function fetchTaxRuleSets(
  authFetch: AuthFetch,
  cursor: string | null,
  signal?: AbortSignal
) {
  return assertPage<TaxRuleSet>(
    await authFetch(pagePath("/taxation/rule-sets", cursor), { signal }),
    "مجموعات الضرائب"
  );
}

export async function fetchTaxVersions(
  authFetch: AuthFetch,
  ruleSetId: number,
  cursor: string | null,
  signal?: AbortSignal
) {
  return assertPage<TaxVersion>(
    await authFetch(
      pagePath(`/taxation/rule-sets/${ruleSetId}/versions`, cursor),
      { signal }
    ),
    "نسخ الضرائب"
  );
}

export async function fetchOfferPolicy(authFetch: AuthFetch) {
  const value = (await authFetch("/offers/policy")) as ApprovalPolicy;
  if (!value || typeof value.maker_checker_enabled !== "boolean") {
    throw new Error("عقد سياسة اعتماد العروض غير صالح.");
  }
  return value;
}

export async function fetchTaxPolicy(authFetch: AuthFetch) {
  const value = (await authFetch("/taxation/policy")) as ApprovalPolicy;
  if (!value || typeof value.maker_checker_enabled !== "boolean") {
    throw new Error("عقد سياسة اعتماد الضرائب غير صالح.");
  }
  return value;
}

export async function offerPreview(
  authFetch: AuthFetch,
  payload: {
    customer_id?: number;
    branch_id?: number;
    channel_code?: string;
    as_of?: string;
    offer_revision_ceiling?: number;
    lines: Array<{ product_variant_id: number; components: Array<{ uom_id: number; quantity: string }> }>;
  }
) {
  return (await authFetch("/offers/preview", {
    method: "POST",
    body: JSON.stringify(payload),
  })) as OfferPreview;
}

export async function taxPreview(
  authFetch: AuthFetch,
  payload: {
    jurisdiction_id: number;
    customer_id?: number;
    document_type_code: string;
    as_of?: string;
    tax_revision_ceiling?: number;
    lines: Array<{ line_id: number; product_variant_id: number; amount: string }>;
  }
) {
  return (await authFetch("/taxation/preview", {
    method: "POST",
    body: JSON.stringify(payload),
  })) as TaxPreview;
}

export async function lifecycleCommand(
  authFetch: AuthFetch,
  family: "offers" | "taxation",
  versionId: number,
  action: "submit" | "publish" | "approve" | "cancel",
  expectedVersion: number,
  reason: string
) {
  const cleanReason = reason.trim();
  if (cleanReason.length < 3 || cleanReason.length > 1000) throw new Error("سبب الإجراء يجب أن يكون بين 3 و1000 حرف.");
  return authFetch(`/${family}/versions/${versionId}/${action}`, {
    method: "POST",
    body: JSON.stringify({
      request_id: crypto.randomUUID(),
      expected_version: expectedVersion,
      reason: cleanReason,
    }),
  });
}

export async function validateVersion(
  authFetch: AuthFetch,
  family: "offers" | "taxation",
  versionId: number
) {
  return authFetch(`/${family}/versions/${versionId}/validate`, {
    method: "POST",
  });
}

export async function fetchCatalogVariants(authFetch: AuthFetch, cursor: string | null, signal?: AbortSignal) {
  return assertPage<import("./contracts").CatalogVariant>(await authFetch(pagePath("/catalog/variants", cursor, 100), { signal }), "أصناف الكتالوج");
}

const jsonRequest = (method: "POST" | "PATCH" | "PUT" | "DELETE", body: Record<string, unknown>): RequestInit => ({ method, body: JSON.stringify(body) });
const mutationBody = (body: Record<string, unknown>) => ({ request_id: crypto.randomUUID(), ...body });

export const createOfferDefinition = (authFetch: AuthFetch, input: { code: string; name: string; description?: string | null }) => authFetch("/offers/definitions", jsonRequest("POST", mutationBody(input)));
export const updateOfferDefinition = (authFetch: AuthFetch, id: number, version: number, input: { code: string; name: string; description?: string | null }) => authFetch(`/offers/definitions/${id}`, jsonRequest("PATCH", mutationBody({ expected_version: version, ...input })));
export const deleteOfferDefinition = (authFetch: AuthFetch, id: number, version: number, reason: string) => authFetch(`/offers/definitions/${id}`, jsonRequest("DELETE", mutationBody({ expected_version: version, reason })));
export const createOfferVersion = (authFetch: AuthFetch, definitionId: number, definitionVersion: number, input: Record<string, unknown>) => authFetch(`/offers/definitions/${definitionId}/versions`, jsonRequest("POST", mutationBody({ expected_definition_version: definitionVersion, ...input })));
export const updateOfferVersion = (authFetch: AuthFetch, id: number, version: number, input: Record<string, unknown>) => authFetch(`/offers/versions/${id}`, jsonRequest("PUT", mutationBody({ expected_version: version, ...input })));
export const deleteOfferVersion = (authFetch: AuthFetch, id: number, version: number, reason: string) => authFetch(`/offers/versions/${id}`, jsonRequest("DELETE", mutationBody({ expected_version: version, reason })));

export const createTaxJurisdiction = (authFetch: AuthFetch, input: Record<string, unknown>) => authFetch("/taxation/jurisdictions", jsonRequest("POST", mutationBody(input)));
export const updateTaxJurisdiction = (authFetch: AuthFetch, id: number, version: number, input: Record<string, unknown>) => authFetch(`/taxation/jurisdictions/${id}`, jsonRequest("PATCH", mutationBody({ expected_version: version, ...input })));
export const deleteTaxJurisdiction = (authFetch: AuthFetch, id: number, version: number, reason: string) => authFetch(`/taxation/jurisdictions/${id}`, jsonRequest("DELETE", mutationBody({ expected_version: version, reason })));
export const createTaxRuleSet = (authFetch: AuthFetch, input: { code: string; name: string; description?: string | null }) => authFetch("/taxation/rule-sets", jsonRequest("POST", mutationBody(input)));
export const updateTaxRuleSet = (authFetch: AuthFetch, id: number, version: number, input: { code: string; name: string; description?: string | null }) => authFetch(`/taxation/rule-sets/${id}`, jsonRequest("PATCH", mutationBody({ expected_version: version, ...input })));
export const deleteTaxRuleSet = (authFetch: AuthFetch, id: number, version: number, reason: string) => authFetch(`/taxation/rule-sets/${id}`, jsonRequest("DELETE", mutationBody({ expected_version: version, reason })));
export const createTaxVersion = (authFetch: AuthFetch, ruleSetId: number, ruleSetVersion: number, input: Record<string, unknown>) => authFetch(`/taxation/rule-sets/${ruleSetId}/versions`, jsonRequest("POST", mutationBody({ expected_rule_set_version: ruleSetVersion, ...input })));
export const updateTaxVersion = (authFetch: AuthFetch, id: number, version: number, input: Record<string, unknown>) => authFetch(`/taxation/versions/${id}`, jsonRequest("PUT", mutationBody({ expected_version: version, ...input })));
export const deleteTaxVersion = (authFetch: AuthFetch, id: number, version: number, reason: string) => authFetch(`/taxation/versions/${id}`, jsonRequest("DELETE", mutationBody({ expected_version: version, reason })));
