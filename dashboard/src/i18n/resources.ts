export const supportedLanguages = [
  "ar",
  "en",
] as const;

export type SupportedLanguage =
  (typeof supportedLanguages)[number];

export const resources = {
  ar: {
    translation: {
      common: {
        save: "حفظ",
        cancel: "إلغاء",
        close: "إغلاق",
        refresh: "تحديث",
        edit: "تعديل",
        retry: "إعادة المحاولة",
        optional: "اختياري",
        loading: "جاري التحميل...",
        comingSoon: "قريباً",
      },
      nav: {
        home: "الصفحة الرئيسية",
        dispatch: "التوزيع والمناطق",
        inventory: "المخزون والمستودع",
        products: "المنتجات",
        commercialRules: "العروض والضرائب",
        salesReturns: "مرتجعات البيع",
        reports: "الأرشيف والتقارير",
        settings: "الإعدادات",
        accountSettings: "إعدادات الحساب",
        logout: "تسجيل خروج",
        mainNavigation: "التنقل الرئيسي",
        systemAdmin: "مدير النظام",
        inventoryUser: "مستخدم مخزون",
        companyPanel: "لوحة الشركة",
        operationsCenter: "مركز إدارة العمليات",
        locationUnknown: "الموقع غير محدد",
        administrator: "المدير",
        pageInDevelopment: "صفحة «{{page}}» قيد التطوير",
        openNavigation: "فتح قائمة التنقل",
      },
      access: {
        loading: "جاري تحميل صلاحيات الحساب...",
        failed: "تعذر التحقق من صلاحيات الحساب",
      },
      network: {
        offlineBanner:
          "لا يوجد اتصال بالإنترنت. لن ننفذ أي أمر في الخلفية، ومدخلاتك المحفوظة لن تضيع.",
        offline:
          "لا يوجد اتصال بالإنترنت. أعد المحاولة بعد عودة الشبكة.",
        timeout:
          "لم يصل رد من السيرفر ضمن المهلة. أعد المحاولة؛ النظام سيستخدم نفس رقم العملية لمنع التكرار.",
        invalidResponse:
          "وصلت استجابة غير صالحة من السيرفر.",
        sessionExpired: "انتهت الجلسة.",
        refreshFailed: "تعذر تجديد الجلسة.",
        serverError: "تعذر إكمال الطلب.",
      },
      products: {
        title: "المنتجات",
        subtitle:
          "أضف المنتج وسعره في عملية واحدة، والنظام يتكفل بالتفاصيل الداخلية.",
        searchPlaceholder:
          "ابحث باسم المنتج أو العائلة...",
        addProduct: "إضافة منتج",
        importFile: "استيراد ملف",
        families: "العائلات",
        advancedPricing: "التسعير المتقدم",
        advancedPricingHint:
          "سيتم تفعيله لاحقاً",
        emptyTitle: "لا توجد منتجات بعد",
        emptyDescription:
          "أضف منتجاً أو استورد ملفاً.",
        columns: {
          product: "المنتج",
          package: "العبوة",
          unitsPerPackage: "الوحدات / العبوة",
          packagePrice: "سعر العبوة",
          unitPrice: "سعر الحبة",
          action: "الإجراء",
        },
        editPrice: "تعديل السعر",
        addTitle: "إضافة منتج",
        productName: "اسم المنتج",
        productNamePlaceholder:
          "مثال: شيبس لولو جبنة 20غ",
        family: "العائلة",
        familyPlaceholder:
          "اختر عائلة أو اكتب اسماً جديداً",
        noOuterPackage: "يباع بالحبة فقط",
        hasOuterPackage: "له عبوة أكبر",
        packageType: "نوع العبوة",
        unitsPerPackage:
          "عدد الحبات داخل العبوة",
        packagePrice: "سعر العبوة",
        unitPrice: "سعر الحبة",
        packagePricePlaceholder:
          "اتركه فارغاً إذا أدخلت سعر الحبة",
        unitPricePlaceholder:
          "اتركه فارغاً ليحسبه النظام",
        derivedPrice:
          "النظام سيحسب السعر الناقص تلقائياً.",
        independentPrices:
          "سيتم اعتماد السعرين كما أدخلتهما حتى لو لم يتطابقا حسابياً.",
        barcodeSection: "الباركود — اختياري",
        unitBarcode: "باركود الحبة",
        packageBarcode: "باركود العبوة",
        copyBarcode:
          "نفس باركود الحبة",
        copiedBarcode: "تم نسخ الباركود",
        saveProduct: "حفظ المنتج",
        savePrice: "حفظ السعر",
        priceHelp:
          "أدخل سعراً واحداً ليحسب النظام الآخر، أو أدخل السعرين ليتم اعتمادهما كما هما.",
        draftRestored:
          "استعدنا المنتج الذي كنت تعمل عليه.",
        offlineSaveHint:
          "مدخلات المنتج محفوظة على هذا الجهاز حتى ينجح الحفظ أو تلغي العملية.",
        familiesTitle: "إدارة العائلات",
        familiesDescription:
          "العائلة تجمع أحجام أو نكهات أو نسخ المنتج تحت اسم واحد، بينما يبقى كل صنف مستقلاً بالسعر والمخزون والباركود.",
        newFamilyPlaceholder: "اسم العائلة",
        addFamily: "إضافة العائلة",
        variantCount: "{{count}} صنف",
        noFamilies: "لا توجد عائلات بعد.",
        importTitle: "استيراد المنتجات",
        importIntro:
          "يدعم CSV وExcel. ترتيب الأعمدة لا يهم، وإذا لم نتعرف على عمود لن نخمن؛ سنطلب منك ربطه قبل الاستيراد.",
        downloadTemplate: "تحميل النموذج",
        dropFile:
          "اسحب الملف هنا أو اضغط للاختيار",
        importLimit:
          "حتى 50,000 صف — المعالجة تتم في الخلفية",
        uploadAndStart: "رفع وبدء الاستيراد",
        queued:
          "تم إدراج العملية في الطابور...",
        mappingIntro:
          "لم نخمن الأعمدة غير الواضحة. اربط المطلوب فقط ثم تابع.",
        unmapped: "غير مربوط",
        continueImport: "متابعة الاستيراد",
        preparingImport:
          "جاري تجهيز وفحص الملف",
        importingProducts:
          "جاري إضافة المنتجات",
        backgroundHint:
          "يمكنك إغلاق النافذة؛ العملية مستمرة في الخلفية.",
        validationFailed:
          "لم يتم استيراد أي منتج. يوجد {{count}} صف بحاجة تصحيح.",
        downloadErrors: "تحميل تقرير الأخطاء",
        errorReportRow: "رقم الصف",
        errorReportCode: "رمز الخطأ",
        errorReportMessage: "الخطأ",
        newImport: "رفع ملف مصحح / استيراد جديد",
        rowNumber: "الصف {{row}}",
        importFailed:
          "فشلت العملية بعد محاولات الإعادة. لم يترك النظام منتجاً نصف مكتمل.",
        importCompleted:
          "تم استيراد {{count}} منتج بنجاح",
        importAccepted:
          "تم استلام الملف. المعالجة تعمل في الخلفية.",
        importResumed:
          "تم استعادة عملية الاستيراد الجارية.",
        mappingAccepted:
          "تم اعتماد ربط الأعمدة.",
        retryQueued:
          "تمت إعادة العملية إلى الطابور.",
        created:
          "تم حفظ المنتج والسعر.",
        priceUpdated:
          "تم تحديث الأسعار.",
        familyCreated:
          "تم إنشاء العائلة.",
        familyUpdated:
          "تم تعديل العائلة.",
        fields: {
          name: "اسم المنتج",
          family: "العائلة",
          packageUom: "نوع العبوة",
          unitsPerPackage:
            "عدد الحبات داخل العبوة",
          packagePrice: "سعر العبوة",
          unitPrice: "سعر الحبة",
          unitBarcode: "باركود الحبة",
          packageBarcode: "باركود العبوة",
        },
        errors: {
          nameRequired: "اسم المنتج مطلوب.",
          packageUnitsInvalid:
            "عدد الحبات داخل العبوة يجب أن يكون رقماً صحيحاً أكبر من 1.",
          priceRequired:
            "أدخل سعر العبوة أو سعر الحبة على الأقل.",
          unitPriceRequired:
            "أدخل سعر الحبة.",
          fileRequired:
            "اختر ملفاً أولاً.",
          unsupportedFile:
            "الملفات المدعومة CSV وXLSX.",
          createFailed:
            "تعذر حفظ المنتج.",
          priceFailed:
            "تعذر تحديث الأسعار.",
          familyFailed:
            "تعذر حفظ العائلة.",
          importFailed:
            "تعذر رفع ملف الاستيراد.",
          mappingFailed:
            "تعذر اعتماد ربط الأعمدة.",
          retryFailed:
            "تعذر إعادة عملية الاستيراد.",
        },
      },
      inventoryInbound: {
        title: "توريد بضاعة",
        product: "المنتج",
        search: "بحث...",
        batchAndDates: "الدفعة والتواريخ",
        quantityAndUnit: "الكمية ووحدة الشراء",
        purchaseCost: "تكلفة الشراء للوحدة",
        clearDraft: "تصفير المسودة",
        noProducts: "لا توجد أصناف فعالة",
        batchNumber: "رقم الدفعة",
        productionDate: "تاريخ الإنتاج",
        expiryDate: "تاريخ الصلاحية",
        factorToBase: "= {{factor}} {{unit}}",
        unitCostPlaceholder: "التكلفة الفعلية",
        addBatch: "إضافة دفعة أخرى",
        removeBatch: "حذف الدفعة",
        previousPage: "الصفحة السابقة",
        nextPage: "الصفحة التالية",
        reference: "رقم الفاتورة / المرجع",
        notes: "ملاحظات",
        costMethod: "احتساب التكلفة",
        methods: {
          MOVING_AVERAGE: "متوسط متحرك",
          FIFO: "الوارد أولاً يخرج أولاً",
        },
        costMethodLocked: "مثبتة بعد أول توريد",
        submitting: "جاري التوثيق...",
        submit: "توثيق الاستلام",
        clearTitle: "تأكيد تصفير المسودة",
        clearConfirm: "تصفير",
        clearBody: "سيتم مسح مسودة التوريد المحلية الحالية فقط.",
        defaultBatchTitle: "بيانات دفعة افتراضية للسند",
        defaultBatchHint:
          "أدخلها مرة واحدة لتُطبّق على كل الأصناف التي لم تضع لها بيانات دفعة خاصة. يمكنك تجاوزها لأي صنف عند الحاجة.",
        defaultBatchPlaceholder: "مثال: LOT-2026-09",
        overrideBatchPlaceholder: "الافتراضي: {{batch}}",
        rowBatchOverrideHint:
          "اترك الحقل فارغاً لاستخدام دفعة السند الافتراضية، أو أدخل دفعة مختلفة لهذا الصنف فقط.",
        addReceiptLine: "إضافة كمية/وحدة أخرى لنفس المنتج",
        policySaved: "تم حفظ طريقة احتساب التكلفة.",
        received: "تم توثيق التوريد والتكلفة بنجاح.",
        errors: {
          catalogLoad: "تعذر جلب المنتجات.",
          optionsLoad: "تعذر جلب وحدات الشراء.",
          policyLoad: "تعذر جلب إعداد التكلفة.",
          policySave: "تعذر حفظ طريقة احتساب التكلفة.",
          auditLocked: "المستودع مقفل بجرد شامل ولا يمكن التوريد حالياً.",
          quantityRequired: "أضف كمية لصنف واحد على الأقل.",
          referenceRequired: "رقم الفاتورة أو المرجع إجباري.",
          optionsNotReady: "وحدات الشراء لم تجهز بعد.",
          submit: "فشل توثيق التوريد.",
        },
      },
      inventoryCommon: {
        unit: "وحدة",
      },
      inventoryLive: {
        inWarehouse: "في المستودع",
        averageCost: "متوسط التكلفة",
        averageCostHint:
          "متوسط تكلفة الشركة الحالي لهذا المنتج، معروض بوحدة العرض التجارية عند توفر تحويل واحد واضح.",
        blocked: "محجوب عن الصرف",
      },
      inventoryLedger: {
        batch: "الدفعة",
        balanceBefore: "الرصيد قبل",
        quantity: "الكمية",
        balanceAfter: "الرصيد بعد",
        purchaseCost: "تكلفة الشراء",
        averageAfter: "متوسط التكلفة بعد الحركة",
        supervisor: "المشرف",
        totalCost: "إجمالي التكلفة",
      },
      uom: {
        CARTON: "كرتونة",
        CASE: "صندوق",
        PACK: "باكيت",
        BAG: "كيس",
        SACK: "شوال",
        TRAY: "صينية",
        CRATE: "قفص",
        BUNDLE: "حزمة",
        PALLET: "طبلية",
        NONE: "بدون عبوة",
        EACH: "حبة",
      },
      errors: {
        serverReasonWithCodeAndReference:
          "{{message}} — رمز الخطأ: {{code}} — رقم التتبع: {{requestId}}",
        serverReasonWithCode:
          "{{message}} — رمز الخطأ: {{code}}",
        serverReasonWithReference:
          "{{message}} — رقم التتبع: {{requestId}}",
        fallbackWithCodeAndReference:
          "{{fallback}} — رمز الخطأ: {{code}} — رقم التتبع: {{requestId}}",
        fallbackWithCode:
          "{{fallback}} — رمز الخطأ: {{code}}",
        fallbackWithReference:
          "{{fallback}} — رقم التتبع: {{requestId}}",
        unexpected:
          "حدث خطأ غير متوقع في الخادم.",
        unexpectedWithReference:
          "حدث خطأ غير متوقع في الخادم. رقم التتبع: {{requestId}}",
        codes: {
          OPERATIONS_RESPONSE_INVALID: "استجابة غرفة العمليات غير صالحة أو غير مكتملة.",
          INBOUND_DUPLICATE_BATCH_UOM_LINE: "لا تكرر نفس المنتج ونفس الدفعة ونفس وحدة الشراء في أكثر من سطر. استخدم سطراً إضافياً فقط لوحدة شراء مختلفة.",
          VALIDATION_ERROR: "بيانات الطلب غير صالحة. راجع الحقول المدخلة.",
          RATE_LIMITED: "تم تجاوز الحد المسموح من الطلبات. حاول مرة أخرى لاحقاً.",
          REQUEST_TOO_LARGE: "حجم الطلب يتجاوز الحد المسموح.",
          INTERNAL_SERVER_ERROR: "حدث خطأ داخلي في الخادم.",
          PRODUCT_LOCATION_REQUIRED: "هذا المنتج غير مربوط بالمستودع المحدد.",
          PRODUCT_LOCATION_INBOUND_DISABLED: "التوريد لهذا المنتج معطّل في المستودع المحدد.",
          INBOUND_UNIT_COST_INVALID: "أدخل تكلفة شراء صحيحة حتى 6 منازل عشرية.",
          INBOUND_VARIANT_UNAVAILABLE: "أحد المنتجات لم يعد فعالاً أو لا يتبع شركتك.",
          INBOUND_UOM_REQUIRED: "اختر وحدة الشراء.",
          INBOUND_UOM_UNSUPPORTED: "وحدة الشراء لا تملك تحويلاً دقيقاً إلى وحدة أساس المنتج.",
          INBOUND_UOM_CONVERSION_INVALID: "تحويل وحدة الشراء غير صالح.",
          INBOUND_UOM_CONVERSION_CONFLICT: "يوجد تعارض في تحويلات وحدة الشراء لهذا المنتج.",
          INBOUND_UOM_REFERENCE_MISSING: "مرجع وحدة قياس مطلوب مفقود.",
          INBOUND_QUANTITY_CONVERSION_INVALID: "الكمية لا يمكن تحويلها بدقة إلى وحدة أساس المنتج.",
          INBOUND_BATCH_INVALID: "أدخل رقم دفعة صالحاً.",
          INBOUND_BATCH_DATES_INVALID: "تواريخ الدفعة غير صالحة.",
          INBOUND_EXPIRY_REQUIRED: "تاريخ الصلاحية مطلوب لهذا المنتج.",
          INBOUND_EXPIRY_NOT_ALLOWED: "هذا المنتج لا يستخدم تتبع الصلاحية.",
          INBOUND_DUPLICATE_BATCH_LINE: "لا تكرر نفس دفعة المنتج داخل فاتورة التوريد الواحدة.",
          INBOUND_TOO_MANY_LINES: "فاتورة التوريد تتجاوز الحد المسموح.",
          INBOUND_OPTIONS_INVALID: "بيانات وحدات الشراء غير صالحة.",
          INBOUND_RESPONSE_INVALID: "استجابة التوريد غير صالحة.",
          INBOUND_REFERENCE_DUPLICATE: "رقم الفاتورة أو المرجع مسجل مسبقاً.",
          INBOUND_BATCH_EXPIRED: "لا يمكن استلام دفعة منتهية الصلاحية كرصد متاح.",
          INBOUND_PRODUCTION_DATE_FUTURE: "تاريخ الإنتاج لا يجوز أن يكون في المستقبل.",
          INBOUND_BATCH_METADATA_CONFLICT: "الدفعة موجودة مسبقاً ببيانات مختلفة.",
          INBOUND_BATCH_UNAVAILABLE: "الدفعة غير متاحة للاستلام كرصد متاح.",
          INBOUND_CONCURRENT_CONFLICT: "حدث تعارض متزامن أثناء التوريد؛ لم يتم حفظ أي جزء.",
          INVENTORY_COST_POLICY_INVALID: "إعداد طريقة التكلفة غير صالح.",
          INVENTORY_COST_METHOD_INVALID: "طريقة احتساب التكلفة غير صالحة.",
          INVENTORY_COST_POLICY_LOCKED: "طريقة احتساب التكلفة مثبتة بعد أول توريد ولا يمكن تغييرها.",
          INVENTORY_COST_POLICY_VERSION_CONFLICT: "تغير إعداد التكلفة؛ حدّث البيانات وأعد المحاولة.",
          INBOUND_COST_REQUIRED: "تكلفة الشراء الفعلية مطلوبة لكل سطر توريد.",
          INBOUND_COST_QUANTITY_MISMATCH: "كمية التكلفة لا تطابق كمية المخزون.",
          COST_OPENING_BALANCE_REQUIRED: "يوجد مخزون سابق بلا تكلفة افتتاحية؛ يجب تثبيت قيمته قبل تشغيل محرك التكلفة.",
          INVENTORY_COST_RECONCILIATION_FAILED: "فشلت مطابقة كمية التكلفة مع المخزون الفعلي؛ تم رفض العملية.",
          FIFO_COST_LAYER_SHORTAGE: "طبقات تكلفة الوارد أولاً لا تغطي كمية الصرف؛ تم رفض العملية.",
          COST_BASIS_REQUIRED: "لا توجد تكلفة مثبتة يمكن الاعتماد عليها لهذه الزيادة المخزنية.",
          COST_REVERSAL_SOURCE_MISSING: "تعذر العثور على أصل التكلفة المطلوب عكسه.",
          COST_REVERSAL_SOURCE_MISMATCH: "أصل التكلفة لا يطابق الحركة العكسية.",
          COST_REVERSAL_ALREADY_APPLIED: "تم عكس هذه التكلفة مسبقاً.",
          FIFO_REVERSAL_LAYER_ALREADY_CONSUMED: "لا يمكن عكس الاستلام بدقة لأن جزءاً من طبقة تكلفته استُهلك لاحقاً.",
          NETWORK_UNAVAILABLE:
            "لا يوجد اتصال بالإنترنت.",
          REQUEST_TIMEOUT:
            "انتهت مهلة الاتصال. يمكنك إعادة المحاولة بأمان.",
          INVALID_SERVER_RESPONSE:
            "وصلت استجابة غير صالحة من السيرفر.",
          SIMPLE_PRODUCT_PRICE_REQUIRED:
            "أدخل سعراً واحداً على الأقل.",
          SIMPLE_PRODUCT_PRICE_INVALID:
            "قيمة السعر غير صالحة.",
          SIMPLE_PRODUCT_BARCODE_CONFLICT:
            "الباركود مستخدم مسبقاً.",
          SIMPLE_PRODUCT_BARCODE_DUPLICATE:
            "يوجد باركود مكرر.",
          SIMPLE_PRODUCT_FAMILY_NAME_CONFLICT:
            "توجد عائلة بهذا الاسم مسبقاً.",
          SIMPLE_PRODUCT_FAMILY_VERSION_CONFLICT:
            "تم تعديل العائلة من مكان آخر. حدّث الصفحة وأعد المحاولة.",
          PRODUCT_IMPORT_REQUEST_CONFLICT:
            "رقم العملية مستخدم لملف مختلف. تم إيقاف الطلب حمايةً من التكرار.",
          PRODUCT_IMPORT_FILE_TYPE_UNSUPPORTED:
            "ارفع ملف CSV أو XLSX.",
          PRODUCT_IMPORT_FILE_TOO_LARGE:
            "ملف الاستيراد أكبر من الحد المسموح.",
          PRODUCT_IMPORT_FILE_EMPTY:
            "ملف الاستيراد فارغ.",
          PRODUCT_IMPORT_MAPPING_INVALID:
            "ربط الأعمدة غير صالح.",
          PRODUCT_IMPORT_VALIDATION_FAILED:
            "يوجد صفوف بحاجة تصحيح قبل الاستيراد.",
          IMPORT_NAME_REQUIRED:
            "اسم المنتج مطلوب.",
          IMPORT_PACKAGING_REQUIRED:
            "عدد الحبات داخل العبوة مطلوب.",
          IMPORT_PACKAGING_INVALID:
            "عدد الحبات داخل العبوة غير صالح.",
          IMPORT_BARCODE_DUPLICATE:
            "الباركود مكرر في أكثر من صف.",
          IMPORT_BARCODE_CONFLICT:
            "الباركود مستخدم مسبقاً.",
        },
      },
    },
  },
  en: {
    translation: {
      common: {
        save: "Save",
        cancel: "Cancel",
        close: "Close",
        refresh: "Refresh",
        edit: "Edit",
        retry: "Retry",
        optional: "Optional",
        loading: "Loading...",
        comingSoon: "Coming soon",
      },
      nav: {
        home: "Home",
        dispatch: "Dispatch & Regions",
        inventory: "Inventory & Warehouse",
        products: "Products",
        commercialRules: "Offers & Taxes",
        salesReturns: "Sales Returns",
        reports: "Archive & Reports",
        settings: "Settings",
        accountSettings: "Account settings",
        logout: "Log out",
        mainNavigation: "Main navigation",
        systemAdmin: "System administrator",
        inventoryUser: "Inventory user",
        companyPanel: "Company dashboard",
        operationsCenter: "Operations center",
        locationUnknown: "Location unavailable",
        administrator: "Administrator",
        pageInDevelopment:
          "\"{{page}}\" is still in development",
        openNavigation: "Open navigation",
      },
      access: {
        loading: "Loading account permissions...",
        failed:
          "Could not verify account permissions",
      },
      network: {
        offlineBanner:
          "You are offline. No command will be silently executed later, and your saved input will not be lost.",
        offline:
          "No internet connection. Retry after the network is back.",
        timeout:
          "The server response timed out. Retry safely; the same operation id will prevent duplicates.",
        invalidResponse:
          "The server returned an invalid response.",
        sessionExpired: "Your session has expired.",
        refreshFailed:
          "The session could not be refreshed.",
        serverError:
          "The request could not be completed.",
      },
      products: {
        title: "Products",
        subtitle:
          "Create the product and its price in one flow; the system handles the internal complexity.",
        searchPlaceholder:
          "Search by product or family...",
        addProduct: "Add product",
        importFile: "Import file",
        families: "Families",
        advancedPricing: "Advanced pricing",
        advancedPricingHint:
          "Will be enabled later",
        emptyTitle: "No products yet",
        emptyDescription:
          "Add a product or import a file.",
        columns: {
          product: "Product",
          package: "Package",
          unitsPerPackage:
            "Units / package",
          packagePrice: "Package price",
          unitPrice: "Unit price",
          action: "Action",
        },
        editPrice: "Edit price",
        addTitle: "Add product",
        productName: "Product name",
        productNamePlaceholder:
          "Example: Lolo Chips Cheese 20g",
        family: "Family",
        familyPlaceholder:
          "Select a family or type a new name",
        noOuterPackage: "Sold as a unit only",
        hasOuterPackage:
          "Has an outer package",
        packageType: "Package type",
        unitsPerPackage:
          "Units inside package",
        packagePrice: "Package price",
        unitPrice: "Unit price",
        packagePricePlaceholder:
          "Leave blank if you entered a unit price",
        unitPricePlaceholder:
          "Leave blank to calculate automatically",
        derivedPrice:
          "The missing price will be calculated automatically.",
        independentPrices:
          "Both prices will be stored exactly as entered, even when they do not match mathematically.",
        barcodeSection: "Barcode — optional",
        unitBarcode: "Unit barcode",
        packageBarcode: "Package barcode",
        copyBarcode:
          "Use unit barcode",
        copiedBarcode: "Barcode copied",
        saveProduct: "Save product",
        savePrice: "Save price",
        priceHelp:
          "Enter one price to calculate the other, or enter both to keep them independent.",
        draftRestored:
          "Your unfinished product was restored.",
        offlineSaveHint:
          "The product draft is kept on this device until saving succeeds or you cancel.",
        familiesTitle: "Manage families",
        familiesDescription:
          "A family groups sizes, flavors, or variants under one name while each item keeps its own price, stock, and barcode.",
        newFamilyPlaceholder: "Family name",
        addFamily: "Add family",
        variantCount: "{{count}} variants",
        noFamilies: "No families yet.",
        importTitle: "Import products",
        importIntro:
          "CSV and Excel are supported. Column order does not matter; unclear columns are never guessed and will be mapped before import.",
        downloadTemplate: "Download template",
        dropFile:
          "Drop the file here or click to choose",
        importLimit:
          "Up to 50,000 rows — processing runs in the background",
        uploadAndStart:
          "Upload and start import",
        queued: "The import is queued...",
        mappingIntro:
          "Unclear columns were not guessed. Map only what is needed, then continue.",
        unmapped: "Not mapped",
        continueImport: "Continue import",
        preparingImport:
          "Preparing and validating file",
        importingProducts:
          "Importing products",
        backgroundHint:
          "You may close this dialog; processing continues in the background.",
        validationFailed:
          "Nothing was imported. {{count}} rows need correction.",
        downloadErrors: "Download error report",
        errorReportRow: "Row",
        errorReportCode: "Error code",
        errorReportMessage: "Error",
        newImport: "Upload corrected file / new import",
        rowNumber: "Row {{row}}",
        importFailed:
          "The import failed after retries. No half-created product was left behind.",
        importCompleted:
          "{{count}} products imported successfully",
        importAccepted:
          "File accepted. Processing is running in the background.",
        importResumed:
          "The active import was restored.",
        mappingAccepted:
          "Column mapping accepted.",
        retryQueued:
          "The import was queued for retry.",
        created:
          "Product and price saved.",
        priceUpdated: "Prices updated.",
        familyCreated: "Family created.",
        familyUpdated: "Family updated.",
        fields: {
          name: "Product name",
          family: "Family",
          packageUom: "Package type",
          unitsPerPackage:
            "Units inside package",
          packagePrice: "Package price",
          unitPrice: "Unit price",
          unitBarcode: "Unit barcode",
          packageBarcode: "Package barcode",
        },
        errors: {
          nameRequired:
            "Product name is required.",
          packageUnitsInvalid:
            "Units per package must be an integer greater than 1.",
          priceRequired:
            "Enter a package price or a unit price.",
          unitPriceRequired:
            "Enter a unit price.",
          fileRequired:
            "Choose a file first.",
          unsupportedFile:
            "Supported files are CSV and XLSX.",
          createFailed:
            "Could not save the product.",
          priceFailed:
            "Could not update prices.",
          familyFailed:
            "Could not save the family.",
          importFailed:
            "Could not upload the import file.",
          mappingFailed:
            "Could not save the column mapping.",
          retryFailed:
            "Could not retry the import.",
        },
      },
      inventoryInbound: {
        title: "Receive stock",
        product: "Product",
        search: "Search...",
        batchAndDates: "Batch & dates",
        quantityAndUnit: "Quantity & purchase unit",
        purchaseCost: "Purchase cost per unit",
        clearDraft: "Clear draft",
        noProducts: "No active products",
        batchNumber: "Batch number",
        productionDate: "Production date",
        expiryDate: "Expiry date",
        factorToBase: "= {{factor}} {{unit}}",
        unitCostPlaceholder: "Actual cost",
        addBatch: "Add another batch",
        removeBatch: "Remove batch",
        previousPage: "Previous page",
        nextPage: "Next page",
        reference: "Invoice / reference number",
        notes: "Notes",
        costMethod: "Costing method",
        methods: {
          MOVING_AVERAGE: "Moving average",
          FIFO: "First in, first out",
        },
        costMethodLocked: "Locked after first receipt",
        submitting: "Posting...",
        submit: "Post receipt",
        clearTitle: "Clear draft?",
        clearConfirm: "Clear",
        clearBody: "Only the current local inbound draft will be cleared.",
        defaultBatchTitle: "Default batch details for this receipt",
        defaultBatchHint:
          "Enter them once and they will apply to every item without its own batch override. Override any item when needed.",
        defaultBatchPlaceholder: "Example: LOT-2026-09",
        overrideBatchPlaceholder: "Default: {{batch}}",
        rowBatchOverrideHint:
          "Leave this empty to use the receipt default, or enter a different batch for this item only.",
        addReceiptLine: "Add another quantity/unit for this product",
        policySaved: "Costing method saved.",
        received: "Receipt and purchase cost posted successfully.",
        errors: {
          catalogLoad: "Could not load products.",
          optionsLoad: "Could not load purchase units.",
          policyLoad: "Could not load the costing setting.",
          policySave: "Could not save the costing method.",
          auditLocked: "The warehouse is locked by a full stocktake.",
          quantityRequired: "Add a quantity for at least one product.",
          referenceRequired: "Invoice or reference number is required.",
          optionsNotReady: "Purchase units are not ready yet.",
          submit: "Could not post the receipt.",
        },
      },
      inventoryCommon: {
        unit: "Unit",
      },
      inventoryLive: {
        inWarehouse: "In warehouse",
        averageCost: "Average cost",
        averageCostHint:
          "The company's current average cost for this product, shown in the commercial display unit when one unambiguous conversion is configured.",
        blocked: "Blocked from issue",
      },
      inventoryLedger: {
        batch: "Batch",
        balanceBefore: "Balance before",
        quantity: "Quantity",
        balanceAfter: "Balance after",
        purchaseCost: "Purchase cost",
        averageAfter: "Average cost after movement",
        supervisor: "Supervisor",
        totalCost: "Total cost",
      },
      uom: {
        CARTON: "Carton",
        CASE: "Case",
        PACK: "Pack",
        BAG: "Bag",
        SACK: "Sack",
        TRAY: "Tray",
        CRATE: "Crate",
        BUNDLE: "Bundle",
        PALLET: "Pallet",
        NONE: "No package",
        EACH: "Unit",
      },
      errors: {
        serverReasonWithCodeAndReference:
          "{{message}} — error code: {{code}} — reference: {{requestId}}",
        serverReasonWithCode:
          "{{message}} — error code: {{code}}",
        serverReasonWithReference:
          "{{message}} — reference: {{requestId}}",
        fallbackWithCodeAndReference:
          "{{fallback}} — error code: {{code}} — reference: {{requestId}}",
        fallbackWithCode:
          "{{fallback}} — error code: {{code}}",
        fallbackWithReference:
          "{{fallback}} — reference: {{requestId}}",
        unexpected:
          "An unexpected server error occurred.",
        unexpectedWithReference:
          "An unexpected server error occurred. Reference: {{requestId}}",
        codes: {
          OPERATIONS_RESPONSE_INVALID: "The operations response is invalid or incomplete.",
          INBOUND_DUPLICATE_BATCH_UOM_LINE: "Do not repeat the same product, batch, and purchasing unit on multiple lines. Add another line only for a different purchasing unit.",
          VALIDATION_ERROR: "The request data is invalid. Review the entered fields.",
          RATE_LIMITED: "The request limit was exceeded. Try again later.",
          REQUEST_TOO_LARGE: "The request is larger than the allowed limit.",
          INTERNAL_SERVER_ERROR: "An internal server error occurred.",
          PRODUCT_LOCATION_REQUIRED: "This product is not assigned to the selected warehouse.",
          PRODUCT_LOCATION_INBOUND_DISABLED: "Inbound is disabled for this product at the selected warehouse.",
          INBOUND_UNIT_COST_INVALID: "Enter a valid purchase cost with at most 6 decimal places.",
          INBOUND_VARIANT_UNAVAILABLE: "A product is no longer active or does not belong to your company.",
          INBOUND_UOM_REQUIRED: "Select the purchase unit.",
          INBOUND_UOM_UNSUPPORTED: "The purchase unit has no exact conversion to the product base unit.",
          INBOUND_UOM_CONVERSION_INVALID: "A purchase-unit conversion is invalid.",
          INBOUND_UOM_CONVERSION_CONFLICT: "Conflicting purchase-unit conversions were found for this product.",
          INBOUND_UOM_REFERENCE_MISSING: "A required unit reference is missing.",
          INBOUND_QUANTITY_CONVERSION_INVALID: "The quantity cannot be represented exactly in the product base unit.",
          INBOUND_BATCH_INVALID: "Enter a valid batch number.",
          INBOUND_BATCH_DATES_INVALID: "Batch dates are invalid.",
          INBOUND_EXPIRY_REQUIRED: "Expiry date is required for this product.",
          INBOUND_EXPIRY_NOT_ALLOWED: "This product does not use expiry tracking.",
          INBOUND_DUPLICATE_BATCH_LINE: "Do not repeat the same product batch in one receipt.",
          INBOUND_TOO_MANY_LINES: "The receipt exceeds the supported line limit.",
          INBOUND_OPTIONS_INVALID: "Purchase-unit data is invalid.",
          INBOUND_RESPONSE_INVALID: "The inbound response is invalid.",
          INBOUND_REFERENCE_DUPLICATE: "The invoice or reference number was already posted.",
          INBOUND_BATCH_EXPIRED: "Expired stock cannot be received as available inventory.",
          INBOUND_PRODUCTION_DATE_FUTURE: "Production date cannot be in the future.",
          INBOUND_BATCH_METADATA_CONFLICT: "The batch already exists with different metadata.",
          INBOUND_BATCH_UNAVAILABLE: "The batch is not available for receipt.",
          INBOUND_CONCURRENT_CONFLICT: "A concurrent receipt conflict occurred; nothing was committed.",
          INVENTORY_COST_POLICY_INVALID: "The costing setting is invalid.",
          INVENTORY_COST_METHOD_INVALID: "The inventory costing method is invalid.",
          INVENTORY_COST_POLICY_LOCKED: "The costing method is locked after the first receipt.",
          INVENTORY_COST_POLICY_VERSION_CONFLICT: "The costing setting changed. Refresh and retry.",
          INBOUND_COST_REQUIRED: "Actual purchase cost is required for every receipt line.",
          INBOUND_COST_QUANTITY_MISMATCH: "Cost quantity does not match inventory quantity.",
          COST_OPENING_BALANCE_REQUIRED: "Existing stock has no opening valuation. Set its opening value before activating costing.",
          INVENTORY_COST_RECONCILIATION_FAILED: "Cost quantity did not reconcile with physical stock; the operation was rejected.",
          FIFO_COST_LAYER_SHORTAGE: "FIFO cost layers do not cover the outbound quantity; the operation was rejected.",
          COST_BASIS_REQUIRED: "No established cost basis is available for this inventory increase.",
          COST_REVERSAL_SOURCE_MISSING: "The original cost evidence for this reversal is missing.",
          COST_REVERSAL_SOURCE_MISMATCH: "The original cost evidence does not match this reversal.",
          COST_REVERSAL_ALREADY_APPLIED: "This cost was already reversed.",
          FIFO_REVERSAL_LAYER_ALREADY_CONSUMED: "The receipt cannot be reversed exactly because part of its FIFO cost layer was consumed later.",
          NETWORK_UNAVAILABLE:
            "No internet connection.",
          REQUEST_TIMEOUT:
            "The request timed out. It is safe to retry.",
          INVALID_SERVER_RESPONSE:
            "The server returned an invalid response.",
          SIMPLE_PRODUCT_PRICE_REQUIRED:
            "Enter at least one price.",
          SIMPLE_PRODUCT_PRICE_INVALID:
            "The price is invalid.",
          SIMPLE_PRODUCT_BARCODE_CONFLICT:
            "The barcode is already in use.",
          SIMPLE_PRODUCT_BARCODE_DUPLICATE:
            "A barcode is duplicated.",
          SIMPLE_PRODUCT_FAMILY_NAME_CONFLICT:
            "A family with this name already exists.",
          SIMPLE_PRODUCT_FAMILY_VERSION_CONFLICT:
            "The family changed elsewhere. Refresh and retry.",
          PRODUCT_IMPORT_REQUEST_CONFLICT:
            "This operation id was already used for a different file.",
          PRODUCT_IMPORT_FILE_TYPE_UNSUPPORTED:
            "Upload a CSV or XLSX file.",
          PRODUCT_IMPORT_FILE_TOO_LARGE:
            "The import file exceeds the size limit.",
          PRODUCT_IMPORT_FILE_EMPTY:
            "The import file is empty.",
          PRODUCT_IMPORT_MAPPING_INVALID:
            "The column mapping is invalid.",
          PRODUCT_IMPORT_VALIDATION_FAILED:
            "Some rows must be corrected before import.",
          IMPORT_NAME_REQUIRED:
            "Product name is required.",
          IMPORT_PACKAGING_REQUIRED:
            "Units per package are required.",
          IMPORT_PACKAGING_INVALID:
            "Units per package are invalid.",
          IMPORT_BARCODE_DUPLICATE:
            "The barcode appears on more than one row.",
          IMPORT_BARCODE_CONFLICT:
            "The barcode is already in use.",
        },
      },
    },
  },
} as const;
