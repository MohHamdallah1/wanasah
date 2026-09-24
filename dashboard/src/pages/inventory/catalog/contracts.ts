import { parseQuantity, type Quantity, validateVariantQuantity } from "../quantity";

const DB_INT_MAX = 2_147_483_647;
const MAX_CURSOR_LENGTH = 512;

export interface UomRef { id: number; code: string; name: string }
export interface CatalogProduct {
  id: number; code: string; name: string; description: string | null;
  brand: string | null; category: string | null; version: number;
}
export interface CatalogVariant {
  id: number; product_id: number; sku: string; gtin: string | null; name: string;
  base_uom: UomRef; quantity_scale: number; quantity_step: Quantity;
  lot_control_mode: "NONE" | "OPTIONAL" | "REQUIRED";
  expiry_control_mode: "NONE" | "OPTIONAL" | "REQUIRED";
  lifecycle_status: "DRAFT" | "ACTIVE" | "RETIRING" | "ARCHIVED";
  operational_hold: "NONE" | "SALES_HOLD" | "RECALL";
  lifecycle_revision: number;
  version: number;
  published_at: string | null;
  retired_at: string | null;
  archived_at: string | null;
}
export interface UomConversion { id:number; product_variant_id:number; from_uom:UomRef; to_uom:UomRef; numerator:Quantity; denominator:Quantity; quantity_scale:number; version:number }
export interface ProductBarcode { id:number; product_variant_id:number; uom:UomRef; barcode:string; barcode_type:"EAN8"|"EAN13"|"UPC_A"|"GTIN14"|"GS1_128"|"INTERNAL"; is_primary:boolean; valid_from:string; valid_to:string|null; is_active:boolean; version:number }
export interface CursorPage<T> { items: T[]; next_cursor: string | null; has_more: boolean }

const record = (value: unknown, message: string): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(message);
  return value as Record<string, unknown>;
};
const integer = (value: unknown, field: string, min = 0): number => {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < min || value > DB_INT_MAX) throw new Error(`حقل ${field} في عقد الكتالوج غير صالح.`);
  return value;
};
const requiredString = (value: unknown, field: string, max: number): string => {
  if (typeof value !== "string" || !value.trim() || value.length > max) throw new Error(`حقل ${field} في عقد الكتالوج غير صالح.`);
  return value;
};
const optionalString = (value: unknown, field: string, max: number): string | null =>
  value === null ? null : requiredString(value, field, max);
const parseUom = (raw: unknown): UomRef => {
  const row = record(raw, "وحدة القياس غير صالحة.");
  return { id: integer(row.id, "uom.id", 1), code: requiredString(row.code, "uom.code", 20), name: requiredString(row.name, "uom.name", 50) };
};
const cursorPage = <T>(raw: unknown, parseItem: (value: unknown) => T): CursorPage<T> => {
  const row = record(raw, "صفحة الكتالوج غير صالحة.");
  if (!Array.isArray(row.items) || row.items.length > 200 || typeof row.has_more !== "boolean") throw new Error("صفحة الكتالوج غير صالحة.");
  const next = row.next_cursor === null ? null : requiredString(row.next_cursor, "next_cursor", MAX_CURSOR_LENGTH);
  if (row.has_more !== (next !== null)) throw new Error("ترقيم الكتالوج غير متسق.");
  return { items: row.items.map(parseItem), next_cursor: next, has_more: row.has_more };
};

