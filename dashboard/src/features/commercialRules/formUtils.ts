import type { OfferProduct, OfferScope, OfferType, OfferVersion, TaxScope, TaxVersion } from "./contracts";

export type EditableOfferScope = { scope_type: OfferScope["scope_type"]; target: string };
export type EditableOfferProduct = { role: OfferProduct["role"]; product_variant_id: string };
export type EditableTier = { minimum_quantity: string; reward_type: "PERCENTAGE_DISCOUNT" | "FIXED_DISCOUNT" | "FREE_QUANTITY"; reward_value: string };
export type OfferVersionForm = {
  offer_type: OfferType; currency_code: string; priority: string; stacking_mode: "EXCLUSIVE" | "STACKABLE";
  effective_from: string; effective_to: string; percentage: string; fixed_amount: string; buy_quantity: string; get_quantity: string;
  qualifying_quantity: string; free_quantity: string; tiers: EditableTier[]; bundle_quantity: string;
  bundle_reward_type: "PERCENTAGE_DISCOUNT" | "FIXED_DISCOUNT" | "FIXED_PRICE"; bundle_reward_value: string;
  max_applications_per_document: string; max_discount_amount: string; max_reward_quantity: string;
  scopes: EditableOfferScope[]; products: EditableOfferProduct[];
};
export type EditableTaxComponent = { component_code: string; name: string; rate: string; basis_mode: "TAXABLE_BASE" | "TAXABLE_BASE_PLUS_PRIOR_TAX"; reporting_code: string };
export type EditableTaxScope = { scope_type: TaxScope["scope_type"]; target: string };
export type TaxVersionForm = { priority: string; price_mode: "EXCLUSIVE" | "INCLUSIVE"; effective_from: string; effective_to: string; components: EditableTaxComponent[]; scopes: EditableTaxScope[] };

const localInput = (value?: string | null) => {
  const date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) return "";
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return shifted.toISOString().slice(0, 16);
};
const toIso = (value: string, label: string) => {
  if (!value) throw new Error(`${label} مطلوب.`);
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) throw new Error(`${label} غير صالح.`);
  return date.toISOString();
};
const positiveInteger = (value: string, label: string) => {
  if (!/^[1-9]\d*$/.test(value.trim())) throw new Error(`${label} يجب أن يكون رقماً صحيحاً موجباً.`);
  const result = Number(value);
  if (!Number.isSafeInteger(result)) throw new Error(`${label} أكبر من الحد الآمن.`);
  return result;
};
const nonNegativeInteger = (value: string, label: string) => {
  if (!/^\d+$/.test(value.trim())) throw new Error(`${label} يجب أن يكون عدداً صحيحاً غير سالب.`);
  const result = Number(value);
  if (!Number.isSafeInteger(result)) throw new Error(`${label} أكبر من الحد الآمن.`);
  return result;
};
const decimal = (value: string, label: string, allowZero: boolean) => {
  const clean = value.trim();
  if (!/^\d+(?:\.\d+)?$/.test(clean)) throw new Error(`${label} يجب أن يكون رقماً عشرياً دقيقاً.`);
  if (!allowZero && /^0+(?:\.0+)?$/.test(clean)) throw new Error(`${label} يجب أن يكون أكبر من صفر.`);
  return clean;
};
const positiveDecimal = (value: string, label: string) => decimal(value, label, false);
const nonNegativeDecimal = (value: string, label: string) => decimal(value, label, true);
const taxRate = (value: string, label: string) => {
  const clean = nonNegativeDecimal(value, label);
  const fraction = clean.split(".")[1] ?? "";
  if (fraction.length > 8) throw new Error(`${label} يقبل 8 منازل عشرية كحد أقصى.`);
  return clean;
};
const percentage = (value: string, label: string) => {
  const clean = positiveDecimal(value, label);
  const [wholeRaw, fraction = ""] = clean.split(".");
  const whole = wholeRaw.replace(/^0+(?=\d)/, "") || "0";
  if (whole.length > 3 || Number(whole) > 100 || (whole === "100" && /[1-9]/.test(fraction))) throw new Error(`${label} يجب ألا تتجاوز 100.`);
  return clean;
};
const decimalParts = (value: string) => {
  const [wholeRaw, fractionRaw = ""] = value.split(".");
  const whole = wholeRaw.replace(/^0+/, "") || "0";
  const fraction = fractionRaw.replace(/0+$/, "");
  return { whole, fraction };
};
const decimalCompare = (left: string, right: string) => {
  const a = decimalParts(left); const b = decimalParts(right);
  if (a.whole.length !== b.whole.length) return a.whole.length > b.whole.length ? 1 : -1;
  if (a.whole !== b.whole) return a.whole > b.whole ? 1 : -1;
  const size = Math.max(a.fraction.length, b.fraction.length);
  const af = a.fraction.padEnd(size, "0"); const bf = b.fraction.padEnd(size, "0");
  if (af === bf) return 0;
  return af > bf ? 1 : -1;
};

