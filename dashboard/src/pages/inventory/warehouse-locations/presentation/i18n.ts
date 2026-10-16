export interface WarehousePresentationCopy {
  setupEyebrow: string;
  identityTitle: string;
  identityHint: string;
  branchTitle: string;
  branchHint: string;
  lifecycleTitle: string;
  lifecycleHint: string;
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
  branchHint: "اختر فرعًا نشطًا للتعيين الجديد. الارتباط الحالي يبقى ظاهرًا حتى لو لم يعد متاحًا للتعيين.",
  lifecycleTitle: "حالة التشغيل",
  lifecycleHint: "تفعيل أو تعطيل المستودع إجراء مستقل عن دورة حياة الفرع.",
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
  branchHint: "Choose an active branch for a new assignment. The current association remains visible even when it is no longer assignable.",
  lifecycleTitle: "Operational state",
  lifecycleHint: "Warehouse activation and deactivation are independent from the branch lifecycle.",
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