export const parseUoms = (raw: unknown): UomRef[] => {
  const row = record(raw, "استجابة وحدات القياس غير صالحة.");
  if (!Array.isArray(row.items) || row.items.length > 100) throw new Error("قائمة وحدات القياس غير صالحة.");
  return row.items.map(parseUom);
};
export const parseProducts = (raw: unknown): CursorPage<CatalogProduct> => cursorPage(raw, (item) => {
  const row = record(item, "عائلة المنتج غير صالحة.");
  return {
    id: integer(row.id, "product.id", 1), code: requiredString(row.code, "product.code", 100),
    name: requiredString(row.name, "product.name", 150), description: optionalString(row.description, "description", 4000),
    brand: optionalString(row.brand, "brand", 100), category: optionalString(row.category, "category", 100),
    version: integer(row.version, "product.version", 1),
  };
});
export const parseCatalogVariant = (item: unknown): CatalogVariant => {
  const row = record(item, "SKU غير صالح.");
  const scale = integer(row.quantity_scale, "quantity_scale");
  if (scale > 6) throw new Error("دقة كمية SKU غير صالحة.");
  const step = parseQuantity(row.quantity_step, "quantity_step");
  const lifecycle = row.lifecycle_status;
  const hold = row.operational_hold;
  const lot = row.lot_control_mode;
  const expiry = row.expiry_control_mode;
  if (!["DRAFT", "ACTIVE", "RETIRING", "ARCHIVED"].includes(String(lifecycle))) throw new Error("حالة SKU غير صالحة.");
  if (!["NONE", "SALES_HOLD", "RECALL"].includes(String(hold))) throw new Error("حالة إيقاف SKU غير صالحة.");
  if (!["NONE", "OPTIONAL", "REQUIRED"].includes(String(lot)) || !["NONE", "OPTIONAL", "REQUIRED"].includes(String(expiry))) throw new Error("سياسة الدفعة أو الصلاحية غير صالحة.");
  return {
    id: integer(row.id, "variant.id", 1), product_id: integer(row.product_id, "product_id", 1),
    sku: requiredString(row.sku, "sku", 100), gtin: optionalString(row.gtin, "gtin", 14), name: requiredString(row.name, "name", 200),
    base_uom: parseUom(row.base_uom), quantity_scale: scale, quantity_step: step,
    lot_control_mode: lot as CatalogVariant["lot_control_mode"], expiry_control_mode: expiry as CatalogVariant["expiry_control_mode"],
    lifecycle_status: lifecycle as CatalogVariant["lifecycle_status"], operational_hold: hold as CatalogVariant["operational_hold"],
    lifecycle_revision: integer(row.lifecycle_revision, "lifecycle_revision", 1),
    version: integer(row.version, "version", 1),
    published_at: optionalString(row.published_at, "published_at", 64),
    retired_at: optionalString(row.retired_at, "retired_at", 64),
    archived_at: optionalString(row.archived_at, "archived_at", 64),
  };
};
export const parseVariants = (raw: unknown): CursorPage<CatalogVariant> => cursorPage(raw, parseCatalogVariant);
export const parseConversions = (raw:unknown):UomConversion[] => {
  const page=record(raw,"استجابة تحويلات UOM غير صالحة."); if(!Array.isArray(page.items)||page.items.length>200)throw new Error("تحويلات UOM غير صالحة.");
  return page.items.map((item)=>{const row=record(item,"تحويل UOM غير صالح.");return{id:integer(row.id,"conversion.id",1),product_variant_id:integer(row.product_variant_id,"product_variant_id",1),from_uom:parseUom(row.from_uom),to_uom:parseUom(row.to_uom),numerator:parseQuantity(row.numerator,"numerator"),denominator:parseQuantity(row.denominator,"denominator"),quantity_scale:integer(row.quantity_scale,"quantity_scale"),version:integer(row.version,"version",1)};});
};
export const parseBarcodes = (raw:unknown):ProductBarcode[] => {
  const page=record(raw,"استجابة الباركود غير صالحة."); if(!Array.isArray(page.items)||page.items.length>500)throw new Error("قائمة الباركود غير صالحة.");
  return page.items.map((item)=>{const row=record(item,"باركود غير صالح.");const type=String(row.barcode_type) as ProductBarcode["barcode_type"];if(!["EAN8","EAN13","UPC_A","GTIN14","GS1_128","INTERNAL"].includes(type))throw new Error("نوع الباركود غير صالح.");return{id:integer(row.id,"barcode.id",1),product_variant_id:integer(row.product_variant_id,"product_variant_id",1),uom:parseUom(row.uom),barcode:requiredString(row.barcode,"barcode",128),barcode_type:type,is_primary:row.is_primary===true,valid_from:requiredString(row.valid_from,"valid_from",64),valid_to:row.valid_to===null?null:requiredString(row.valid_to,"valid_to",64),is_active:row.is_active===true,version:integer(row.version,"version",1)};});
};

