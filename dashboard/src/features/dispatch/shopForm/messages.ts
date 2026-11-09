/** The Shop form owns its AR/EN copy; backend codes are never shown verbatim. */
const copy = {
  ar: {
    titleCreate: "إضافة محل جديد", titleEdit: "تعديل بيانات المحل",
    cancel: "إلغاء", save: "حفظ البيانات", saving: "جاري الحفظ...",
    name: "اسم المحل", owner: "اسم المالك", phone: "رقم الهاتف",
    zone: "المنطقة", map: "رابط الخريطة",
    maxDebt: "سقف المديونية", openingDebt: "الرصيد الافتتاحي", currentDebt: "الرصيد الحالي",
    financeReadOnly: "هذه القيم للعرض فقط. تعديل الرصيد أو سقف المديونية يتطلب إجراءً مالياً مخولاً ومنفصلاً.",
    financeUnavailable: "البيانات المالية غير متاحة لصلاحيات الحساب الحالي.",
    financeLoading: "جاري جلب الأرصدة المصرح بها...",
    financeRefreshFailed: "تعذر جلب الأرصدة الحالية. لم يتم عرض قيم قديمة.",
    invalidMoney: "أدخل قيمة صحيحة وغير سالبة حتى ثلاث منازل عشرية (بحد أقصى 999999999.999).",
    invalidMetadata: "أدخل اسم المحل والمنطقة وراجع طول البيانات.",
    phoneCannotClear: "لا يمكن إفراغ رقم الهاتف من هذه الشاشة حالياً؛ أبقِ الرقم أو استبدله برقم صحيح.",
    added: "تم إنشاء المحل والتحقق من بياناته.",
    edited: "تم تحديث بيانات المحل والتحقق منها.",
    financialStale: "تغير رصيد المحل أو سقفه. لم يُجرَ تعديل مالي. راجع البيانات المحدثة، وتعديلاتك على اسم المحل محفوظة.",
    financialAuthority: "لا يمكن تعديل الرصيد أو سقف الدين من نموذج المحل؛ يتطلب ذلك إجراءً مالياً مخولاً ومستقلاً.",
    conflict: "تعارضت بيانات المحل مع تعديل آخر. لم تُفقد تعديلاتك؛ راجع البيانات الحالية قبل إعادة الحفظ.",
    denied: "ليس للحساب صلاحية تنفيذ هذا التعديل. احتفظنا بالبيانات المدخلة.",
    unknown: "نتيجة الحفظ غير مؤكدة. لن نعيد إرسال الطلب قبل التحقق من الخادم.",
    readback: "تم إرسال الطلب، ولكن لم نتمكن من التحقق من بيانات الخادم. لا نعرض نجاحاً غير مؤكد.",
    refresh: "التحقق من نتيجة الحفظ",
    createDuplicate: "تأكد من بيانات المحل المتشابه قبل الإضافة.",
  },
  en: {
    titleCreate: "Add shop", titleEdit: "Edit shop details",
    cancel: "Cancel", save: "Save details", saving: "Saving...",
    name: "Shop name", owner: "Owner", phone: "Phone",
    zone: "Zone", map: "Map link",
    maxDebt: "Credit limit", openingDebt: "Opening receivable", currentDebt: "Current receivable",
    financeReadOnly: "Read-only figures. Changing a receivable or credit limit requires a separate authorized finance process.",
    financeUnavailable: "Financial figures are not available to this account.",
    financeLoading: "Loading authorized financial balances...",
    financeRefreshFailed: "Current financial balances could not be loaded. Old figures are not shown.",
    invalidMoney: "Enter a valid nonnegative amount with up to 3 decimals (maximum 999999999.999).",
    invalidMetadata: "Enter a shop name and zone and check the field lengths.",
    phoneCannotClear: "This screen cannot clear an existing phone number. Keep or replace it with a valid number.",
    added: "Shop created and verified.",
    edited: "Shop details updated and verified.",
    financialStale: "The shop balance or credit limit has changed. No financial value was changed. Your shop details remain in the form.",
    financialAuthority: "The shop form cannot change balances or credit limits. A separate authorized finance process is required.",
    conflict: "Another change conflicts with these shop details. Your edits are retained; review the current data before saving again.",
    denied: "This account is not authorized to make that change. Your edits are retained.",
    unknown: "Save result is uncertain. The request will not be sent again before server verification.",
    readback: "The request was sent, but its server result could not be verified. No success is claimed.",
    refresh: "Verify saved result",
    createDuplicate: "Review the matching shop before creating another.",
  },
} as const;
export type ShopFormMessageKey = keyof typeof copy.en;
export const shopFormText = (language: string, key: ShopFormMessageKey): string =>
  copy[language.toLowerCase().startsWith("ar") ? "ar" : "en"][key];

export const withSafeReference = (message: string, reference: string | undefined, language: string): string =>
  reference && /^[A-Za-z0-9._:-]{1,100}$/.test(reference)
    ? `${message} ${language.toLowerCase().startsWith("ar") ? "مرجع الطلب" : "Request reference"}: ${reference}.`
    : message;
