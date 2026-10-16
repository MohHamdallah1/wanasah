export interface BranchSelectorCopy {
  branch: string;
  none: string;
  current: string;
  currentNumber: string;
  active: string;
  inactiveCurrent: string;
  assignmentRule: string;
  search: string;
  loadFailed: string;
  loading: string;
  more: string;
  retry: string;
}

const ar: BranchSelectorCopy = {
  branch: "الفرع",
  none: "غير مرتبط بفرع",
  current: "الارتباط الحالي",
  currentNumber: "الفرع الحالي",
  active: "نشط",
  inactiveCurrent: "غير نشط — الارتباط الحالي محفوظ",
  assignmentRule: "يمكن تعيين الفروع النشطة فقط. الارتباط الحالي لا يتغير تلقائيًا.",
  search: "ابحث عن فرع بحرفين على الأقل",
  loadFailed: "تعذر جلب الفروع.",
  loading: "جارٍ تحميل الفروع...",
  more: "توجد نتائج إضافية؛ استخدم البحث للوصول إلى الفرع المطلوب.",
  retry: "إعادة المحاولة",
};

const en: BranchSelectorCopy = {
  branch: "Branch",
  none: "No branch",
  current: "current association",
  currentNumber: "Current branch",
  active: "Active",
  inactiveCurrent: "Inactive — current association preserved",
  assignmentRule: "Only active branches can be newly assigned. The current association is never changed automatically.",
  search: "Search branches using at least two characters",
  loadFailed: "Could not load branches.",
  loading: "Loading branches...",
  more: "More results exist; use search to find the required branch.",
  retry: "Retry",
};

export const branchSelectorCopy = (language: string | undefined): BranchSelectorCopy =>
  (language ?? "").toLowerCase().startsWith("ar") ? ar : en;
