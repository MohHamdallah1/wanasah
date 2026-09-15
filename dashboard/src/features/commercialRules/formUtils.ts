import type { OfferProduct, OfferScope, OfferType, OfferVersion, TaxScope, TaxVersion } from "./contracts";

export type EditableOfferScope = { scope_type: OfferScope["scope_type"]; target: string; uom_id: string };
export type EditableOfferProduct = { role: OfferProduct["role"]; product_variant_id: string; uom_id: string; quantity_per_application: string };
export type EditableTier = { minimum_quantity: string; reward_type: "PERCENTAGE_DISCOUNT" | "FIXED_DISCOUNT" | "FREE_QUANTITY"; reward_value: string };
export type OfferVersionForm = {
  offer_type: OfferType; currency_code: string; priority: string; stacking_mode: "EXCLUSIVE" | "STACKABLE";
  effective_from: string; effective_to: string; percentage: string; fixed_amount: string; buy_quantity: string;
  qualifying_quantity: string; tiers: EditableTier[];
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
  const clean = nonNegativeDecimal(value, label); const [wholeRaw, fractionRaw = ""] = clean.split(".");
  const whole = wholeRaw.replace(/^0+/, "") || "0"; const fraction = fractionRaw.replace(/0+$/, "");
  if (fraction.length > 8) throw new Error(`${label} يقبل 8 منازل عشرية كحد أقصى.`);
  if (whole.length > 12) throw new Error(`${label} يتجاوز سعة NUMERIC(20,8).`);
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
const positiveQuantity = (value: string, label: string) => {
  const clean = positiveDecimal(value, label); const [wholeRaw, fractionRaw = ""] = clean.split(".");
  const whole = wholeRaw.replace(/^0+/, "") || "0"; const fraction = fractionRaw.replace(/0+$/, "");
  if (fraction.length > 6) throw new Error(`${label} لا يقبل أكثر من 6 منازل عشرية.`);
  if (whole.length > 14) throw new Error(`${label} يتجاوز سعة NUMERIC(20,6).`);
  return clean;
};
const quantityPercentage = (value: string, label: string) => percentage(positiveQuantity(value, label), label);
const offerChannelCode = (value: string) => {
  const clean = value.trim().toUpperCase();
  if (!/^[A-Z0-9][A-Z0-9_.:-]{0,49}$/.test(clean)) throw new Error("رمز القناة غير صالح.");
  return clean;
};
const offerCurrencyCode = (value: string) => {
  const clean = value.trim().toUpperCase();
  if (clean && !/^[A-Z][A-Z0-9]{2,9}$/.test(clean)) throw new Error("رمز العملة غير صالح.");
  return clean;
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
  effective_from: localInput(), effective_to: "", percentage: "10", fixed_amount: "1", buy_quantity: "1",
  qualifying_quantity: "1", tiers: [{ minimum_quantity: "1", reward_type: "PERCENTAGE_DISCOUNT", reward_value: "5" }],
  bundle_reward_type: "PERCENTAGE_DISCOUNT", bundle_reward_value: "5",
  max_applications_per_document: "", max_discount_amount: "", max_reward_quantity: "", scopes: [], products: [],
});

export const offerVersionToForm = (version: OfferVersion): OfferVersionForm => {
  const form = emptyOfferVersionForm();
  const payload = version.payload;
  const get = (key: string, fallback: string) => payload[key] == null ? fallback : String(payload[key]);
  form.offer_type = version.offer_type; form.currency_code = version.currency_code ?? ""; form.priority = String(version.priority);
  form.stacking_mode = version.stacking_mode; form.effective_from = localInput(version.effective_from); form.effective_to = version.effective_to ? localInput(version.effective_to) : "";
  form.percentage = get("percentage", form.percentage); form.fixed_amount = get("amount", form.fixed_amount); form.buy_quantity = get("buy_quantity", form.buy_quantity);
  form.qualifying_quantity = get("qualifying_quantity", form.qualifying_quantity);
  form.bundle_reward_type = (payload.reward_type as OfferVersionForm["bundle_reward_type"]) ?? form.bundle_reward_type;
  form.bundle_reward_value = get("reward_value", form.bundle_reward_value);
  const caps = payload.caps && typeof payload.caps === "object" ? payload.caps as Record<string, unknown> : {};
  form.max_applications_per_document = caps.max_applications_per_document == null ? "" : String(caps.max_applications_per_document);
  form.max_discount_amount = caps.max_discount_amount == null ? "" : String(caps.max_discount_amount);
  form.max_reward_quantity = caps.max_reward_quantity == null ? "" : String(caps.max_reward_quantity);
  if (Array.isArray(payload.tiers)) form.tiers = payload.tiers.map((raw) => { const row = raw as Record<string, unknown>; return { minimum_quantity: String(row.minimum_quantity ?? ""), reward_type: (row.reward_type as EditableTier["reward_type"]) ?? "PERCENTAGE_DISCOUNT", reward_value: String(row.reward_value ?? "") }; });
  form.scopes = version.scopes.map((scope) => ({ scope_type: scope.scope_type, target: scope.product_variant_id != null ? String(scope.product_variant_id) : scope.customer_id != null ? String(scope.customer_id) : scope.branch_id != null ? String(scope.branch_id) : scope.channel_code ?? "", uom_id: scope.uom_id == null ? "" : String(scope.uom_id) }));
  form.products = version.products.map((product) => ({ role: product.role, product_variant_id: String(product.product_variant_id), uom_id: String(product.uom_id), quantity_per_application: product.quantity_per_application ?? "" }));
  return form;
};

