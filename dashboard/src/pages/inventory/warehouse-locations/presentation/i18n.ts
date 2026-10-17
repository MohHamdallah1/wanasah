export interface WarehousePresentationCopy {
  setupEyebrow: string;
  identityTitle: string;
  identityHint: string;
  branchTitle: string;
  branchHint: string;
  activeBranch: string;
  currentAssociation: string;
  assignmentRule: string;
  listLoadFailed: string;
  retry: string;
  deactivationCheck: string;
  deactivationNextStep: string;
  activationBranchNote: string;
  qualityPolicy: string;
  qualityPolicyHint: string;
}

const ar: WarehousePresentationCopy = {
  setupEyebrow: "إعداد المستودعات",
  identityTitle: "هوية المستودع",
  identityHint: "الاسم والرمز يعرّفان المستودع للمشغّلين والتقارير.",
  branchTitle: "ارتباط الفرع",
  branchHint: "الارتباط بفرع اختياري. اترك المستودع غير مرتبط إذا كانت الشركة لا تستخدم الفروع، أو اختر فرعًا نشطًا عند الحاجة.",
  activeBranch: "فرع نشط",
  currentAssociation: "الارتباط الحالي",
  assignmentRule: "التعيينات الجديدة متاحة للفروع النشطة فقط؛ الارتباط الحالي لا يتغير تلقائيًا.",
  listLoadFailed: "تعذر تحميل المستودعات. يمكنك إعادة المحاولة دون فقدان إعداداتك.",
  retry: "إعادة المحاولة",
  deactivationCheck: "قبل التعطيل، يتحقق النظام من الأرصدة والعمليات والسياسات المفتوحة المرتبطة بالمستودع.",
  deactivationNextStep: "راجع المرجع أو العملية الظاهرة أدناه ثم أعد المحاولة بعد إزالة المانع.",
  activationBranchNote: "تفعيل المستودع لا يفعّل الفرع المرتبط ولا يغيّر حالته.",
  qualityPolicy: "إعداد وسياسة",
  qualityPolicyHint: "هذه إعدادات وجهات المعالجة فقط وليست إجراءً يوميًا على المخزون.",
};

const en: WarehousePresentationCopy = {
  setupEyebrow: "Warehouse setup",
  identityTitle: "Warehouse identity",
  identityHint: "Name and code identify the warehouse to operators and reports.",
  branchTitle: "Branch assignment",
  branchHint: "Branch assignment is optional. Leave the warehouse unassigned when the company does not use branches, or choose an active branch when needed.",
  activeBranch: "Active branch",
  currentAssociation: "Current association",
  assignmentRule: "New assignments are limited to active branches; the existing association is never changed automatically.",
  listLoadFailed: "Warehouses could not be loaded. You can retry without losing setup changes.",
  retry: "Retry",
  deactivationCheck: "Before deactivation, the system checks balances, open operations, locks, and published policies tied to this warehouse.",
  deactivationNextStep: "Inspect the reference or process shown below, clear the blocker, then retry.",
  activationBranchNote: "Activating the warehouse does not activate or change the linked branch.",
  qualityPolicy: "Setup / policy",
  qualityPolicyHint: "These are destination settings only, not a daily stock action.",
};

export const warehousePresentationCopy = (language: string | undefined): WarehousePresentationCopy =>
  (language ?? "").toLowerCase().startsWith("ar") ? ar : en;