const buildCaps = (form: OfferVersionForm) => {
  const result: Record<string, unknown> = {};
  if (form.max_applications_per_document.trim()) result.max_applications_per_document = positiveInteger(form.max_applications_per_document, "حد مرات التطبيق");
  if (form.max_discount_amount.trim()) result.max_discount_amount = positiveDecimal(form.max_discount_amount, "الحد الأعلى للخصم");
  if (form.max_reward_quantity.trim()) result.max_reward_quantity = positiveDecimal(form.max_reward_quantity, "الحد الأعلى للكمية المجانية");
  return Object.keys(result).length ? result : undefined;
};

export const emptyOfferVersionForm = (): OfferVersionForm => ({
  offer_type: "PERCENTAGE_DISCOUNT", currency_code: "", priority: "0", stacking_mode: "EXCLUSIVE",
  effective_from: localInput(), effective_to: "", percentage: "10", fixed_amount: "1", buy_quantity: "1", get_quantity: "1",
  qualifying_quantity: "1", free_quantity: "1", tiers: [{ minimum_quantity: "1", reward_type: "PERCENTAGE_DISCOUNT", reward_value: "5" }],
  bundle_quantity: "1", bundle_reward_type: "PERCENTAGE_DISCOUNT", bundle_reward_value: "5",
  max_applications_per_document: "", max_discount_amount: "", max_reward_quantity: "", scopes: [], products: [],
});

export const offerVersionToForm = (version: OfferVersion): OfferVersionForm => {
  const form = emptyOfferVersionForm();
  const payload = version.payload;
  const get = (key: string, fallback: string) => payload[key] == null ? fallback : String(payload[key]);
  form.offer_type = version.offer_type; form.currency_code = version.currency_code ?? ""; form.priority = String(version.priority);
  form.stacking_mode = version.stacking_mode; form.effective_from = localInput(version.effective_from); form.effective_to = version.effective_to ? localInput(version.effective_to) : "";
  form.percentage = get("percentage", form.percentage); form.fixed_amount = get("amount", form.fixed_amount); form.buy_quantity = get("buy_quantity", form.buy_quantity);
  form.get_quantity = get("get_quantity", form.get_quantity); form.qualifying_quantity = get("qualifying_quantity", form.qualifying_quantity); form.free_quantity = get("free_quantity", form.free_quantity);
  form.bundle_quantity = get("bundle_quantity", form.bundle_quantity); form.bundle_reward_type = (payload.reward_type as OfferVersionForm["bundle_reward_type"]) ?? form.bundle_reward_type;
  form.bundle_reward_value = get("reward_value", form.bundle_reward_value);
  const caps = payload.caps && typeof payload.caps === "object" ? payload.caps as Record<string, unknown> : {};
  form.max_applications_per_document = caps.max_applications_per_document == null ? "" : String(caps.max_applications_per_document);
  form.max_discount_amount = caps.max_discount_amount == null ? "" : String(caps.max_discount_amount);
  form.max_reward_quantity = caps.max_reward_quantity == null ? "" : String(caps.max_reward_quantity);
  if (Array.isArray(payload.tiers)) form.tiers = payload.tiers.map((raw) => { const row = raw as Record<string, unknown>; return { minimum_quantity: String(row.minimum_quantity ?? ""), reward_type: (row.reward_type as EditableTier["reward_type"]) ?? "PERCENTAGE_DISCOUNT", reward_value: String(row.reward_value ?? "") }; });
  form.scopes = version.scopes.map((scope) => ({ scope_type: scope.scope_type, target: scope.product_variant_id != null ? String(scope.product_variant_id) : scope.customer_id != null ? String(scope.customer_id) : scope.branch_id != null ? String(scope.branch_id) : scope.channel_code ?? "" }));
  form.products = version.products.map((product) => ({ role: product.role, product_variant_id: String(product.product_variant_id) }));
  return form;
};

const offerScopePayload = (scope: EditableOfferScope) => {
  const target = scope.target.trim(); if (!target) throw new Error("كل نطاق عرض يحتاج قيمة هدف.");
  if (scope.scope_type === "CHANNEL") return { scope_type: scope.scope_type, channel_code: target.toUpperCase() };
  const id = positiveInteger(target, "معرّف نطاق العرض");
  if (scope.scope_type === "PRODUCT_VARIANT") return { scope_type: scope.scope_type, product_variant_id: id };
  if (scope.scope_type === "CUSTOMER") return { scope_type: scope.scope_type, customer_id: id };
  return { scope_type: scope.scope_type, branch_id: id };
};

