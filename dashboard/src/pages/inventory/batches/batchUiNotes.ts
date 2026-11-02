type Key =
  | "familySearch" | "productSearch" | "searchMin" | "loading"
  | "loadMore" | "retry" | "loadFailed" | "summaryScope" | "summaryDisposition";

const messages: Record<"ar" | "en", Record<Key, string>> = {
  ar: {
    familySearch: "ابحث عن عائلة لها تشغيلات في المستودع",
    productSearch: "ابحث عن منتج له تشغيلات في المستودع",
    searchMin: "اكتب حرفين على الأقل للبحث.",
    loading: "جاري تحميل الخيارات...",
    loadMore: "عرض خيارات أخرى",
    retry: "إعادة محاولة الخيارات",
    loadFailed: "تعذر تحميل الخيارات. أعد المحاولة.",
    summaryScope: "هذا الملخص يتبع بحث التشغيلات والعائلة والمنتج في المستودع؛ فلاتر الصلاحية وقابلية البيع وحالة التشغيلة والتنبيهات لا تغيّر أرقامه.",
    summaryDisposition: "الحجر والحظر والسحب هنا أعداد تشغيلات حسب حالتها، وليست كميات مخزون.",
  },
  en: {
    familySearch: "Search families with batches in this warehouse",
    productSearch: "Search products with batches in this warehouse",
    searchMin: "Enter at least two characters to search.",
    loading: "Loading options...",
    loadMore: "Show more options",
    retry: "Retry options",
    loadFailed: "Could not load options. Try again.",
    summaryScope: "This summary follows the warehouse batch search, family and product. Expiry, sellability, disposition and attention filters do not change its counts.",
    summaryDisposition: "Quarantined, blocked and recalled are batch disposition counts, not stock quantities.",
  },
};
export const batchUiNote = (language: string, key: Key) =>
  messages[language.toLowerCase().startsWith("ar") ? "ar" : "en"][key];
