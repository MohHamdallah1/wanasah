import { resolveAppLocale } from "@/lib/locale";

export interface WarehouseLocationsCopy {
  title: string;
  summary: (total: string, active: string) => string;
  refresh: string;
  newWarehouse: string;
  warehousesView: string;
  qualityDestinationsView: string;
  qualityDestinationsSummary: string;
  firstWarehouseTitle: string;
  firstWarehouseDescription: string;
  createFirstWarehouse: string;
  search: string;
  number: string;
  warehouse: string;
  code: string;
  branch: string;
  status: string;
  updated: string;
  actions: string;
  unassigned: string;
  active: string;
  inactive: string;
  editAction: string;
  deactivateAction: string;
  activateAction: string;
  emptySearch: string;
  emptyCreate: string;
  emptyNoAccess: string;
  page: (page: string) => string;
  previous: string;
  next: string;
  add: string;
  edit: string;
  name: string;
  warehouseCode: string;
  codePlaceholder: string;
  codeHint: string;
  address: string;
  addressPlaceholder: string;
  addressRequired: string;
  locationLink: string;
  latitude: string;
  longitude: string;
  coordinatesHint: string;
  coordinatesInvalid: string;
  deactivate: string;
  activate: string;
  deactivateReason: string;
  activateNote: string;
  confirmDeactivate: string;
  confirmActivate: string;
  versionChanged: string;
  branchMissing: string;
  branchInactive: string;
  blockers: Record<string, string>;
  blockerTitle: (label: string) => string;
  onHand: string;
  reserved: string;
  reference: string;
  referenceId: string;
  policyId: string;
  policyRevision: string;
}

const warehouseAr: WarehouseLocationsCopy = {
  title: "إدارة المستودعات",
  summary: (total, active) => `${total} مستودع · ${active} فعال في الصفحة الحالية`,
  refresh: "تحديث",
  newWarehouse: "مستودع جديد",
  warehousesView: "المستودعات",
  qualityDestinationsView: "وجهات الجودة",
  qualityDestinationsSummary: "إعداد وجهات الجودة لعمليات المخزون.",
  firstWarehouseTitle: "أنشئ أول مستودع",
  firstWarehouseDescription: "بعد إنشاء المستودع تصبح عمليات المستودع جاهزة للعمل.",
  createFirstWarehouse: "إنشاء أول مستودع",
  search: "بحث بالاسم أو الكود (حرفان على الأقل)",
  number: "الرقم",
  warehouse: "المستودع",
  code: "الكود",
  branch: "الفرع",
  status: "الحالة",
  updated: "آخر تحديث",
  actions: "إجراءات",
  unassigned: "غير مرتبط",
  active: "فعال",
  inactive: "متوقف",
  editAction: "تعديل",
  deactivateAction: "تعطيل",
  activateAction: "تفعيل",
  emptySearch: "لا توجد مستودعات مطابقة للبحث.",
  emptyCreate: "لم تُنشئ الشركة أي مستودع بعد. ابدأ بإنشاء مستودع من زر الإضافة.",
  emptyNoAccess: "لا توجد مستودعات متاحة لحسابك.",
  page: (page) => `الصفحة ${page}`,
  previous: "الصفحة السابقة",
  next: "الصفحة التالية",
  add: "إضافة مستودع",
  edit: "تعديل المستودع",
  name: "اسم المستودع",
  warehouseCode: "كود المستودع",
  codePlaceholder: "WH-001",
  codeHint: "يُقترح تلقائياً مثل WH-001، ويمكنك تعديله قبل الحفظ.",
  address: "العنوان",
  addressPlaceholder: "مثال: عمّان، ماركا الشمالية، اسم الشارع...",
  addressRequired: "العنوان مطلوب وبحد أقصى 2000 حرف.",
  locationLink: "رابط الموقع أو Google Maps (اختياري)",
  latitude: "خط العرض (اختياري)",
  longitude: "خط الطول (اختياري)",
  coordinatesHint: "يمكنك إدخال رابط الخرائط أو الإحداثيات؛ يكفي أحدهما.",
  coordinatesInvalid: "أدخل خط العرض وخط الطول معاً بقيم جغرافية صحيحة.",
  deactivate: "تعطيل المستودع",
  activate: "تفعيل المستودع",
  deactivateReason: "سبب التعطيل - إجباري",
  activateNote: "ملاحظة التفعيل - اختيارية",
  confirmDeactivate: "تأكيد التعطيل",
  confirmActivate: "تأكيد التفعيل",
  versionChanged: "تغيرت بيانات المستودع. تم تحديث النسخة الحالية مع الإبقاء على مدخلاتك. راجعها ثم نفّذ العملية مرة أخرى.",
  branchMissing: "الفرع المحدد لم يعد متاحاً. تم تحديث قائمة الفروع؛ اختر فرعاً متاحاً ثم أعد المحاولة.",
  branchInactive: "الفرع المحدد غير نشط ولا يمكن إنشاء ارتباط جديد به. تم تحديث قائمة الفروع.",
  blockers: {
    INVENTORY_BALANCE: "رصيد مخزني",
    OPEN_TRANSFER: "حوالة غير نهائية",
    INVENTORY_LOCK: "قفل مخزني نشط",
    OPEN_STOCKTAKE: "جلسة جرد غير نهائية",
    PUBLISHED_OPERATIONAL_POLICY: "سياسة تشغيل منشورة",
    OPEN_DISPATCH_ROUTE: "خط سير غير نهائي",
  },
  blockerTitle: (label) => `تعذر التعطيل: ${label}`,
  onHand: "المتاح",
  reserved: "المحجوز",
  reference: "المرجع",
  referenceId: "معرف المرجع",
  policyId: "معرف السياسة",
  policyRevision: "إصدار السياسة",
};

