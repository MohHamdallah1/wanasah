export const productQualityWorkspace = {
  ar: {
    title: "معالجة الكميات المتأثرة",
    configureDestinations: "إعداد وجهات المعالجة",
    product: "المنتج: {{name}}",
    catalogContext: "المنتج موقوف على مستوى الشركة عن البيع والتحميل والتوريد الجديد. هذه المساحة تعالج الكميات الموجودة فقط ولا ترفع الإيقاف.",
    batches: "الكميات المعروضة حسب الدفعة: {{count}}",
    sources: "أماكن الكميات وقرارات المعالجة المتاحة",
    sourceScope: "كل مستودع أو مركبة مصدر مستقل. يظهر لك فقط ما تسمح به صلاحياتك، والقرارات والوجهات يحددها الخادم.",
    noVisibleStock: "لا توجد كميات ظاهرة ضمن صلاحياتك حالياً. يبقى إيقاف المنتج فعالاً حتى تكتمل جميع المتطلبات.",
    scopeMismatch: "البيانات لا تطابق المنتج المطلوب. لم يُنفذ أي إجراء.",
  },
  en: {
    title: "Handle affected quantities",
    configureDestinations: "Configure handling destinations",
    product: "Product: {{name}}",
    catalogContext: "The product is stopped company-wide for new sales, loads, and inbound. This workspace handles existing quantities only and does not lift the stop.",
    batches: "Quantities shown by batch: {{count}}",
    sources: "Stock locations and available handling decisions",
    sourceScope: "Each warehouse or vehicle is a separate source. You only see authorized locations; the server controls allowed decisions and destinations.",
    noVisibleStock: "No stock is currently visible within your permissions. The product stop remains active until all requirements are complete.",
    scopeMismatch: "The data does not match the requested product. No action was executed.",
  },
} as const;