export const buildOfferVersionPayload = (form: OfferVersionForm) => {
  const caps = buildCaps(form); let payload: Record<string, unknown>;
  switch (form.offer_type) {
    case "PERCENTAGE_DISCOUNT": payload = { percentage: percentage(form.percentage, "نسبة الخصم") }; break;
    case "FIXED_DISCOUNT": payload = { amount: positiveDecimal(form.fixed_amount, "الخصم الثابت") }; break;
    case "BUY_X_GET_Y": payload = { buy_quantity: positiveDecimal(form.buy_quantity, "كمية الشراء"), get_quantity: positiveDecimal(form.get_quantity, "كمية المكافأة") }; break;
    case "FREE_GOODS": payload = { qualifying_quantity: positiveDecimal(form.qualifying_quantity, "الكمية المؤهلة"), free_quantity: positiveDecimal(form.free_quantity, "الكمية المجانية") }; break;
    case "QUANTITY_TIERS": {
      if (!form.tiers.length) throw new Error("أضف شريحة كمية واحدة على الأقل.");
      let previous: string | null = null;
      const tiers = form.tiers.map((tier, index) => {
        const minimum = positiveDecimal(tier.minimum_quantity, `حد الشريحة ${index + 1}`);
        if (previous !== null && decimalCompare(minimum, previous) <= 0) throw new Error("شرائح الكمية يجب أن تكون تصاعدية بدون تكرار.");
        previous = minimum;
        return { minimum_quantity: minimum, reward_type: tier.reward_type, reward_value: tier.reward_type === "PERCENTAGE_DISCOUNT" ? percentage(tier.reward_value, `قيمة الشريحة ${index + 1}`) : positiveDecimal(tier.reward_value, `قيمة الشريحة ${index + 1}`) };
      });
      payload = { tiers }; break;
    }
    case "BUNDLE": payload = { bundle_quantity: positiveDecimal(form.bundle_quantity, "كمية الحزمة"), reward_type: form.bundle_reward_type, reward_value: form.bundle_reward_type === "PERCENTAGE_DISCOUNT" ? percentage(form.bundle_reward_value, "قيمة مكافأة الحزمة") : positiveDecimal(form.bundle_reward_value, "قيمة مكافأة الحزمة") }; break;
  }
  if (caps) payload.caps = caps;
  const scopes = form.scopes.map(offerScopePayload);
  const scopeKeys = scopes.map((row) => JSON.stringify(row)); if (new Set(scopeKeys).size !== scopeKeys.length) throw new Error("يوجد نطاق عرض مكرر.");
  const products = form.products.map((row) => ({ role: row.role, product_variant_id: positiveInteger(row.product_variant_id, "معرّف منتج العرض") }));
  const productKeys = products.map((row) => `${row.role}:${row.product_variant_id}`); if (new Set(productKeys).size !== productKeys.length) throw new Error("يوجد منتج/دور مكرر في العرض.");
  const productScopes = scopes.filter((row) => row.scope_type === "PRODUCT_VARIANT");
  if (["PERCENTAGE_DISCOUNT", "FIXED_DISCOUNT"].includes(form.offer_type) && products.length) throw new Error("هذا النوع يستخدم نطاق المنتج ولا يقبل أدوار منتجات.");
  if (form.offer_type === "QUANTITY_TIERS" && (products.length || productScopes.length !== 1)) throw new Error("عرض الشرائح يحتاج نطاق منتج واحد فقط ولا يقبل أدوار منتجات.");
  if (["BUY_X_GET_Y", "FREE_GOODS"].includes(form.offer_type)) {
    if (productScopes.length) throw new Error("هذا النوع يستخدم أدوار المنتجات بدل نطاق المنتج.");
    const qualifying = products.filter((row) => row.role === "QUALIFYING"); const rewards = products.filter((row) => row.role === "REWARD");
    if (!qualifying.length || rewards.length !== 1 || products.some((row) => !["QUALIFYING", "REWARD"].includes(row.role))) throw new Error("يلزم منتج مؤهل واحد على الأقل ومنتج مكافأة واحد بالضبط.");
  }
  if (form.offer_type === "BUNDLE") {
    const components = products.filter((row) => row.role === "BUNDLE_COMPONENT");
    if (productScopes.length || components.length < 2 || components.length !== products.length) throw new Error("الحزمة تحتاج منتجين BUNDLE_COMPONENT على الأقل وبدون نطاق منتج.");
  }
  const usesMoney = form.offer_type === "FIXED_DISCOUNT" || (form.offer_type === "QUANTITY_TIERS" && form.tiers.some((tier) => tier.reward_type === "FIXED_DISCOUNT")) || (form.offer_type === "BUNDLE" && ["FIXED_DISCOUNT", "FIXED_PRICE"].includes(form.bundle_reward_type)) || Boolean(form.max_discount_amount.trim());
  const currency = form.currency_code.trim().toUpperCase(); if (usesMoney && !currency) throw new Error("رمز العملة مطلوب لهذا العرض.");
  const effectiveFrom = toIso(form.effective_from, "بداية العرض"); const effectiveTo = form.effective_to ? toIso(form.effective_to, "نهاية العرض") : null;
  if (effectiveTo && new Date(effectiveTo) <= new Date(effectiveFrom)) throw new Error("نهاية العرض يجب أن تكون بعد بدايته.");
  return { offer_type: form.offer_type, payload, currency_code: currency || null, priority: nonNegativeInteger(form.priority, "الأولوية"), stacking_mode: form.stacking_mode, effective_from: effectiveFrom, effective_to: effectiveTo, scopes, products };
};

