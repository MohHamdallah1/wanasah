export const productQualityWorkspace = {
  ar: {
    title: "مشكلة جودة المنتج",
    product: "المنتج: {{name}}",
    catalogContext: "قرار إيقاف البيع على مستوى الشركة يخص صفحة المنتجات. يُعرض هنا للسياق فقط ولا تغيّره إجراءات المخزون.",
    batches: "دفعات المنتج المعروضة: {{count}}",
    sources: "مواقع الكميات والإجراءات المتاحة",
    sourceScope: "كل مستودع أو مركبة مصدر مستقل. الكميات والحجوزات والإجراءات المعروضة تخص المواقع المسموح لك بها فقط.",
    noVisibleStock: "لا توجد كميات للعرض ضمن صلاحياتك حالياً. هذا لا يغيّر قرار إيقاف بيع المنتج.",
    scopeMismatch: "البيانات لا تطابق المنتج المطلوب. لم يُنفذ أي إجراء.",
  },
  en: {
    title: "Product quality issue",
    product: "Product: {{name}}",
    catalogContext: "The company-wide sales hold belongs to Products. It is shown here as context and is not changed by inventory actions.",
    batches: "Product batches shown: {{count}}",
    sources: "Stock sources and available actions",
    sourceScope: "Each warehouse or vehicle is a separate source. Quantities, reservations and actions are shown only for locations you can read.",
    noVisibleStock: "No stock is currently visible within your permissions. This does not change the product sales hold.",
    scopeMismatch: "The data does not match the requested product. No action was executed.",
  },
} as const;