const offerScopePayload = (scope: EditableOfferScope) => {
  const target = scope.target.trim(); if (!target) throw new Error("كل نطاق عرض يحتاج قيمة هدف.");
  if (scope.scope_type === "CHANNEL") return { scope_type: scope.scope_type, channel_code: offerChannelCode(target) };
  const id = positiveInteger(target, "معرّف نطاق العرض");
  if (scope.scope_type === "PRODUCT_VARIANT") return { scope_type: scope.scope_type, product_variant_id: id, uom_id: scope.uom_id.trim() ? positiveInteger(scope.uom_id, "وحدة نطاق المنتج") : null };
  if (scope.scope_type === "CUSTOMER") return { scope_type: scope.scope_type, customer_id: id };
  return { scope_type: scope.scope_type, branch_id: id };
};

export const buildOfferVersionPayload = (form: OfferVersionForm) => {
  if (["BUY_X_GET_Y", "FREE_GOODS"].includes(form.offer_type) && form.max_reward_quantity.trim()) throw new Error("حد كمية المكافأة العام غير صالح للعروض متعددة وحدات القياس؛ استخدم حد مرات التطبيق.");
  const caps = buildCaps(form); let payload: Record<string, unknown>;
  switch (form.offer_type) {
    case "PERCENTAGE_DISCOUNT": payload = { percentage: percentage(form.percentage, "نسبة الخصم") }; break;
    case "FIXED_DISCOUNT": payload = { amount: positiveDecimal(form.fixed_amount, "الخصم الثابت") }; break;
    case "BUY_X_GET_Y": payload = { buy_quantity: positiveQuantity(form.buy_quantity, "كمية الشراء") }; break;
    case "FREE_GOODS": payload = { qualifying_quantity: positiveQuantity(form.qualifying_quantity, "الكمية المؤهلة") }; break;
    case "QUANTITY_TIERS": {
      if (!form.tiers.length) throw new Error("أضف شريحة كمية واحدة على الأقل.");
      let previous: string | null = null;
      const tiers = form.tiers.map((tier, index) => {
        const minimum = positiveQuantity(tier.minimum_quantity, `حد الشريحة ${index + 1}`);
        if (previous !== null && decimalCompare(minimum, previous) <= 0) throw new Error("شرائح الكمية يجب أن تكون تصاعدية بدون تكرار.");
        previous = minimum;
        return { minimum_quantity: minimum, reward_type: tier.reward_type, reward_value: tier.reward_type === "PERCENTAGE_DISCOUNT" ? quantityPercentage(tier.reward_value, `قيمة الشريحة ${index + 1}`) : positiveQuantity(tier.reward_value, `قيمة الشريحة ${index + 1}`) };
      });
      payload = { tiers }; break;
    }
    case "BUNDLE": payload = { reward_type: form.bundle_reward_type, reward_value: form.bundle_reward_type === "PERCENTAGE_DISCOUNT" ? percentage(form.bundle_reward_value, "قيمة مكافأة الحزمة") : positiveDecimal(form.bundle_reward_value, "قيمة مكافأة الحزمة") }; break;
  }
  if (caps) payload.caps = caps;
  const scopes = form.scopes.map(offerScopePayload);
  const scopeKeys = scopes.map((row) => JSON.stringify(row)); if (new Set(scopeKeys).size !== scopeKeys.length) throw new Error("يوجد نطاق عرض مكرر.");
  const products = form.products.map((row, index) => ({ role: row.role, product_variant_id: positiveInteger(row.product_variant_id, `منتج العرض ${index + 1}`), uom_id: positiveInteger(row.uom_id, `وحدة منتج العرض ${index + 1}`), quantity_per_application: row.quantity_per_application.trim() ? positiveQuantity(row.quantity_per_application, `كمية منتج العرض ${index + 1}`) : null }));
  const productKeys = products.map((row) => `${row.role}:${row.product_variant_id}:${row.uom_id}`); if (new Set(productKeys).size !== productKeys.length) throw new Error("يوجد منتج/وحدة/دور مكرر في العرض.");
  const productScopes = scopes.filter((row) => row.scope_type === "PRODUCT_VARIANT");
  if (productScopes.some((row, index) => row.uom_id == null && productScopes.some((other, otherIndex) => otherIndex !== index && other.product_variant_id === row.product_variant_id))) throw new Error("لا يمكن الجمع بين كل الوحدات ووحدة محددة لنفس المنتج.");
  if (["PERCENTAGE_DISCOUNT", "FIXED_DISCOUNT"].includes(form.offer_type) && products.length) throw new Error("هذا النوع يستخدم نطاق المنتج ولا يقبل أدوار منتجات.");
  if (form.offer_type === "QUANTITY_TIERS" && (products.length || productScopes.length !== 1 || productScopes[0].uom_id == null)) throw new Error("عرض الشرائح يحتاج منتجاً واحداً ووحدة قياس صريحة ولا يقبل أدوار منتجات.");
  if (["BUY_X_GET_Y", "FREE_GOODS"].includes(form.offer_type)) {
    if (productScopes.length) throw new Error("هذا النوع يستخدم أدوار المنتجات بدل نطاق المنتج.");
    const qualifying = products.filter((row) => row.role === "QUALIFYING"); const rewards = products.filter((row) => row.role === "REWARD");
    if (!qualifying.length || !rewards.length || products.some((row) => !["QUALIFYING", "REWARD"].includes(row.role))) throw new Error("يلزم منتج مؤهل واحد على الأقل ومكافأة واحدة على الأقل.");
    if (new Set(qualifying.map((row) => row.uom_id)).size !== 1) throw new Error("كل المنتجات المؤهلة في هذا العرض يجب أن تستخدم وحدة القياس نفسها.");
    if (qualifying.some((row) => row.quantity_per_application !== null)) throw new Error("كمية المنتجات المؤهلة تُحدد من حد الشراء/التأهيل، وليس من صف المنتج.");
    if (rewards.some((row) => row.quantity_per_application === null)) throw new Error("حدد كمية المكافأة لكل منتج مكافأة.");
  }
  if (form.offer_type === "BUNDLE") {
    const components = products.filter((row) => row.role === "BUNDLE_COMPONENT");
    if (productScopes.length || components.length < 2 || new Set(components.map((row) => row.product_variant_id)).size < 2 || components.length !== products.length || components.some((row) => row.quantity_per_application === null)) throw new Error("الحزمة تحتاج منتجين مختلفين على الأقل، ولكل مكوّن وحدة وكمية صريحتان، وبدون نطاق منتج.");
  }
  const usesMoney = form.offer_type === "FIXED_DISCOUNT" || (form.offer_type === "QUANTITY_TIERS" && form.tiers.some((tier) => tier.reward_type === "FIXED_DISCOUNT")) || (form.offer_type === "BUNDLE" && ["FIXED_DISCOUNT", "FIXED_PRICE"].includes(form.bundle_reward_type)) || Boolean(form.max_discount_amount.trim());
  const currency = offerCurrencyCode(form.currency_code); if (usesMoney && !currency) throw new Error("رمز العملة مطلوب لهذا العرض.");
  const effectiveFrom = toIso(form.effective_from, "بداية العرض"); const effectiveTo = form.effective_to ? toIso(form.effective_to, "نهاية العرض") : null;
  if (effectiveTo && new Date(effectiveTo) <= new Date(effectiveFrom)) throw new Error("نهاية العرض يجب أن تكون بعد بدايته.");
  return { offer_type: form.offer_type, payload, currency_code: currency || null, priority: nonNegativeInteger(form.priority, "الأولوية"), stacking_mode: form.stacking_mode, effective_from: effectiveFrom, effective_to: effectiveTo, scopes, products };
};

