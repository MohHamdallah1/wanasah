export interface WarehousePresentationCopy {
  setupEyebrow: string;
  identityTitle: string;
  identityHint: string;
  locationTitle: string;
  locationHint: string;
  listLoadFailed: string;
  retry: string;
  deactivationCheck: string;
  deactivationNextStep: string;
  activationCheck: string;
  qualityPolicy: string;
  qualityPolicyHint: string;
}

const ar: WarehousePresentationCopy = {
  setupEyebrow: "إعداد المستودعات",
  identityTitle: "هوية المستودع",
  identityHint: "أدخل اسم المستودع والكود.",
  locationTitle: "الموقع الفعلي",
  locationHint: "العنوان مطلوب، ورابط الخرائط والإحداثيات اختيارية.",
  listLoadFailed: "تعذر تحميل المستودعات. يمكنك إعادة المحاولة دون فقدان إعداداتك.",
  retry: "إعادة المحاولة",
  deactivationCheck: "قبل التعطيل، يتحقق النظام من الأرصدة والعمليات والسياسات المفتوحة المرتبطة بالمستودع.",
  deactivationNextStep: "راجع المرجع أو العملية الظاهرة أدناه ثم أعد المحاولة بعد إزالة المانع.",
  activationCheck: "عند التفعيل، يصبح المستودع متاحاً للعمليات التي تسمح بها الصلاحيات والسياسات الحالية.",
  qualityPolicy: "إعداد وسياسة",
  qualityPolicyHint: "هذه إعدادات وجهات المعالجة فقط وليست إجراءً يوميًا على المخزون.",
};

const en: WarehousePresentationCopy = {
  setupEyebrow: "Warehouse setup",
  identityTitle: "Warehouse identity",
  identityHint: "Enter the warehouse name and code.",
  locationTitle: "Physical location",
  locationHint: "Address is required. Map link and coordinates are optional.",
  listLoadFailed: "Warehouses could not be loaded. You can retry without losing setup changes.",
  retry: "Retry",
  deactivationCheck: "Before deactivation, the system checks balances, open operations, locks, and published policies tied to this warehouse.",
  deactivationNextStep: "Inspect the reference or process shown below, clear the blocker, then retry.",
  activationCheck: "Once activated, the warehouse becomes available to workflows allowed by the current permissions and policies.",
  qualityPolicy: "Setup / policy",
  qualityPolicyHint: "These are destination settings only, not a daily stock action.",
};

export const warehousePresentationCopy = (language: string | undefined): WarehousePresentationCopy =>
  (language ?? "").toLowerCase().startsWith("ar") ? ar : en;
