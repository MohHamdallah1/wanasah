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
        saving: "جاري الحفظ...",
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
      inventoryShell: {
        navigationLabel: "أقسام إدارة المخزون",
        title: "إدارة المخزون",
        subtitle: "الأرصدة والحركات والعمليات المخزنية",
        warehouseSelectLabel: "المستودع المحدد",
        chooseWarehouse: "اختر المستودع",
        liveStockCount: "الرصيد الحي",
        locked: "مقفل",
        lastUpdated: "آخر تحديث",
        refreshNow: "تحديث الآن",
        loadingWarehouses: "جارٍ جلب مستودعات الشركة...",
        locationsLoadTitle: "تعذر جلب مستودعات الشركة",
        locationsLoadGuard:
          "تم إيقاف واجهة المخزون احترازياً حتى نتأكد من المواقع التابعة للشركة الحالية.",
        retry: "إعادة المحاولة",
        locationsTruncated:
          "يعرض محدد التشغيل أول 200 مستودع متاح. استخدم إدارة المستودعات للبحث عن موقع آخر.",
        accessChanged: "الموقع غير متاح أو تغيرت صلاحياتك.",
        refreshAccess: "تحديث المواقع والصلاحيات",
        noWarehouseCreated:
          "لم تُنشئ الشركة مستودعاً فعالاً بعد. أنشئ المستودع من شاشة إدارة المستودعات أولاً.",
        noAccessibleWarehouse:
          "توجد مستودعات فعالة للشركة، لكن حسابك لا يملك وصولاً إلى أي منها.",
        noWarehouseSelected:
          "لا يوجد مستودع محدد لهذه العملية. اختر مستودعاً فعالاً.",
        openWarehouseManagement: "فتح إدارة المستودعات",
        errors: {
          locationsLoadFailed: "تعذر تحميل مستودعات الشركة.",
          statusCheckFailed:
            "تعذر التحقق من حالة قفل المستودع. تم إبقاء الواجهة في الوضع الآمن.",
        },
        tabsLabel: "شاشات المخزون",
        tabs: {
          live: "الرصيد الحي",
          batches: "الدفعات والصلاحية",
          inbound: "توريد بضاعة",
          transfers: "الحوالات",
          ledger: "سجل الحركات",
          stocktake: "جرد وتسوية",
          warehouses: "إدارة المستودعات",
          permissions: "الصلاحيات",
        },
      },
      inventoryBatches: {
        searchPlaceholder: "ابحث عن منتج أو SKU...",
        noProducts: "لا توجد منتجات مطابقة.",
        chooseProduct: "اختر منتجاً لعرض دفعاته وصلاحيته.",
        loadMoreProducts: "تحميل منتجات إضافية",
        batchCount: "{{count}} دفعة",
        status: "الحالة",
        restrictions: "القيود والحالات",
        errors: {
          products: "تعذر تحميل منتجات المستودع.",
          details: "تعذر تحميل تفاصيل الدفعات.",
        },
      },
      inventoryMinimum: {
        button: "الحد الأدنى للمخزون",
        title: "إدارة الحد الأدنى للمخزون",
        description:
          "حدد الحد الأدنى للمخزون في المستودع الحالي لكل المنتجات أو لعائلات ومنتجات تختارها.",
        scopeAll: "كل المنتجات",
        scopeAllHint:
          "سيشمل التعديل جميع منتجات المستودع الحالي. اختر طريقة التطبيق بالأسفل قبل التنفيذ.",
        scopeFamily: "عائلات محددة",
        scopeProduct: "منتجات محددة",
        searchFamily: "ابحث عن عائلة...",
        searchProduct: "ابحث عن منتج أو SKU...",
        valueLabel: "الحد الأدنى للمخزون",
        unitHint:
          "يُطبّق الرقم بوحدة العرض الخاصة بكل منتج؛ كرتونة للمنتجات المعروضة بالكرتونة وحبة للمنتجات المعروضة بالحبة.",
        onlyUnset: "فقط غير المحدد",
        onlyUnsetHint: "يحافظ على الحدود التي تم ضبطها سابقاً.",
        overwrite: "استبدال الحالي",
        overwriteHint: "يحدّث الحد الأدنى حتى لو كان محدداً مسبقاً.",
        applyToSelection: "تحديث العناصر المحددة",
        applyToSelectionHint:
          "يضع الرقم الجديد على كامل النطاق المختار، ويستبدل الحد السابق إن وجد.",
        fillMissingOnly: "إضافة للمنتجات بدون حد",
        fillMissingOnlyHint:
          "لا يغيّر أي حد موجود مسبقاً؛ يضبط فقط المنتجات التي لم يُحدد لها حد.",
        preview: "معاينة",
        previewOptional: "معاينة (اختياري)",
        apply: "تطبيق",
        selectedCount: "{{count}} محدد",
        clearSelection: "مسح التحديد",
        selectedFamilies: "{{count}} عائلة محددة",
        selectedProducts: "{{count}} منتج محدد",
        previewMatched: "{{count}} منتج ضمن النطاق",
        previewAffected: "سيتم تعديلها",
        previewSkipped: "محفوظة كما هي",
        previewConflict:
          "{{count}} منتج لديه تعارض يمنع التطبيق الآمن. عدّل الإعداد قبل التنفيذ.",
        applied: "تم تحديث الحد الأدنى لـ {{count}} منتج.",
        noChangesExisting:
          "لم يتغير شيء: {{count}} منتج لديه حد مسبقاً. اختر «تحديث العناصر المحددة» إذا أردت تغيير الحدود الحالية.",
        noChangesSame:
          "لا يوجد تغيير: القيمة المدخلة مطابقة للحد الحالي في النطاق المختار.",
        errors: {
          preview: "تعذر معاينة تطبيق الحد الأدنى.",
          apply: "تعذر تطبيق الحد الأدنى للمخزون.",
        },
      },
      inventoryLive: {
        product: "المنتج",
        searchPlaceholder: "ابحث عن منتج أو SKU...",
        warehouseBalance: "داخل المستودع",
        warehouseBalanceHint:
          "هذا التقسيم يخص البضاعة الموجودة داخل المستودع المحدد فقط. إجمالي الموجود = محجوز لعملية + متاح للبيع + غير متاح للبيع. بضاعة المركبات منفصلة.",
        onHand: "إجمالي الموجود",
        onHandHint:
          "كل البضاعة الموجودة فعليًا داخل المستودع المحدد بجميع حالاتها. تشمل المحجوز لعملية وغير المتاح للبيع، ولا تشمل بضاعة المركبات.",
        reserved: "محجوز لعملية",
        reservedHint:
          "كمية موجودة داخل المستودع حجزها النظام مؤقتًا لعملية جارية. تبقى ضمن إجمالي الموجود، لكنها لا تدخل في المتاح للبيع حتى تُحرر أو تُنفذ العملية.",
        availableForSale: "المتاح للبيع",
        availableForSaleHint:
          "الكمية الموجودة داخل المستودع التي يسمح النظام بصرفها أو بيعها الآن بعد استبعاد الحجز والحالات غير القابلة للبيع.",
        withVehicles: "مع المركبات",
        withVehiclesHint:
          "بضاعة خرجت فعليًا من المستودع وأصبحت في مركبات مرتبطة بهذا المستودع. لا تدخل ضمن إجمالي الموجود داخل المستودع.",
        companyCosts: "التكاليف",
        resultCount: "{{total}} منتج",
        costs: "التكلفة",
        costsHint:
          "بيانات التكلفة مالية على مستوى الشركة وليست تكلفة مستقلة لهذا المستودع. لا تظهر في هذه الشاشة عندما لا توجد لهذا المنتج بضاعة مرتبطة بالمستودع المحدد.",
        lastCompanyPurchase: "تكلفة آخر شراء",
        lastCompanyPurchaseHint:
          "آخر تكلفة شراء فعلية مسجلة لهذا المنتج على مستوى الشركة، بالوحدة التي تم الشراء بها.",
        companyAverage: "متوسط التكلفة",
        companyAverageHint:
          "متوسط التكلفة المالي الحالي للمنتج على مستوى الشركة. يظهر هنا فقط عندما توجد بضاعة مرتبطة بالمستودع المحدد.",
        unavailable: "غير متاح للبيع",
        unavailableHint:
          "بضاعة موجودة داخل المستودع لكنها غير متاحة للبيع الآن بسبب الصلاحية أو الحجر أو الإيقاف أو السحب أو التلف أو انتظار الإتلاف.",
        perUnit: "لكل {{unit}}",
        results: "النتائج: {{count}}",
        page: "صفحة {{page}}",
        noMatches: "لا توجد بيانات مطابقة",
        atMinimum: "وصل للحد الأدنى للمخزون",
        minimumStockLabel: "الحد الأدنى",
        minimumStockUnset: "غير محدد",
        editMinimumStock: "تعديل",
        minimumStockDialogTitle: "تحديد الحد الأدنى للمخزون",
        minimumStockDialogDescription:
          "حدد الحد الأدنى للمنتج {{product}} في المستودع الحالي. عند وصول المتاح للبيع إلى هذا الحد أو أقل سيظهر المنتج كتنبيه أحمر للمسؤول.",
        minimumStockInputLabel: "الحد الأدنى ({{unit}})",
        minimumStockZeroHint:
          "أدخل 0 لإيقاف تنبيه النقص لهذا المنتج في هذا المستودع. الإعداد تابع لشركتك ولا يؤثر على الشركات الأخرى.",
        minimumStockSave: "حفظ الحد الأدنى",
        minimumStockSaved: "تم تحديث الحد الأدنى للمخزون.",
        minimumStockInvalid: "أدخل كمية صحيحة غير سالبة حتى 6 منازل عشرية.",
        minimumStockSaveFailed: "تعذر تحديث الحد الأدنى للمخزون.",
        alertFilterTitle: "عرض الأصناف التي وصلت للحد الأدنى",
        filterButton: "فلترة",
        filterTitle: "فلترة الرصيد الحي",
        filterSubtitle: "طبّق الفلاتر على كامل المخزون، وليس على الصفحة الحالية فقط.",
        stockStateTitle: "حالة الرصيد",
        filterAll: "كل المنتجات",
        filterAllHint: "عرض كل المنتجات الظاهرة لهذا المستودع.",
        filterOnHand: "فيه رصيد بالمستودع",
        filterOnHandHint: "يوجد رصيد مادي داخل المستودع حتى لو كان محجوزاً أو غير متاح للبيع.",
        filterSellable: "متاح للبيع",
        filterSellableHint: "يوجد رصيد متاح للبيع بعد الحجوزات والقيود.",
        filterOutOfStock: "غير متاح للبيع",
        filterOutOfStockHint: "لا يوجد رصيد متاح للبيع حالياً.",
        filterLowStock: "وصل للحد الأدنى",
        filterLowStockHint: "المنتجات عند الحد الأدنى أو أقل.",
        filterLowStockCount: "{{count}} منتج يحتاج انتباه",
        indicatorsTitle: "مؤشرات المخزون",
        indicatorReserved: "عليه حجز",
        indicatorUnavailable: "فيه غير متاح للبيع",
        indicatorDamaged: "فيه تالف",
        indicatorRecalled: "فيه مسحوب",
        indicatorVehicle: "له رصيد مع المركبات",
        indicatorMinimumUnset: "الحد الأدنى غير محدد",
        familyTitle: "عائلة المنتج",
        familySearch: "ابحث باسم العائلة أو الكود...",
        allFamilies: "كل العائلات",
        clearFamily: "إلغاء فلتر العائلة",
        family: "العائلة",
        sortTitle: "الترتيب",
        sortNameAsc: "الاسم: أ ← ي",
        sortNameDesc: "الاسم: ي ← أ",
        filterReset: "إلغاء الفلترة",
        rowNumber: "المنتج رقم {{number}}",
        alertTitle: "{{count}} صنف وصل للحد الأدنى",
        alertFiltered: "الجدول يعرض هذه الأصناف فقط",
        alertPreview: "منها: {{items}}{{more}}",
        previousPage: "الصفحة السابقة",
        nextPage: "الصفحة التالية",
        openBatchDetails: "فتح تفاصيل الدفعات والصلاحية",
        closeBatchDetails: "إغلاق تفاصيل الدفعات والصلاحية",
        batchDetailsHint: "الدفعات والصلاحية والحالات",
        batchPanelTitle: "الدفعات والصلاحية",
        batchPanelHint:
          "الكميات أدناه تخص المستودع المحدد فقط. تكاليف الشراء هي أدلة مالية للمنتج داخل الشركة ولا تغيّر رصيد أي مستودع.",
        loadingBatches: "جاري تحميل تفاصيل الدفعات...",
        noBatchesInWarehouse: "لا توجد دفعات برصيد حالي داخل هذا المستودع.",
        batchNumber: "رقم الدفعة",
        productionDate: "الإنتاج",
        expiryDate: "الصلاحية",
        expiresToday: "تنتهي اليوم",
        daysRemaining: "متبقي {{count}} يوم",
        expiredSince: "منتهية منذ {{count}} يوم",
        latestBatchPurchase: "آخر شراء لهذه الدفعة",
        batchPurchaseEvents: "{{count}} عملية توريد مسجلة لهذه الدفعة",
        noBatchPurchaseEvidence: "لا يوجد دليل شراء مباشر مسجل لهذه الدفعة",
        noRestrictedStock: "لا توجد كميات مقيدة",
        restricted: "غير صالح للبيع",
        quarantined: "محجور",
        blocked: "موقوف",
        recalled: "مسحوب",
        damaged: "تالف",
        disposalPending: "بانتظار الإتلاف",
        recalledShort: "مسحوب",
        damagedShort: "تالف",
        batchDisposition: {
          RELEASED: "مفرج عنها",
          QUARANTINED: "محجورة",
          BLOCKED: "موقوفة",
          RECALLED: "مسحوبة",
        },
        errors: {
          loadFailed: "تعذر تحميل الرصيد الحي.",
          batchLoadFailed: "تعذر تحميل تفاصيل الدفعات.",
        },
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
          LIVE_STOCK_RESPONSE_INVALID: "استجابة الرصيد الحي غير صالحة أو غير مكتملة.",
          LIVE_STOCK_BATCH_RESPONSE_INVALID: "استجابة تفاصيل الدفعات غير صالحة أو غير مكتملة.",
          LIVE_STOCK_LOCATION_NOT_FOUND: "المستودع المحدد غير متاح.",
          LIVE_STOCK_PRODUCT_NOT_FOUND: "المنتج المحدد غير متاح.",
          STOCK_MINIMUM_ADMIN_REQUIRED: "تعديل الحد الأدنى متاح لمسؤول الشركة فقط.",
          STOCK_MINIMUM_LOCATION_NOT_FOUND: "المستودع المحدد غير موجود أو غير فعال.",
          STOCK_MINIMUM_PRODUCT_NOT_FOUND: "المنتج المحدد غير موجود ضمن هذه الشركة.",
          STOCK_MINIMUM_PRODUCT_LOCATION_REQUIRED: "اربط المنتج بالمستودع قبل تحديد الحد الأدنى له.",
          STOCK_MINIMUM_UOM_UNSUPPORTED: "وحدة الحد الأدنى لا تملك تحويلاً صالحاً إلى وحدة أساس المنتج.",
          STOCK_MINIMUM_UOM_INVALID: "تحويل وحدة الحد الأدنى غير صالح.",
          STOCK_MINIMUM_QUANTITY_INVALID: "كمية الحد الأدنى غير صالحة.",
          STOCK_MINIMUM_VERSION_CONFLICT: "تغير الحد الأدنى منذ فتح الصفحة. حدّث الرصيد ثم أعد المحاولة.",
          STOCK_MINIMUM_POLICY_INACTIVE: "سياسة هذا المنتج غير فعالة حالياً.",
          STOCK_MINIMUM_EXCEEDS_TARGET: "الحد الأدنى لا يجوز أن يتجاوز الكمية المستهدفة الحالية.",
          STOCK_MINIMUM_IDEMPOTENCY_CONFLICT: "تعارض طلب تعديل الحد الأدنى مع طلب سابق.",
          STOCK_MINIMUM_SCOPE_INVALID: "اختيار نطاق الحد الأدنى غير صالح.",
          STOCK_MINIMUM_BULK_CONFLICT: "تعذر تطبيق الحد الأدنى على كامل النطاق بأمان. راجع التعارضات أولاً.",
          LIVE_STOCK_PROJECTION_UNAVAILABLE: "تعذر تحديث الرصيد الحي حالياً. أعد المحاولة بعد قليل.",
          LIVE_STOCK_SEARCH_TOO_SHORT: "أدخل حرفين على الأقل للبحث في المخزون.",
          LIVE_STOCK_FAMILY_SEARCH_TOO_SHORT: "أدخل حرفين على الأقل للبحث في عائلات المنتجات.",
          LIVE_STOCK_ALERT_FILTER_CONFLICT: "لا يمكن دمج فلتر التنبيهات مع حالة رصيد أخرى.",
          LIVE_STOCK_FAMILY_INVALID: "عائلة المنتج المحددة غير صالحة.",
          LIVE_STOCK_BATCH_DETAILS_FAILED: "تعذر تحميل تفاصيل الدفعات.",
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
        saving: "Saving...",
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
      inventoryShell: {
        navigationLabel: "Inventory management sections",
        title: "Inventory management",
        subtitle: "Balances, movements, and warehouse operations",
        warehouseSelectLabel: "Selected warehouse",
        chooseWarehouse: "Choose warehouse",
        liveStockCount: "Live stock",
        locked: "Locked",
        lastUpdated: "Last updated",
        refreshNow: "Refresh now",
        loadingWarehouses: "Loading company warehouses...",
        locationsLoadTitle: "Could not load company warehouses",
        locationsLoadGuard:
          "Inventory has been paused until the current company's locations can be verified.",
        retry: "Retry",
        locationsTruncated:
          "The selector shows the first 200 accessible warehouses. Use Warehouse Management to find another location.",
        accessChanged: "This location is unavailable or your permissions changed.",
        refreshAccess: "Refresh locations and permissions",
        noWarehouseCreated:
          "The company has no active warehouse yet. Create one in Warehouse Management first.",
        noAccessibleWarehouse:
          "The company has active warehouses, but your account cannot access any of them.",
        noWarehouseSelected:
          "No warehouse is selected for this operation. Choose an active warehouse.",
        openWarehouseManagement: "Open Warehouse Management",
        errors: {
          locationsLoadFailed: "Could not load company warehouses.",
          statusCheckFailed:
            "Could not verify the warehouse lock state. The interface remains in safe mode.",
        },
        tabsLabel: "Inventory screens",
        tabs: {
          live: "Live stock",
          batches: "Batches & expiry",
          inbound: "Inbound receipt",
          transfers: "Transfers",
          ledger: "Movement ledger",
          stocktake: "Stocktake & adjustment",
          warehouses: "Warehouse management",
          permissions: "Permissions",
        },
      },
      inventoryBatches: {
        searchPlaceholder: "Search product or SKU...",
        noProducts: "No matching products.",
        chooseProduct: "Choose a product to view its batches and expiry details.",
        loadMoreProducts: "Load more products",
        batchCount: "{{count}} batches",
        status: "Status",
        restrictions: "Restrictions & states",
        errors: {
          products: "Could not load warehouse products.",
          details: "Could not load batch details.",
        },
      },
      inventoryMinimum: {
        button: "Minimum stock",
        title: "Manage minimum stock",
        description:
          "Set minimum stock for the current warehouse across all products or selected families and products.",
        scopeAll: "All products",
        scopeAllHint:
          "The update will include every product in the current warehouse. Choose how existing values should be handled below.",
        scopeFamily: "Selected families",
        scopeProduct: "Selected products",
        searchFamily: "Search family...",
        searchProduct: "Search product or SKU...",
        valueLabel: "Minimum stock",
        unitHint:
          "The number uses each product's display unit: cartons for carton-displayed products and eaches for each-displayed products.",
        onlyUnset: "Only unset",
        onlyUnsetHint: "Keeps thresholds that were already configured.",
        overwrite: "Replace current",
        overwriteHint: "Updates the minimum even when a value already exists.",
        applyToSelection: "Update selected items",
        applyToSelectionHint:
          "Applies the new value to the entire selected scope and replaces an existing minimum when present.",
        fillMissingOnly: "Set only missing minimums",
        fillMissingOnlyHint:
          "Keeps existing minimums unchanged and sets a value only where no minimum exists.",
        preview: "Preview",
        previewOptional: "Preview (optional)",
        apply: "Apply",
        selectedCount: "{{count}} selected",
        clearSelection: "Clear selection",
        selectedFamilies: "{{count}} families selected",
        selectedProducts: "{{count}} products selected",
        previewMatched: "{{count}} products in scope",
        previewAffected: "Will change",
        previewSkipped: "Kept unchanged",
        previewConflict:
          "{{count}} products have conflicts that block a safe update. Resolve them before applying.",
        applied: "Minimum stock updated for {{count}} products.",
        noChangesExisting:
          "Nothing changed: {{count}} products already have a minimum. Choose “Update selected items” to change existing values.",
        noChangesSame:
          "Nothing changed: the entered value already matches the current minimum in the selected scope.",
        errors: {
          preview: "Could not preview the minimum-stock update.",
          apply: "Could not apply minimum stock.",
        },
      },
      inventoryLive: {
        product: "Product",
        searchPlaceholder: "Search by product or SKU...",
        warehouseBalance: "Inside warehouse",
        warehouseBalanceHint:
          "This split covers stock physically inside the selected warehouse only. Total in warehouse = reserved for an operation + available for sale + unavailable for sale. Vehicle stock is separate.",
        onHand: "Total in warehouse",
        onHandHint:
          "All stock physically inside the selected warehouse in every status. It includes quantities reserved for an operation and quantities unavailable for sale, but excludes vehicle stock.",
        reserved: "Reserved for operation",
        reservedHint:
          "Stock that is still inside the warehouse but temporarily reserved by an in-progress system operation. It remains part of total warehouse stock and is excluded from sale availability until released or executed.",
        availableForSale: "Available for sale",
        availableForSaleHint:
          "Stock inside the warehouse that the system can issue or sell now after excluding reservations and non-sellable states.",
        withVehicles: "With vehicles",
        withVehiclesHint:
          "Stock that has physically left the warehouse and is now held by vehicles linked to this warehouse. It is not included in the warehouse total.",
        companyCosts: "Costs",
        resultCount: "Products: {{total}}",
        costs: "Cost",
        costsHint:
          "Cost data is financial evidence at company level, not a separate cost for this warehouse. It is hidden on this screen when the product has no inventory associated with the selected warehouse.",
        lastCompanyPurchase: "Latest purchase cost",
        lastCompanyPurchaseHint:
          "The latest actual purchase cost recorded for this product at company level, in the unit used for that purchase.",
        companyAverage: "Average cost",
        companyAverageHint:
          "The current company-wide financial average cost for this product. It is shown here only when inventory is associated with the selected warehouse.",
        unavailable: "Unavailable for sale",
        unavailableHint:
          "Stock physically inside the warehouse but not available for sale now because of expiry, quarantine, blocking, recall, damage, or pending disposal.",
        perUnit: "per {{unit}}",
        results: "Results: {{count}}",
        page: "Page {{page}}",
        noMatches: "No matching inventory",
        atMinimum: "Reached minimum stock",
        minimumStockLabel: "Minimum stock",
        minimumStockUnset: "Not set",
        editMinimumStock: "Edit",
        minimumStockDialogTitle: "Set minimum stock",
        minimumStockDialogDescription:
          "Set the minimum for {{product}} in the current warehouse. When sellable stock reaches this level or lower, the product is shown as a red alert to the responsible user.",
        minimumStockInputLabel: "Minimum stock ({{unit}})",
        minimumStockZeroHint:
          "Enter 0 to disable the low-stock alert for this product in this warehouse. The setting belongs only to your company.",
        minimumStockSave: "Save minimum",
        minimumStockSaved: "Minimum stock was updated.",
        minimumStockInvalid: "Enter a non-negative quantity with at most 6 decimal places.",
        minimumStockSaveFailed: "Could not update minimum stock.",
        alertFilterTitle: "Show products at or below minimum stock",
        filterButton: "Filter",
        filterTitle: "Filter live stock",
        filterSubtitle: "Filters apply to the full inventory, not only the current page.",
        stockStateTitle: "Stock state",
        filterAll: "All products",
        filterAllHint: "Show all products visible for this warehouse.",
        filterOnHand: "Stock in warehouse",
        filterOnHandHint: "Physical warehouse stock exists even if some is reserved or not sellable.",
        filterSellable: "Sellable",
        filterSellableHint: "Sellable stock remains after reservations and restrictions.",
        filterOutOfStock: "Not sellable",
        filterOutOfStockHint: "No stock is currently available for sale.",
        filterLowStock: "At or below minimum",
        filterLowStockHint: "Products at or below their minimum threshold.",
        filterLowStockCount: "{{count}} products need attention",
        indicatorsTitle: "Inventory indicators",
        indicatorReserved: "Has reservations",
        indicatorUnavailable: "Has unavailable stock",
        indicatorDamaged: "Has damaged stock",
        indicatorRecalled: "Has recalled stock",
        indicatorVehicle: "Stock with vehicles",
        indicatorMinimumUnset: "Minimum not set",
        familyTitle: "Product family",
        familySearch: "Search family name or code...",
        allFamilies: "All families",
        clearFamily: "Clear family filter",
        family: "Family",
        sortTitle: "Sort",
        sortNameAsc: "Name: A → Z",
        sortNameDesc: "Name: Z → A",
        filterReset: "Clear filters",
        rowNumber: "Product number {{number}}",
        alertTitle: "{{count}} products reached minimum stock",
        alertFiltered: "The table is showing only these products",
        alertPreview: "Including: {{items}}{{more}}",
        previousPage: "Previous page",
        nextPage: "Next page",
        openBatchDetails: "Open batch and expiry details",
        closeBatchDetails: "Close batch and expiry details",
        batchDetailsHint: "Batches, expiry, and statuses",
        batchPanelTitle: "Batches & expiry",
        batchPanelHint:
          "Quantities below are scoped only to the selected warehouse. Purchase costs are company financial evidence and do not change any warehouse balance.",
        loadingBatches: "Loading batch details...",
        noBatchesInWarehouse: "No batch currently has stock in this warehouse.",
        batchNumber: "Batch",
        productionDate: "Production",
        expiryDate: "Expiry",
        expiresToday: "Expires today",
        daysRemaining: "{{count}} days remaining",
        expiredSince: "Expired {{count}} days ago",
        latestBatchPurchase: "Latest purchase for this batch",
        batchPurchaseEvents: "{{count}} purchase receipts recorded for this batch",
        noBatchPurchaseEvidence: "No direct purchase evidence is recorded for this batch",
        noRestrictedStock: "No restricted quantities",
        restricted: "Not sellable",
        quarantined: "Quarantined",
        blocked: "Blocked",
        recalled: "Recalled",
        damaged: "Damaged",
        disposalPending: "Pending disposal",
        recalledShort: "Recalled",
        damagedShort: "Damaged",
        batchDisposition: {
          RELEASED: "Released",
          QUARANTINED: "Quarantined",
          BLOCKED: "Blocked",
          RECALLED: "Recalled",
        },
        errors: {
          loadFailed: "Could not load live inventory.",
          batchLoadFailed: "Could not load batch details.",
        },
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
          LIVE_STOCK_RESPONSE_INVALID: "The live-stock response is invalid or incomplete.",
          LIVE_STOCK_BATCH_RESPONSE_INVALID: "The batch-detail response is invalid or incomplete.",
          LIVE_STOCK_LOCATION_NOT_FOUND: "The selected warehouse is unavailable.",
          LIVE_STOCK_PRODUCT_NOT_FOUND: "The selected product is unavailable.",
          STOCK_MINIMUM_ADMIN_REQUIRED: "Only a company administrator can change minimum stock.",
          STOCK_MINIMUM_LOCATION_NOT_FOUND: "The selected warehouse does not exist or is inactive.",
          STOCK_MINIMUM_PRODUCT_NOT_FOUND: "The selected product does not belong to this company.",
          STOCK_MINIMUM_PRODUCT_LOCATION_REQUIRED: "Assign the product to this warehouse before setting its minimum.",
          STOCK_MINIMUM_UOM_UNSUPPORTED: "The selected minimum-stock unit cannot be converted to the product base unit.",
          STOCK_MINIMUM_UOM_INVALID: "The minimum-stock unit conversion is invalid.",
          STOCK_MINIMUM_QUANTITY_INVALID: "The minimum-stock quantity is invalid.",
          STOCK_MINIMUM_VERSION_CONFLICT: "Minimum stock changed since this page was opened. Refresh and try again.",
          STOCK_MINIMUM_POLICY_INACTIVE: "This product stock policy is currently inactive.",
          STOCK_MINIMUM_EXCEEDS_TARGET: "Minimum stock cannot exceed the current target quantity.",
          STOCK_MINIMUM_IDEMPOTENCY_CONFLICT: "This minimum-stock request conflicts with an earlier request.",
          STOCK_MINIMUM_SCOPE_INVALID: "The selected minimum-stock scope is invalid.",
          STOCK_MINIMUM_BULK_CONFLICT: "Minimum stock could not be applied safely to the entire scope. Review the conflicts first.",
          LIVE_STOCK_PROJECTION_UNAVAILABLE: "Live stock cannot be refreshed right now. Try again shortly.",
          LIVE_STOCK_SEARCH_TOO_SHORT: "Enter at least two characters to search inventory.",
          LIVE_STOCK_FAMILY_SEARCH_TOO_SHORT: "Enter at least two characters to search product families.",
          LIVE_STOCK_ALERT_FILTER_CONFLICT: "Alert-only filtering cannot be combined with another stock state.",
          LIVE_STOCK_FAMILY_INVALID: "The selected product family is invalid.",
          LIVE_STOCK_BATCH_DETAILS_FAILED: "Batch details could not be loaded.",
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