const taxStableCode = (value: string, label: string, maximum: number) => {
  const clean = value.trim().toUpperCase();
  if (!clean || clean.length > maximum || !/^[A-Z0-9][A-Z0-9_.:-]*$/.test(clean)) throw new Error(`${label} غير صالح.`);
  return clean;
};
const taxRequiredText = (value: string, label: string, maximum: number) => {
  const clean = value.trim();
  if (!clean || clean.length > maximum) throw new Error(`${label} غير صالح.`);
  return clean;
};

export const emptyTaxVersionForm = (): TaxVersionForm => ({ priority: "0", price_mode: "EXCLUSIVE", effective_from: localInput(), effective_to: "", components: [{ component_code: "VAT", name: "VAT", rate: "0", basis_mode: "TAXABLE_BASE", reporting_code: "" }], scopes: [] });
export const taxVersionToForm = (version: TaxVersion): TaxVersionForm => ({
  priority: String(version.priority), price_mode: version.price_mode, effective_from: localInput(version.effective_from), effective_to: version.effective_to ? localInput(version.effective_to) : "",
  components: version.components.map((row) => ({ component_code: row.component_code, name: row.name, rate: row.rate, basis_mode: row.basis_mode, reporting_code: row.reporting_code ?? "" })),
  scopes: version.scopes.map((scope) => ({ scope_type: scope.scope_type, target: scope.jurisdiction_id != null ? String(scope.jurisdiction_id) : scope.product_variant_id != null ? String(scope.product_variant_id) : scope.customer_id != null ? String(scope.customer_id) : scope.document_type_code ?? "" })),
});
const taxScopePayload = (scope: EditableTaxScope) => {
  const target = scope.target.trim(); if (!target) throw new Error("كل نطاق ضريبي يحتاج قيمة هدف.");
  if (scope.scope_type === "DOCUMENT_TYPE") return { scope_type: scope.scope_type, document_type_code: taxStableCode(target, "نوع المستند", 80) };
  const id = positiveInteger(target, "معرّف النطاق الضريبي");
  if (scope.scope_type === "JURISDICTION") return { scope_type: scope.scope_type, jurisdiction_id: id };
  if (scope.scope_type === "PRODUCT_VARIANT") return { scope_type: scope.scope_type, product_variant_id: id };
  return { scope_type: scope.scope_type, customer_id: id };
};
export const buildTaxVersionPayload = (form: TaxVersionForm) => {
  if (!form.components.length) throw new Error("يلزم مكوّن ضريبي واحد على الأقل.");
  if (form.components.length > 100) throw new Error("النسخة الضريبية لا تقبل أكثر من 100 مكوّن.");
  if (form.scopes.length > 500) throw new Error("النسخة الضريبية لا تقبل أكثر من 500 نطاق.");
  const codes = new Set<string>();
  const components = form.components.map((row, index) => {
    const code = taxStableCode(row.component_code, `كود المكوّن ${index + 1}`, 100); const name = taxRequiredText(row.name, `اسم المكوّن ${index + 1}`, 150);
    if (codes.has(code)) throw new Error("كود المكوّن الضريبي مكرر."); codes.add(code);
    const reportingCode = row.reporting_code.trim() ? taxStableCode(row.reporting_code, `Reporting code للمكوّن ${index + 1}`, 100) : null;
    return { component_code: code, name, sequence: index + 1, rate: taxRate(row.rate, `نسبة ${name}`), basis_mode: index === 0 ? "TAXABLE_BASE" : row.basis_mode, reporting_code: reportingCode };
  });
  const scopes = form.scopes.map(taxScopePayload); const keys = scopes.map((row) => JSON.stringify(row)); if (new Set(keys).size !== keys.length) throw new Error("يوجد نطاق ضريبي مكرر.");
  const effectiveFrom = toIso(form.effective_from, "بداية القاعدة"); const effectiveTo = form.effective_to ? toIso(form.effective_to, "نهاية القاعدة") : null;
  if (effectiveTo && new Date(effectiveTo) <= new Date(effectiveFrom)) throw new Error("نهاية القاعدة يجب أن تكون بعد بدايتها.");
  return { priority: nonNegativeInteger(form.priority, "الأولوية"), price_mode: form.price_mode, effective_from: effectiveFrom, effective_to: effectiveTo, components, scopes };
};
