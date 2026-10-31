export interface WarehousePresentationCopy {
  setupEyebrow: string;
  warehouseIllustrationCode: string;
  setupStart: string;
  locationLinkPlaceholder: string;
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
  warehouseIllustrationCode: "مستودع / 001",
  setupStart: "البداية",
  locationLinkPlaceholder: "ألصق رابط الموقع أو خرائط Google",
  identityTitle: "هوية المستودع",
  locationTitle: "الموقع الفعلي",
  listLoadFailed: "تعذر تحميل المستودعات. يمكنك إعادة المحاولة دون فقدان إعداداتك.",
  retry: "إعادة المحاولة",
  deactivationCheck: "قبل التعطيل، يتحقق النظام من الأرصدة والعمليات والسياسات المفتوحة المرتبطة بالمستودع.",
  deactivationNextStep: "راجع المرجع أو العملية الظاهرة أدناه ثم أعد المحاولة بعد إزالة المانع.",
  activationCheck: "عند التفعيل، يصبح المستودع متاحاً للعمليات التي تسمح بها الصلاحيات والسياسات الحالية.",
  qualityPolicy: "معالجة الجودة",
  qualityPolicyHint: "يبقى المخزون في موقعه الحالي وتتغير حالة المخزون فقط.",
};

const en: WarehousePresentationCopy = {
  setupEyebrow: "Warehouse setup",
  warehouseIllustrationCode: "WH / 001",
  setupStart: "START",
  locationLinkPlaceholder: "Paste a location or Google Maps link",
  identityTitle: "Warehouse identity",
  locationTitle: "Physical location",
  listLoadFailed: "Warehouses could not be loaded. You can retry without losing setup changes.",
  retry: "Retry",
  deactivationCheck: "Before deactivation, the system checks balances, open operations, locks, and published policies tied to this warehouse.",
  deactivationNextStep: "Inspect the reference or process shown below, clear the blocker, then retry.",
  activationCheck: "Once activated, the warehouse becomes available to workflows allowed by the current permissions and policies.",
  qualityPolicy: "Quality handling",
  qualityPolicyHint: "Stock stays in its current location and only its stock status changes.",
};

export const warehousePresentationCopy = (language: string | undefined): WarehousePresentationCopy =>
  (language ?? "").toLowerCase().startsWith("ar") ? ar : en;
