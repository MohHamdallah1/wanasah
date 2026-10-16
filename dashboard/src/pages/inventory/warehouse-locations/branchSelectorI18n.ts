export interface BranchSelectorCopy {
  branch: string;
  none: string;
  current: string;
  currentNumber: string;
  search: string;
  loadFailed: string;
  loading: string;
  more: string;
}

const ar: BranchSelectorCopy = {
  branch: "الفرع",
  none: "غير مرتبط بفرع",
  current: "الارتباط الحالي",
  currentNumber: "الفرع الحالي",
  search: "ابحث عن فرع بحرفين على الأقل",
  loadFailed: "تعذر جلب الفروع.",
  loading: "جارٍ تحميل الفروع...",
  more: "توجد نتائج إضافية؛ استخدم البحث للوصول إلى الفرع المطلوب.",
};

const en: BranchSelectorCopy = {
  branch: "Branch",
  none: "No branch",
  current: "current association",
  currentNumber: "Current branch",
  search: "Search branches using at least two characters",
  loadFailed: "Could not load branches.",
  loading: "Loading branches...",
  more: "More results exist; use search to find the required branch.",
};

export const branchSelectorCopy = (language: string | undefined): BranchSelectorCopy =>
  (language ?? "").toLowerCase().startsWith("ar") ? ar : en;