export interface ProductDraft { code: string; name: string; description: string; brand: string; category: string }
export interface VariantDraft {
  product_id: string; sku: string; gtin: string; name: string; base_uom_id: string;
  quantity_scale: string; quantity_step: string;
  lot_control_mode: CatalogVariant["lot_control_mode"];
  expiry_control_mode: CatalogVariant["expiry_control_mode"];
}
const cleanOptional = (value: string): string | null => value.trim() || null;
export const buildProductPayload = (draft: ProductDraft) => {
  const code = draft.code.trim().toUpperCase();
  const name = draft.name.trim();
  if (!/^[A-Z0-9][A-Z0-9_.-]*$/.test(code) || code.length > 100) throw new Error("كود العائلة غير صالح.");
  if (!name || name.length > 150) throw new Error("اسم عائلة المنتج غير صالح.");
  return { request_id: crypto.randomUUID(), code, name, description: cleanOptional(draft.description), brand: cleanOptional(draft.brand), category: cleanOptional(draft.category) };
};
export const buildVariantPayload = (draft: VariantDraft) => {
  const productId = integer(Number(draft.product_id), "product_id", 1);
  const baseUomId = integer(Number(draft.base_uom_id), "base_uom_id", 1);
  const scale = integer(Number(draft.quantity_scale), "quantity_scale");
  if (scale > 6) throw new Error("دقة الكمية يجب أن تكون بين 0 و6.");
  const rawStep = parseQuantity(draft.quantity_step.trim(), "quantity_step");
  const step = validateVariantQuantity(rawStep, scale, rawStep, "quantity_step");
  const sku = draft.sku.trim().toUpperCase();
  const name = draft.name.trim();
  const gtin = cleanOptional(draft.gtin);
  if (!sku || sku.length > 100) throw new Error("SKU مطلوب ولا يتجاوز 100 حرف.");
  if (!name || name.length > 200) throw new Error("اسم SKU مطلوب ولا يتجاوز 200 حرف.");
  if (gtin && !/^(?:\d{8}|\d{12}|\d{13}|\d{14})$/.test(gtin)) throw new Error("GTIN غير صالح.");
  return { request_id: crypto.randomUUID(), product_id: productId, sku, gtin, name, base_uom_id: baseUomId, quantity_scale: scale, quantity_step: step, lot_control_mode: draft.lot_control_mode, expiry_control_mode: draft.expiry_control_mode };
};
export interface UomConversionCommandPayload {
  from_uom_id: number;
  to_uom_id: number;
  numerator: Quantity;
  denominator: Quantity;
  quantity_scale: number;
}

export const buildConversionCommandPayload = (
  draft: {
    from_uom_id: string;
    to_uom_id: string;
    numerator: string;
    denominator: string;
    quantity_scale: string;
  },
): UomConversionCommandPayload => {
  const quantityScale = integer(
    Number(draft.quantity_scale),
    "quantity_scale",
  );
  if (quantityScale > 6) {
    throw new Error(
      "دقة التحويل يجب أن تكون بين 0 و6.",
    );
  }
  return {
    from_uom_id: integer(
      Number(draft.from_uom_id),
      "from_uom_id",
      1,
    ),
    to_uom_id: integer(
      Number(draft.to_uom_id),
      "to_uom_id",
      1,
    ),
    numerator: parseQuantity(
      draft.numerator,
      "numerator",
    ),
    denominator: parseQuantity(
      draft.denominator,
      "denominator",
    ),
    quantity_scale: quantityScale,
  };
};

export const buildConversionPayload = (
  draft: {
    from_uom_id: string;
    to_uom_id: string;
    numerator: string;
    denominator: string;
    quantity_scale: string;
  },
) => ({
  request_id: crypto.randomUUID(),
  ...buildConversionCommandPayload(draft),
});
export const buildBarcodePayload=(draft:{uom_id:string;barcode:string;barcode_type:ProductBarcode["barcode_type"];is_primary:boolean})=>({request_id:crypto.randomUUID(),uom_id:integer(Number(draft.uom_id),"uom_id",1),barcode:requiredString(draft.barcode.trim(),"barcode",128),barcode_type:draft.barcode_type,is_primary:draft.is_primary,valid_from:new Date().toISOString(),valid_to:null});
export const parseMutationMessage = (raw: unknown): string => requiredString(record(raw, "استجابة الكتالوج غير صالحة.").message, "message", 1000);

export const parseConversionMutation = (
  raw: unknown,
): {
  message: string;
  conversion: UomConversion;
} => {
  const row = record(
    raw,
    "استجابة تحويل UOM غير صالحة.",
  );
  const conversionRaw = record(
    row.conversion,
    "استجابة تحويل UOM غير صالحة.",
  );
  const parsed = parseConversions({
    items: [conversionRaw],
  });
  if (parsed.length !== 1) {
    throw new Error(
      "استجابة تحويل UOM غير صالحة.",
    );
  }
  return {
    message: requiredString(
      row.message,
      "message",
      1000,
    ),
    conversion: parsed[0],
  };
};