const warehouseEn: WarehouseLocationsCopy = {
  title: "Manage warehouses",
  summary: (total, active) => `${total} warehouses · ${active} active on this page`,
  refresh: "Refresh",
  newWarehouse: "New warehouse",
  warehousesView: "Warehouses",
  qualityDestinationsView: "Quality destinations",
  qualityDestinationsSummary: "Configure quality destinations for inventory operations.",
  firstWarehouseTitle: "Create your first warehouse",
  firstWarehouseDescription: "After creating the warehouse, warehouse operations are ready to use.",
  createFirstWarehouse: "Create first warehouse",
  search: "Search by name or code (2+ characters)",
  number: "No.",
  warehouse: "Warehouse",
  code: "Code",
  branch: "Branch",
  status: "Status",
  updated: "Last updated",
  actions: "Actions",
  unassigned: "Not assigned",
  active: "Active",
  inactive: "Inactive",
  editAction: "Edit",
  deactivateAction: "Deactivate",
  activateAction: "Activate",
  emptySearch: "No warehouses match the search.",
  emptyCreate: "No warehouse has been created yet. Use the add button to create the first warehouse.",
  emptyNoAccess: "No warehouses are available to your account.",
  page: (page) => `Page ${page}`,
  previous: "Previous page",
  next: "Next page",
  add: "Add warehouse",
  edit: "Edit warehouse",
  name: "Warehouse name",
  warehouseCode: "Warehouse code",
  codePlaceholder: "WH-001",
  codeHint: "Suggested automatically, for example WH-001. You can edit it before saving.",
  address: "Address",
  addressPlaceholder: "Example: Amman, Marka Al-Shamaliyah, street ...",
  addressRequired: "Address is required when creating a new warehouse and must be at most 2000 characters.",
  locationLink: "Location or Google Maps link - optional",
  latitude: "Latitude - optional",
  longitude: "Longitude - optional",
  coordinatesHint: "Enter a map link or coordinates; either one is enough.",
  coordinatesInvalid: "Enter latitude and longitude together using valid geographic values.",
  deactivate: "Deactivate warehouse",
  activate: "Activate warehouse",
  deactivateReason: "Deactivation reason - required",
  activateNote: "Activation note - optional",
  confirmDeactivate: "Confirm deactivation",
  confirmActivate: "Confirm activation",
  versionChanged: "Warehouse data changed. The current version was refreshed while keeping your input. Review it and submit a fresh mutation deliberately.",
  branchMissing: "The selected branch is no longer available. Branch options were refreshed; choose an available branch and retry.",
  branchInactive: "The selected branch is inactive and cannot be used for a new association. Branch options were refreshed.",
  blockers: {
    INVENTORY_BALANCE: "Inventory balance",
    OPEN_TRANSFER: "Open transfer",
    INVENTORY_LOCK: "Active inventory lock",
    OPEN_STOCKTAKE: "Open stocktake",
    PUBLISHED_OPERATIONAL_POLICY: "Published operational policy",
    OPEN_DISPATCH_ROUTE: "Open dispatch route",
  },
  blockerTitle: (label) => `Deactivation blocked: ${label}`,
  onHand: "On hand",
  reserved: "Reserved",
  reference: "Reference",
  referenceId: "Reference ID",
  policyId: "Policy ID",
  policyRevision: "Policy revision",
};

