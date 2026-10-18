export interface WarehousePresentationCopy {
  setupEyebrow: string;
  identityTitle: string;
  locationTitle: string;
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
  locationTitle: "الموقع الفعلي",
  listLoadFailed: "تعذر تحميل المستودعات. يمكنك إعادة المحاولة دون فقدان إعداداتك.",
  retry: "إعادة المحاولة",
  deactivationCheck: "قبل التعطيل، يتحقق النظام من الأرصدة والعمليات والسياسات المفتوحة المرتبطة بالمستودع.",
  deactivationNextStep: "راجع المرجع أو العملية الظاهرة أدناه ثم أعد المحاولة بعد إزالة المانع.",
  activationCheck: "عند التفعيل، يصبح المستودع متاحاً للعمليات التي تسمح بها الصلاحيات والسياسات الحالية.",
  qualityPolicy: "إعداد وسياسة",
  qualityPolicyHint: "الافتراضي في V1 هو إبقاء المخزون في موقعه الحالي وتغيير حالة المخزون فقط.",
};

const en: WarehousePresentationCopy = {
  setupEyebrow: "Warehouse setup",
  identityTitle: "Warehouse identity",
  locationTitle: "Physical location",
  listLoadFailed: "Warehouses could not be loaded. You can retry without losing setup changes.",
  retry: "Retry",
  deactivationCheck: "Before deactivation, the system checks balances, open operations, locks, and published policies tied to this warehouse.",
  deactivationNextStep: "Inspect the reference or process shown below, clear the blocker, then retry.",
  activationCheck: "Once activated, the warehouse becomes available to workflows allowed by the current permissions and policies.",
  qualityPolicy: "Setup / policy",
  qualityPolicyHint: "The V1 default keeps stock in its current location and changes stock status only.",
};

export const warehousePresentationCopy = (language: string | undefined): WarehousePresentationCopy =>
  (language ?? "").toLowerCase().startsWith("ar") ? ar : en;