export interface ArchiveBlocker { code: string; count: number; sample_id: number | null }
export interface ArchivePreflight {
  variant_id: number;
  lifecycle_status: CatalogVariant["lifecycle_status"];
  version: number;
  can_archive: boolean;
  blockers: ArchiveBlocker[];
}
export interface ProductLocationAssignment {
  id: number;
  location: { id: number; code: string; name: string; location_type: string };
  product_variant: { id: number; sku: string; name: string; lifecycle_status: CatalogVariant["lifecycle_status"] };
  operational_flags: { inbound_enabled: boolean; outbound_enabled: boolean };
  version: number;
  created_by: number;
  created_at: string;
  updated_at: string;
}

const parseLifecycle = (value: unknown): CatalogVariant["lifecycle_status"] => {
  if (!["DRAFT", "ACTIVE", "RETIRING", "ARCHIVED"].includes(String(value))) throw new Error("حالة دورة الحياة غير صالحة.");
  return value as CatalogVariant["lifecycle_status"];
};
const parseBlocker = (value: unknown): ArchiveBlocker => {
  const row = record(value, "مانع الأرشفة غير صالح.");
  return {
    code: requiredString(row.code, "blocker.code", 100),
    count: integer(row.count, "blocker.count", 1),
    sample_id: row.sample_id === null ? null : integer(row.sample_id, "blocker.sample_id", 1),
  };
};
export const parseVariantMutation = (raw: unknown): { message: string; variant: CatalogVariant } => {
  const row = record(raw, "استجابة أمر دورة الحياة غير صالحة.");
  return { message: requiredString(row.message, "message", 1000), variant: parseCatalogVariant(row.variant) };
};
export const parseArchivePreflight = (raw: unknown): ArchivePreflight => {
  const row = record(raw, "استجابة فحص الأرشفة غير صالحة.");
  if (!Array.isArray(row.blockers) || row.blockers.length > 20 || typeof row.can_archive !== "boolean") throw new Error("قائمة موانع الأرشفة غير صالحة.");
  return {
    variant_id: integer(row.variant_id, "variant_id", 1),
    lifecycle_status: parseLifecycle(row.lifecycle_status),
    version: integer(row.version, "version", 1),
    can_archive: row.can_archive,
    blockers: row.blockers.map(parseBlocker),
  };
};
const parseProductLocation = (value: unknown): ProductLocationAssignment => {
  const row = record(value, "ربط الصنف بالموقع غير صالح.");
  const location = record(row.location, "هوية الموقع غير صالحة.");
  const variant = record(row.product_variant, "هوية الصنف غير صالحة.");
  const flags = record(row.operational_flags, "صلاحيات تشغيل الصنف غير صالحة.");
  if (typeof flags.inbound_enabled !== "boolean" || typeof flags.outbound_enabled !== "boolean") throw new Error("صلاحيات تشغيل الصنف غير صالحة.");
  return {
    id: integer(row.id, "product_location.id", 1),
    location: { id: integer(location.id, "location.id", 1), code: requiredString(location.code, "location.code", 100), name: requiredString(location.name, "location.name", 150), location_type: requiredString(location.location_type, "location.location_type", 30) },
    product_variant: { id: integer(variant.id, "variant.id", 1), sku: requiredString(variant.sku, "variant.sku", 100), name: requiredString(variant.name, "variant.name", 200), lifecycle_status: parseLifecycle(variant.lifecycle_status) },
    operational_flags: { inbound_enabled: flags.inbound_enabled, outbound_enabled: flags.outbound_enabled },
    version: integer(row.version, "product_location.version", 1), created_by: integer(row.created_by, "created_by", 1),
    created_at: requiredString(row.created_at, "created_at", 64), updated_at: requiredString(row.updated_at, "updated_at", 64),
  };
};
export const parseProductLocations = (raw: unknown): CursorPage<ProductLocationAssignment> => cursorPage(raw, parseProductLocation);
export const buildLifecycleCommand = (variant: CatalogVariant, reason: string) => {
  const clean = reason.trim();
  if (clean.length < 3 || clean.length > 1000) throw new Error("سبب الإجراء مطلوب وبحد أدنى 3 أحرف.");
  return { request_id: crypto.randomUUID(), expected_version: variant.version, reason: clean };
};

export type SimpleProductVariant = CatalogVariant;
export type SimpleProductVariantCursorPage = CursorPage<CatalogVariant>;
export const parseCatalogPage = parseVariants;