export interface BranchManagementCopy {
  manage: string;
  add: string;
  edit: string;
  deactivate: string;
  activate: string;
  search: string;
  refresh: string;
  newBranch: string;
  branch: string;
  code: string;
  status: string;
  created: string;
  actions: string;
  active: string;
  inactive: string;
  editAction: string;
  deactivateAction: string;
  activateAction: string;
  empty: string;
  page: (page: string) => string;
  previous: string;
  next: string;
  branchName: string;
  branchCode: string;
  save: string;
  saving: string;
  back: string;
  executing: string;
  reasonDeactivate: string;
  noteActivate: string;
  nonCascade: string;
  nameInvalid: string;
  codeInvalid: string;
  noChanges: string;
  loadFailed: string;
  saveFailed: string;
  stateFailed: string;
  reasonRequired: string;
  total: (count: string) => string;
}

const branchAr: BranchManagementCopy = {
  manage: "إدارة الفروع",
  add: "إضافة فرع",
  edit: "تعديل الفرع",
  deactivate: "تعطيل الفرع",
  activate: "تفعيل الفرع",
  search: "بحث بالاسم أو الكود",
  refresh: "تحديث",
  newBranch: "فرع جديد",
  branch: "الفرع",
  code: "الكود",
  status: "الحالة",
  created: "تاريخ الإنشاء",
  actions: "إجراءات",
  active: "فعال",
  inactive: "متوقف",
  editAction: "تعديل",
  deactivateAction: "تعطيل",
  activateAction: "تفعيل",
  empty: "لا توجد فروع مطابقة.",
  page: (page) => `الصفحة ${page}`,
  previous: "الصفحة السابقة",
  next: "الصفحة التالية",
  branchName: "اسم الفرع",
  branchCode: "كود الفرع",
  save: "حفظ",
  saving: "جارٍ الحفظ...",
  back: "رجوع",
  executing: "جارٍ التنفيذ...",
  reasonDeactivate: "سبب التعطيل - إجباري",
  noteActivate: "ملاحظة التفعيل - اختيارية",
  nonCascade: "تغيير حالة الفرع لا يغير حالة المستودعات المرتبطة ولا صلاحيات المواقع.",
  nameInvalid: "اسم الفرع مطلوب وبحد أقصى 150 حرفاً.",
  codeInvalid: "كود الفرع يجب أن يبدأ بحرف/رقم ويحتوي فقط A-Z و0-9 و _ و -.",
  noChanges: "لا توجد تغييرات لحفظها.",
  loadFailed: "تعذر جلب الفروع.",
  saveFailed: "تعذر حفظ الفرع.",
  stateFailed: "تعذر تغيير حالة الفرع.",
  reasonRequired: "سبب تعطيل الفرع مطلوب للتدقيق.",
  total: (count) => `${count} فرع`,
};