export const emptyTaxVersionForm = (): TaxVersionForm => ({ priority: "0", price_mode: "EXCLUSIVE", effective_from: localInput(), effective_to: "", components: [{ component_code: "VAT", name: "VAT", rate: "0", basis_mode: "TAXABLE_BASE", reporting_code: "" }], scopes: [] });
export const taxVersionToForm = (version: TaxVersion): TaxVersionForm => ({
  priority: String(version.priority), price_mode: version.price_mode, effective_from: localInput(version.effective_from), effective_to: version.effective_to ? localInput(version.effective_to) : "",
  components: version.components.map((row) => ({ component_code: row.component_code, name: row.name, rate: row.rate, basis_mode: row.basis_mode, reporting_code: row.reporting_code ?? "" })),
  scopes: version.scopes.map((scope) => ({ scope_type: scope.scope_type, target: scope.jurisdiction_id != null ? String(scope.jurisdiction_id) : scope.product_variant_id != null ? String(scope.product_variant_id) : scope.customer_id != null ? String(scope.customer_id) : scope.document_type_code ?? "" })),
});
const taxScopePayload = (scope: EditableTaxScope) => {
  const target = scope.target.trim(); if (!target) throw new Error("كل نطاق ضريبي يحتاج قيمة هدف.");
  if (scope.scope_type === "DOCUMENT_TYPE") return { scope_type: scope.scope_type, document_type_code: target.toUpperCase() };
  const id = positiveInteger(target, "معرّف النطاق الضريبي");
  if (scope.scope_type === "JURISDICTION") return { scope_type: scope.scope_type, jurisdiction_id: id };
  if (scope.scope_type === "PRODUCT_VARIANT") return { scope_type: scope.scope_type, product_variant_id: id };
  return { scope_type: scope.scope_type, customer_id: id };
};
export const buildTaxVersionPayload = (form: TaxVersionForm) => {
  if (!form.components.length) throw new Error("يلزم مكوّن ضريبي واحد على الأقل.");
  const codes = new Set<string>();
  const components = form.components.map((row, index) => {
    const code = row.component_code.trim().toUpperCase(); const name = row.name.trim();
    if (!code || !name) throw new Error("كود واسم المكوّن الضريبي مطلوبان."); if (codes.has(code)) throw new Error("كود المكوّن الضريبي مكرر."); codes.add(code);
    return { component_code: code, name, sequence: index + 1, rate: taxRate(row.rate, `نسبة ${name}`), basis_mode: index === 0 ? "TAXABLE_BASE" : row.basis_mode, reporting_code: row.reporting_code.trim().toUpperCase() || null };
  });
  const scopes = form.scopes.map(taxScopePayload); const keys = scopes.map((row) => JSON.stringify(row)); if (new Set(keys).size !== keys.length) throw new Error("يوجد نطاق ضريبي مكرر.");
  const effectiveFrom = toIso(form.effective_from, "بداية القاعدة"); const effectiveTo = form.effective_to ? toIso(form.effective_to, "نهاية القاعدة") : null;
  if (effectiveTo && new Date(effectiveTo) <= new Date(effectiveFrom)) throw new Error("نهاية القاعدة يجب أن تكون بعد بدايتها.");
  return { priority: nonNegativeInteger(form.priority, "الأولوية"), price_mode: form.price_mode, effective_from: effectiveFrom, effective_to: effectiveTo, components, scopes };
};