const branchEn: BranchManagementCopy = {
  manage: "Manage branches",
  add: "Add branch",
  edit: "Edit branch",
  deactivate: "Deactivate branch",
  activate: "Activate branch",
  search: "Search by name or code",
  refresh: "Refresh",
  newBranch: "New branch",
  branch: "Branch",
  code: "Code",
  status: "Status",
  created: "Created",
  actions: "Actions",
  active: "Active",
  inactive: "Inactive",
  editAction: "Edit",
  deactivateAction: "Deactivate",
  activateAction: "Activate",
  empty: "No matching branches.",
  page: (page) => `Page ${page}`,
  previous: "Previous page",
  next: "Next page",
  branchName: "Branch name",
  branchCode: "Branch code",
  save: "Save",
  saving: "Saving...",
  back: "Back",
  executing: "Processing...",
  reasonDeactivate: "Deactivation reason - required",
  noteActivate: "Activation note - optional",
  nonCascade: "Changing branch state does not change linked warehouse state or location permissions.",
  nameInvalid: "Branch name is required and must be at most 150 characters.",
  codeInvalid: "Branch code must start with a letter/number and contain only A-Z, 0-9, _ and -.",
  noChanges: "There are no changes to save.",
  loadFailed: "Could not load branches.",
  saveFailed: "Could not save the branch.",
  stateFailed: "Could not change branch state.",
  reasonRequired: "A deactivation reason is required for audit.",
  total: (count) => `${count} branches`,
};

const isArabicLanguage = (language: string | undefined) =>
  (language ?? "").toLowerCase().startsWith("ar");

export const warehouseLocationsCopy = (language: string | undefined) =>
  isArabicLanguage(language) ? warehouseAr : warehouseEn;

export const branchManagementCopy = (language: string | undefined) =>
  isArabicLanguage(language) ? branchAr : branchEn;

export const inventoryPresentationLocale = (language: string | undefined) =>
  resolveAppLocale(language);

export const formatInventoryInteger = (value: number, language: string | undefined) =>
  new Intl.NumberFormat(inventoryPresentationLocale(language), {
    maximumFractionDigits: 0,
  }).format(value);

export const formatInventoryDecimal = (value: number, language: string | undefined) =>
  new Intl.NumberFormat(inventoryPresentationLocale(language), {
    maximumFractionDigits: 20,
  }).format(value);

export const formatInventoryDate = (value: string, language: string | undefined) =>
  new Intl.DateTimeFormat(inventoryPresentationLocale(language), {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));

export const formatInventoryDateTime = (value: string, language: string | undefined) =>
  new Intl.DateTimeFormat(inventoryPresentationLocale(language), {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));

export interface WarehouseOperatorIssue {
  title: string;
  details: string[];
}

const contextNumber = (context: Record<string, unknown> | null, key: string) => {
  const value = context?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
};

const contextText = (context: Record<string, unknown> | null, key: string) => {
  const value = context?.[key];
  return typeof value === "string" && value.trim() ? value : null;
};

export const formatWarehouseDeactivationBlocker = (
  context: Record<string, unknown> | null,
  language: string | undefined,
): WarehouseOperatorIssue => {
  const copy = warehouseLocationsCopy(language);
  const type = contextText(context, "blocker_type") ?? "UNKNOWN";
  const label = copy.blockers[type] ?? type;
  const details: string[] = [];
  const onHand = contextNumber(context, "on_hand_quantity");
  const reserved = contextNumber(context, "reserved_quantity");
  const reference = contextText(context, "reference_number");
  const referenceId = contextNumber(context, "reference_id");
  const policyId = contextNumber(context, "policy_id");
  const policyRevision = contextNumber(context, "policy_revision");
  const quantity = (value: number) => formatInventoryDecimal(value, language);
  const integer = (value: number) => formatInventoryInteger(value, language);

  if (onHand !== null) details.push(`${copy.onHand}: ${quantity(onHand)}`);
  if (reserved !== null) details.push(`${copy.reserved}: ${quantity(reserved)}`);
  if (reference) details.push(`${copy.reference}: ${reference}`);
  if (referenceId !== null) details.push(`${copy.referenceId}: ${integer(referenceId)}`);
  if (policyId !== null) details.push(`${copy.policyId}: ${integer(policyId)}`);
  if (policyRevision !== null) details.push(`${copy.policyRevision}: ${integer(policyRevision)}`);

  return { title: copy.blockerTitle(label), details };
};