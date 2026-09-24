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
          "ابحث بالمنتج أو العائلة أو SKU أو الباركود...",
        filters: {
          show: "الفلاتر والفرز",
          hide: "إخفاء الفلاتر",
          clear: "مسح الفلاتر",
          all: "الكل",
          family: "العائلة",
          familySearch:
            "ابحث عن عائلة للفلترة...",
          familyLoadFailed:
            "تعذر تحميل خيارات العائلات. اضغط لإعادة المحاولة.",
          lifecycle: "حالة المنتج",
          trackingType: "نوع التتبع",
          compatibility: "نوع الإعداد",
          barcode: "الباركود",
          price: "السعر",
          lot: "تتبع الدفعات",
          expiry: "تتبع الصلاحية",
          sortBy: "الترتيب حسب",
          sortDirection: "اتجاه الترتيب",
          simple: "مبسط",
          advanced: "متقدم",
          present: "موجود",
          missing: "غير موجود",
          tracked: "مُتتبّع",
          notTracked: "غير مُتتبّع",
          ascending: "تصاعدي",
          descending: "تنازلي",
          trackingTypes: {
            NONE: "بدون تتبع",
            LOT: "دفعات فقط",
            EXPIRY: "صلاحية فقط",
            LOT_EXPIRY: "دفعات وصلاحية",
          },
          sortFields: {
            id: "الأقدم / رقم السجل",
            name: "اسم المنتج",
            family: "العائلة",
            sku: "SKU",
            lifecycle: "حالة المنتج",
          },
        },
        addProduct: "إضافة منتج",
        importFile: "استيراد ملف",
        families: "العائلات",
        advancedPricing: "التسعير المتقدم",
        advancedPricingHint:
          "غير مفعّل حالياً وسيتم تفعيله في مرحلة لاحقة.",
        advancedUom: {
          action: "إدارة وحدات القياس المتقدمة",
          productAction: "إدارة وحدات القياس",
          title: "إدارة وحدات القياس المتقدمة",
          description:
            "استخدم هذه الصفحة فقط للمنتجات التي تحتاج تحويلات UOM تتجاوز المسار المبسط. بنية الوحدات تصبح للقراءة فقط بعد نشر الصنف.",
          back: "العودة إلى المنتجات",
          searchPlaceholder: "ابحث باسم SKU أو رمزه...",
          noAccess: "لا تملك صلاحية قراءة كتالوج المنتجات.",
          variantsLoadFailed: "تعذر تحميل أصناف الكتالوج.",
          noVariants: "لا توجد أصناف مطابقة.",
          selectVariant: "اختر SKU لعرض تحويلات وحدات القياس.",
          variantLoadFailed: "تعذر تحميل الصنف المطلوب.",
          variantNotFound: "الصنف المطلوب غير موجود أو لم يعد متاحاً.",
          baseUom: "وحدة الأساس",
          lockedAfterPublish:
            "تم نشر هذا الصنف، لذلك أصبحت بنية وحدات القياس غير قابلة للتعديل حفاظاً على السجل التشغيلي. يمكنك مراجعة التحويلات فقط.",
          draftEditable:
            "هذا الصنف ما زال مسودة، ويمكن تعديل تحويلات وحدات القياس قبل النشر.",
          readOnly:
            "يمكنك مراجعة التحويلات، لكن تعديلها يتطلب صلاحية إدارة الكتالوج.",
          conversions: "تحويلات وحدات القياس",
          conversionsLoadFailed: "تعذر تحميل تحويلات وحدات القياس.",
          noConversions: "لا توجد تحويلات مسجلة لهذا الصنف.",
          addConversion: "إضافة تحويل",
          editConversion: "تعديل التحويل",
          from: "من وحدة",
          to: "إلى وحدة",
          chooseUom: "اختر وحدة...",
          uomRequired: "اختر وحدة قياس.",
          invalidValue: "أدخل قيمة صالحة.",
          numerator: "البسط",
          denominator: "المقام",
          scale: "دقة الكمية",
          uomsLoadFailed: "تعذر تحميل دليل وحدات القياس.",
          saved: "تم حفظ تحويل وحدة القياس.",
          saveFailed: "تعذر حفظ تحويل وحدة القياس.",
          pendingRetry:
            "نتيجة المحاولة السابقة غير مؤكدة. يجب إعادة إرسال نفس الأمر قبل السماح بتغيير القيم.",
          pendingBlocked:
            "تعذر التحقق من الأمر المعلّق المحفوظ. أوقفت التعديلات لحماية البيانات من التكرار.",
        },
        quickCreate: {
          advancedTitle: "إعدادات متقدمة",
          advancedHint:
            "للباركود أو تخصيص التتبع لهذا المنتج. الإعدادات الأساسية تكفي لمعظم المنتجات.",
          showAdvanced: "عرض الإعدادات",
          hideAdvanced: "إخفاء الإعدادات",
          trackingAdvancedHint:
            "يستخدم المنتج افتراضيات الشركة. افتح الإعدادات المتقدمة فقط إذا احتجت استثناءً لهذا المنتج.",
          systemManagedHint:
            "في الإنشاء السريع يولّد النظام SKU ويطبق دورة النشر المعتمدة تلقائياً. يمكنك مراجعة الهوية والحالة بعد الحفظ من تفاصيل المنتج.",
        },
        emptyTitle: "لا توجد منتجات بعد",
        emptyDescription:
          "أضف منتجاً أو استورد ملفاً.",
        columns: {
          product: "المنتج",
          package: "العبوة",
          unitsPerPackage: "الوحدات / العبوة",
          tracking: "التتبع",
          lifecycle: "حالة المنتج",
          unitBarcode: "باركود الحبة",
          packageBarcode: "باركود العبوة",
          packagePrice: "سعر العبوة",
          unitPrice: "سعر الحبة",
          action: "الإجراء",
        },
        displayPreferences: {
          action: "تخصيص العرض",
          title: "تفضيلات عرض المنتجات",
          userScopedHint:
            "هذه التفضيلات تخص حسابك داخل هذه الشركة فقط، ولا تغيّر بيانات المنتج أو إعدادات الشركة.",
          visibleColumns: "الأعمدة الظاهرة",
          fixedColumnsHint:
            "هوية المنتج والإجراءات الأساسية تبقى ظاهرة دائماً.",
          density: "كثافة الجدول",
          densities: {
            comfortable: "مريح",
            compact: "مضغوط",
          },
          defaultSort: "الفرز الافتراضي",
          detailSections: "أقسام تفاصيل المنتج",
          restoreDefaults: "استعادة الافتراضي",
          saved: "تم حفظ تفضيلات العرض.",
          saveFailed: "تعذر حفظ تفضيلات العرض.",
          columns: {
            package: "العبوة",
            unitsPerPackage: "الوحدات / العبوة",
            tracking: "ملخص التتبع",
            lifecycle: "حالة المنتج",
            unitBarcode: "باركود الحبة",
            packageBarcode: "باركود العبوة",
            packagePrice: "سعر العبوة",
            unitPrice: "سعر الحبة",
          },
          detailSectionsOptions: {
            package: "العبوة ووحدات القياس",
            tracking: "التتبع",
            barcodes: "الباركود",
            pricing: "التسعير",
            compatibility: "التوافق",
          },
        },
        editPrice: "تعديل السعر",
        details: {
          open: "عرض التفاصيل",
          title: "تفاصيل المنتج",
          identity: "هوية المنتج",
          lifecycle: "حالة المنتج",
          operationalHold:
            "الإيقاف التشغيلي",
          lifecycleModes: {
            DRAFT: "مسودة",
            ACTIVE: "نشط",
            RETIRING: "قيد الإيقاف",
            ARCHIVED: "مؤرشف",
          },
          holdModes: {
            NONE: "بدون إيقاف",
            SALES_HOLD: "إيقاف بيع",
            RECALL: "استدعاء",
          },
          package: "العبوة",
          tracking: "التتبع",
          barcodes: "الباركود",
          pricing: "التسعير",
          compatibility: "التوافق",
          simpleCompatible:
            "هذا المنتج متوافق مع مسار المنتجات المبسط ويمكن إدارته من هذه الصفحة.",
          advancedOnly:
            "هذا المنتج يحتوي إعدادات متقدمة؛ اعرض تفاصيله هنا واستخدم الإدارة المتقدمة عند الحاجة للتعديل.",
          notSet: "غير محدد",
        },
        lifecycleManager: {
          action: "إدارة دورة الحياة",
          title:
            "إدارة دورة الحياة — {{name}}",
          loadFailed:
            "تعذر تحميل الحالة التشغيلية الحالية للمنتج.",
        },
        barcodeManager: {
          action: "إدارة الباركود",
          title: "إدارة الباركود — {{name}}",
          current: "الباركودات الحالية",
          none: "لا توجد باركودات مسجلة.",
          add: "إضافة باركود",
          scope: "الوحدة المرتبطة",
          unit: "وحدة الأساس",
          package: "العبوة",
          type: "نوع الباركود",
          types: {
            INTERNAL: "داخلي",
            EAN8: "EAN-8",
            EAN13: "EAN-13",
            UPC_A: "UPC-A",
            GTIN14: "GTIN-14",
            GS1_128: "GS1-128",
          },
          value: "قيمة الباركود",
          makePrimary: "تعيينه باركوداً أساسياً لهذه الوحدة",
          primary: "أساسي",
          inactive: "غير فعال",
          deactivate: "تعطيل",
          save: "إضافة الباركود",
          added: "تمت إضافة الباركود.",
          deactivated: "تم تعطيل الباركود مع الاحتفاظ بسجله.",
          loadMore: "تحميل المزيد",
          pendingRetry:
            "هناك محاولة سابقة نتيجتها غير مؤكدة. الحقول مقفلة حتى تعيد نفس الطلب بأمان.",
          pendingBlocked:
            "تعذر التحقق من الطلب المعلّق المحفوظ. تم إيقاف إنشاء باركود جديد حتى تتم تسوية الطلب بدون مخاطرة التكرار.",
          retryPending: "إعادة إرسال الطلب المعلّق",
          sharedPackageHint:
            "باركود العبوة مرتبط حالياً بباركود وحدة الأساس. إضافة باركود عبوة مستقل تتطلب أولاً تغيير سياسة الباركود من الإدارة المتقدمة.",
          historyHint:
            "لا نحذف تاريخ الباركود. عند الاستبدال عطّل السجل القديم ثم أضف السجل الجديد.",
          loadFailed: "تعذر تحميل باركودات المنتج.",
          saveFailed: "تعذر حفظ تغيير الباركود.",
        },
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
        familySearchPlaceholder: "ابحث عن عائلة...",
        familyPrevious: "السابق",
        familyNext: "التالي",
        variantCount: "{{count}} صنف",
        noFamilies: "لا توجد عائلات بعد.",
        noMatchingFamilies: "لا توجد عائلات مطابقة للبحث.",
        familyPendingRetry:
          "يوجد طلب عائلة سابق لم تُحسم نتيجته. أعد إرسال نفس الطلب لتسويته بأمان.",
        familyPendingBlocked:
          "تعذر التحقق من طلب العائلة المعلّق. تم إيقاف إرسال طلب جديد حتى تتم تسويته بدون مخاطرة التكرار.",
        importTitle: "استيراد المنتجات",
        importIntro:
          "يدعم CSV وExcel. ترتيب الأعمدة لا يهم، وإذا لم نتعرف على عمود لن نخمن؛ سنطلب منك ربطه قبل الاستيراد.",
        importTrackingTitle:
          "تتبع المنتجات في هذا الاستيراد",
        importTrackingHint:
          "سيستخدم هذا الاستيراد افتراضيات شركتك تلقائياً. غيّرها فقط إذا كان هذا الملف يحتاج قاعدة مختلفة.",
        importTrackingSummary:
          "الدفعة / التشغيلة: {{lot}} — الصلاحية: {{expiry}}",
        importTrackingCompanyScope:
          "يستخدم افتراضيات الشركة الحالية.",
        importTrackingCustomScope:
          "تم تخصيص التتبع لهذا الاستيراد فقط.",
        importTrackingChange:
          "تغيير لهذا الاستيراد",
        importTrackingReset:
          "استخدام افتراضيات الشركة",
        importTrackingOnlyThisImport:
          "أي تغيير هنا يخص هذا الاستيراد فقط ولا يغيّر افتراضيات الشركة أو المنتجات الموجودة.",
        importTrackingOverrideHint:
          "إذا ربطت أعمدة تتبع الدفعة أو الصلاحية من الملف، فقيمة الصف غير الفارغة تتقدم على اختيار هذا الاستيراد.",
        importTrackingValueHint:
          "داخل الملف استخدم القيم: {{none}} / {{optional}} / {{required}}. القيم الفارغة تستخدم اختيار هذا الاستيراد.",
        trackingDefaultsLoading:
          "جاري تحميل إعدادات التتبع الافتراضية للشركة...",
        tracking: {
          createTitle: "تتبع الدفعات والصلاحية",
          createHint:
            "يستخدم المنتج افتراضيات شركتك تلقائياً. غيّرها فقط إذا كان هذا المنتج يحتاج طريقة تتبع مختلفة.",
          createSummary:
            "الدفعة / التشغيلة: {{lot}} — الصلاحية: {{expiry}}",
          createCompanyScope:
            "يستخدم افتراضيات الشركة الحالية.",
          createCustomScope:
            "تم تخصيص التتبع لهذا المنتج فقط.",
          createChange:
            "تغيير لهذا المنتج",
          createReset:
            "استخدام افتراضيات الشركة",
          createOnlyThisProduct:
            "أي تغيير هنا يخص هذا المنتج فقط ولا يغيّر افتراضيات الشركة أو المنتجات الأخرى.",
          createDefaultHint:
            "هذا الاختيار يخص المنتج الجديد فقط ولا يغيّر الإعداد الافتراضي لباقي منتجات الشركة.",
          lotLabel: "رقم الدفعة / التشغيلة من المصنع",
          lotHelp:
            "عند استلام هذا المنتج، هل يوجد على العبوة رقم دفعة أو تشغيلة من المصنع وتريد تسجيله؟ هذا الرقم يميز كمية إنتاج عن أخرى عند التتبع أو الاستدعاء.",
          lotModes: {
            NONE: "لا — هذا المنتج لا يعتمد رقم دفعة أو تشغيلة",
            OPTIONAL: "اختياري — سجّله إذا كان موجوداً على المنتج",
            REQUIRED: "إلزامي — يجب تسجيله عند كل توريد",
          },
          importValues: {
            NONE: "لا",
            OPTIONAL: "اختياري",
            REQUIRED: "إلزامي",
          },
          shortLot: "دفعة",
          shortExpiry: "صلاحية",
          shortModes: {
            NONE: "بدون",
            OPTIONAL: "اختياري",
            REQUIRED: "إلزامي",
          },
          lotExample:
            "مثال: قد يصل نفس الشيبس بتشغيلة A123 ثم B456؛ تسجيل الرقم يسمح بتحديد أي كمية جاءت من كل تشغيلة.",
          expiryLabel: "تاريخ انتهاء الصلاحية",
          expiryHelp:
            "عند استلام هذا المنتج، هل يجب تسجيل تاريخ انتهاء الصلاحية حتى يتابع النظام الانتهاء والتنبيهات وقواعد السماح بالبيع؟",
          expiryModes: {
            NONE: "لا — هذا المنتج لا يتطلب تاريخ صلاحية",
            OPTIONAL: "اختياري — سجّله إذا كان موجوداً",
            REQUIRED: "إلزامي — يجب تسجيله عند كل توريد",
          },
          expiryExample:
            "مثال: الأغذية غالباً تحتاج تاريخ صلاحية، بينما قطع الغيار والأدوات قد لا يكون لها تاريخ انتهاء أصلاً.",
        },
        trackingSettings: {
          action: "افتراضيات التتبع",
          title: "افتراضيات تتبع المنتجات الجديدة",
          descriptionTitle: "متى تُستخدم هذه الافتراضيات؟",
          description:
            "تُستخدم كنقطة بداية عند إضافة منتج جديد أو بدء استيراد جديد. لا تغيّر أي منتج موجود، ويمكن تغييرها للمنتج أو الاستيراد نفسه.",
          save: "حفظ افتراضيات الشركة",
          saved: "تم حفظ افتراضيات التتبع للشركة.",
          companySource: "محفوظة للشركة",
          platformSource: "قيمة النظام المبدئية",
          sourceSummary:
            "حالة الإعداد الحالي — الدفعات: {{lot}}، الصلاحية: {{expiry}}.",
        },
        trackingEditor: {
          action: "تعديل التتبع",
          title: "إعدادات تتبع المنتج",
          save: "حفظ إعدادات المنتج",
          saved: "تم تحديث إعدادات تتبع المنتج.",
          warning:
            "هذه الإعدادات تحدد ما سيطلبه النظام عند توريد هذا المنتج مستقبلاً. لا تغيّرها لمجرد تعديل العرض.",
          lockHint:
            "إذا كان للمنتج سجل دفعات سابق، يمنع النظام التغيير العادي حفاظاً على تاريخ المخزون وسلامة التتبع.",
        },
        downloadTemplate: "تحميل النموذج",
        importTemplateSampleName: "شيبس لولو بالجبنة 20غ",
        importTemplateSampleFamily: "شيبس لولو",
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
          sku: "SKU",
          packageUom: "نوع العبوة",
          unitsPerPackage:
            "عدد الحبات داخل العبوة",
          packagePrice: "سعر العبوة",
          unitPrice: "سعر الحبة",
          unitBarcode: "باركود الحبة",
          packageBarcode: "باركود العبوة",
          lotControlMode: "تتبع الدفعات",
          expiryControlMode: "تتبع الصلاحية",
        },
        errors: {
          listLoadTitle: "تعذر تحميل المنتجات",
          listLoadDescription:
            "فشل طلب المنتجات، لذلك لن نعرض حالة فارغة مضللة. تحقق من الاتصال ثم أعد المحاولة.",
          familiesLoad:
            "تعذر تحميل العائلات. أعد المحاولة.",
          packageUomsLoad:
            "تعذر تحميل أنواع العبوات. أعد المحاولة قبل حفظ المنتج.",
          importStatusLoad:
            "تعذر تحديث حالة الاستيراد. سنواصل المحاولة ويمكنك إعادة المحاولة الآن.",
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
          trackingDefaultsLoad:
            "تعذر تحميل إعدادات التتبع الافتراضية للشركة.",
          trackingDefaultsRequired:
            "تعذر تحديد إعدادات التتبع.",
          trackingDefaultsSave:
            "تعذر حفظ إعدادات التتبع الافتراضية.",
          trackingProductRequired:
            "حدد إعدادات تتبع المنتج قبل الحفظ.",
          trackingProductSave:
            "تعذر حفظ إعدادات تتبع المنتج.",
          mappingFailed:
            "تعذر اعتماد ربط الأعمدة.",
          retryFailed:
            "تعذر إعادة عملية الاستيراد.",
        },
      },
      catalogLifecycle: {
        title: "دورة الحياة والإيقاف التشغيلي",
        summary:
          "الحالة: {{lifecycle}} · الإيقاف: {{hold}} · الإصدار: {{version}}",
        reason: "سبب الإجراء",
        reasonPlaceholder:
          "سبب واضح لا يقل عن 3 أحرف",
        preflightPassed:
          "فحص الأرشفة ناجح؛ لا توجد موانع حالية.",
        blockersTitle:
          "الأرشفة متوقفة حتى معالجة الموانع التالية:",
        pendingRetry:
          "هناك أمر سابق ({{action}}) نتيجته غير مؤكدة. يجب إعادة نفس الأمر قبل تنفيذ أمر مختلف.",
        retryPending:
          "إعادة إرسال الأمر المعلّق",
        pendingBlocked:
          "تعذر التحقق من الأمر المعلّق المحفوظ. تم إيقاف أوامر دورة الحياة حتى تتم تسويته بأمان.",
        actions: {
          publish: "نشر",
          deleteDraft: "حذف المسودة",
          retire: "بدء التقاعد",
          restore: "استعادة",
          checkArchive: "فحص الأرشفة",
          archive: "أرشفة نهائية",
          salesHold: "إيقاف بيع",
          releaseSalesHold: "تحرير الإيقاف",
          recall: "استدعاء",
          closeRecall: "إغلاق الاستدعاء",
        },
        success: {
          publish: "تم نشر الصنف.",
          deleteDraft:
            "تم حذف مسودة الصنف.",
          retire:
            "بدأت عملية تقاعد الصنف.",
          restore:
            "تمت استعادة الصنف.",
          archive:
            "تمت أرشفة الصنف.",
          salesHold:
            "تم إيقاف بيع الصنف.",
          releaseSalesHold:
            "تم تحرير إيقاف البيع.",
          recall:
            "تم وضع الصنف تحت الاستدعاء.",
          closeRecall:
            "تم إغلاق استدعاء الصنف.",
        },
        assignments: {
          title:
            "تهيئة الصنف للمستودعات",
          description:
            "الربط لا ينشئ رصيداً أو سياسة مخزون.",
          removeReason:
            "سبب إزالة الربط",
          removeReasonPlaceholder:
            "مطلوب فقط عند إزالة ربط قائم",
          loading:
            "جارٍ تحميل الروابط...",
          empty:
            "الصنف غير مهيأ لأي مستودع.",
          inbound: "استلام",
          outbound: "صرف",
          chooseLocation:
            "اختر مستودعاً...",
          link: "ربط",
          remove:
            "حذف ربط الصنف بالمستودع",
          pendingRetry:
            "هناك أمر ربط سابق ({{action}}) نتيجته غير مؤكدة. أعد نفس الأمر قبل تنفيذ تغيير مختلف.",
          retryPending:
            "إعادة إرسال أمر الربط المعلّق",
          pendingBlocked:
            "تعذر التحقق من أمر الربط المعلّق المحفوظ. تم إيقاف تغييرات الربط حتى تتم تسويته بأمان.",
          actions: {
            create: "إنشاء الربط",
            update: "تحديث الربط",
            delete: "حذف الربط",
          },
          success: {
            create:
              "تم ربط الصنف بالمستودع.",
            update:
              "تم تحديث تشغيل الصنف في المستودع.",
            delete:
              "تم حذف ربط الصنف بالمستودع.",
          },
          errors: {
            load:
              "تعذر جلب روابط الصنف بالمواقع.",
            locationRequired:
              "اختر مستودعاً صالحاً.",
            create:
              "تعذر ربط الصنف بالمستودع.",
            update:
              "تعذر تحديث تشغيل الصنف في المستودع.",
            delete:
              "تعذر حذف ربط الصنف بالمستودع.",
            reason:
              "سبب إزالة الربط مطلوب وبحد أدنى 3 أحرف.",
            pending:
              "تعذر التحقق من أمر الربط المعلّق.",
          },
        },
        errors: {
          action:
            "تعذر تنفيذ أمر دورة الحياة.",
          preflight:
            "تعذر فحص موانع الأرشفة.",
          preflightRequired:
            "نفّذ فحص الأرشفة الحالي قبل الأرشفة النهائية.",
          reason:
            "سبب الإجراء مطلوب وبحد أدنى 3 أحرف.",
        },
        blockers: {
          INVENTORY_BALANCE: "رصيد أو حجز مخزون",
          PRODUCT_LOCATION: "ربط تشغيلي بموقع",
          STOCK_POLICY: "سياسة مخزون فعالة",
          OPEN_TRANSFER: "حوالة مفتوحة",
          ACTIVE_ROUTE_LOAD: "حمولة مسار فعالة",
          OPEN_STOCKTAKE: "جرد مفتوح",
          ACTIVE_INVENTORY_LOCK: "قفل مخزون فعال",
          OPEN_CUSTODY: "عهدة مندوب مفتوحة",
          OPEN_SHORTAGE: "طلب نقص مفتوح",
          ACTIVE_OFFER: "عرض فعال",
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
        loadMoreBatches: "تحميل دفعات إضافية",
        batchCount: "{{count}} دفعة",
        loadedBatchCount: "تم تحميل {{count}} دفعة",
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
        loadingReference: "جارٍ تحميل جميع حركات المرجع...",
        confirmAdjustment: "تأكيد التعديل",
        errors: {
          loadFailed: "تعذر جلب سجل الحركات.",
          referenceDetailsFailed: "تعذر جلب تفاصيل المرجع.",
          receiptNetFailed: "تعذر حساب صافي فاتورة التوريد.",
          adjustmentFailed: "حدث خطأ أثناء التصحيح.",
          adjustmentPermission: "لا تملك صلاحية تصحيح التوريد في هذا المستودع.",
        },
      },
      inventoryWarehouses: {
        processing: "جاري التنفيذ...",
        noChanges: "لا توجد تغييرات لحفظها.",
        errors: {
          loadFailed: "تعذر تحميل إدارة المستودعات.",
          nameInvalid: "اسم المستودع مطلوب وبحد أقصى 150 حرفاً.",
          codeInvalid: "كود المستودع يجب أن يبدأ بحرف أو رقم ويحتوي فقط على A-Z و0-9 و _ و -.",
          systemCodeReserved: "الكود TRANSIT-SYS محجوز للنظام.",
          saveFailed: "تعذر حفظ تغييرات المستودع.",
          stateFailed: "تعذر تغيير حالة المستودع.",
          deactivationReasonRequired: "سبب تعطيل المستودع مطلوب للتدقيق.",
          reasonTooLong: "سبب العملية لا يجوز أن يتجاوز 1000 حرف.",
        },
      },
      inventoryAccessAdmin: {
        saved: "تم حفظ الصلاحيات.",
        errors: {
          loadFailed: "تعذر تحميل بيانات الصلاحيات.",
          saveFailed: "تعذر حفظ الصلاحيات.",
        },
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
          LIVE_STOCK_PROJECTION_NOT_READY: "الرصيد الحي قيد التحديث. أعد المحاولة بعد لحظات.",
          LIVE_STOCK_SEARCH_TOO_SHORT: "أدخل حرفين على الأقل للبحث في المخزون.",
          LIVE_STOCK_FAMILY_SEARCH_TOO_SHORT: "أدخل حرفين على الأقل للبحث في عائلات المنتجات.",
          LIVE_STOCK_ALERT_FILTER_CONFLICT: "لا يمكن دمج فلتر التنبيهات مع حالة رصيد أخرى.",
          LIVE_STOCK_FAMILY_INVALID: "عائلة المنتج المحددة غير صالحة.",
          WAREHOUSE_LOCATION_RESPONSE_INVALID: "استجابة قائمة المستودعات غير صالحة أو غير مكتملة.",
          WAREHOUSE_LOCATION_MUTATION_RESPONSE_INVALID: "استجابة عملية المستودع غير صالحة أو غير مكتملة.",
          INVENTORY_ACCESS_ADMIN_RESPONSE_INVALID: "استجابة إدارة الصلاحيات غير صالحة أو غير مكتملة.",
          LEDGER_REFERENCE_DUPLICATE_MOVEMENT: "تفاصيل المرجع تحتوي حركة مكررة بين الصفحات.",
          LEDGER_REFERENCE_CURSOR_INVALID: "تسلسل صفحات تفاصيل المرجع غير متسق.",
          LEDGER_REFERENCE_TOO_LARGE: "عدد حركات المرجع كبير جداً للعرض المباشر؛ استخدم تقريراً مخصصاً.",
          INVENTORY_ACCESS_RESPONSE_INVALID: "استجابة صلاحيات المخزون غير صالحة أو غير مكتملة.",
          INVENTORY_ACCESS_SCOPE_MISMATCH: "استجابة صلاحيات المخزون لا تطابق الموقع المحدد.",
          INVENTORY_LOCATION_CAPABILITIES_RESPONSE_INVALID: "استجابة صلاحيات المواقع غير صالحة أو غير مكتملة.",
          WAREHOUSE_SETUP_RESPONSE_INVALID: "استجابة حالة إعداد المستودعات غير صالحة أو غير مكتملة.",
          WAREHOUSE_STATUS_RESPONSE_INVALID: "استجابة حالة قفل المستودع غير صالحة أو غير مكتملة.",
          LIVE_STOCK_BATCH_SCOPE_MISMATCH: "تفاصيل الدفعات لا تطابق المستودع أو المنتج المحدد.",
          STOCK_MINIMUM_BULK_RESPONSE_INVALID: "استجابة إدارة الحد الأدنى للمخزون غير صالحة أو غير مكتملة.",
          LIVE_STOCK_BATCH_DETAILS_FAILED: "تعذر تحميل تفاصيل الدفعات.",
          OPERATIONS_RESPONSE_INVALID: "استجابة غرفة العمليات غير صالحة أو غير مكتملة.",
          INBOUND_DUPLICATE_BATCH_UOM_LINE: "لا تكرر نفس المنتج ونفس الدفعة ونفس وحدة الشراء في أكثر من سطر. استخدم سطراً إضافياً فقط لوحدة شراء مختلفة.",
          VALIDATION_ERROR: "بيانات الطلب غير صالحة. راجع الحقول المدخلة.",
          RATE_LIMITED: "تم تجاوز الحد المسموح من الطلبات. حاول مرة أخرى لاحقاً.",
          REQUEST_TOO_LARGE: "حجم الطلب يتجاوز الحد المسموح.",
          INTERNAL_SERVER_ERROR: "حدث خطأ داخلي في الخادم.",
          IDENTITY_NOT_READY: "هوية الشركة أو المستخدم غير جاهزة بعد. حدّث الصفحة وأعد المحاولة.",
          CATALOG_CONTRACT_INVALID: "وصلت بيانات كتالوج غير صالحة أو غير مكتملة.",
          CATALOG_LIFECYCLE_SCOPE_MISMATCH: "استجابة أمر دورة الحياة لا تطابق المنتج المحدد.",
          CATALOG_LIFECYCLE_PREFLIGHT_STALE: "تغير المنتج منذ فحص الأرشفة. حدّث البيانات وأعد الفحص.",
          CATALOG_PRODUCT_LOCATIONS_LIMIT_EXCEEDED: "عدد روابط الصنف تجاوز الحد الآمن للواجهة.",
          CATALOG_PRODUCT_LOCATION_SCOPE_MISMATCH: "استجابة ربط الصنف بالمستودع لا تطابق النطاق المحدد.",
          PRODUCT_LOCATION_NOT_FOUND: "ربط الصنف بالمستودع غير موجود أو لم يعد متاحاً.",
          PRODUCT_LOCATION_TARGET_NOT_FOUND: "المستودع غير موجود أو غير قابل للربط.",
          PRODUCT_LOCATION_VARIANT_NOT_ACTIVE: "يمكن إنشاء ربط جديد لمنتج نشط فقط.",
          PRODUCT_LOCATION_CONFLICT: "تعذر حفظ ربط الصنف بالمستودع بسبب تعارض في البيانات.",
          PRODUCT_LOCATION_VERSION_CONFLICT: "تغير ربط الصنف بالمستودع. حدّث البيانات وأعد المحاولة.",
          PRODUCT_LOCATION_DELETE_BLOCKED: "لا يمكن حذف ربط مستخدم أو مرتبط بسجل تشغيلي.",
          PRODUCT_LOCATION_SCOPE_MISMATCH: "المستودع المرسل لا يطابق ربط الصنف المطلوب.",
          PACKAGE_UOMS_RESPONSE_INVALID: "استجابة وحدات العبوة غير صالحة أو غير مكتملة.",
          PRODUCT_FAMILIES_RESPONSE_INVALID: "استجابة عائلات المنتجات غير صالحة أو غير مكتملة.",
          PRODUCT_BARCODES_RESPONSE_INVALID: "استجابة باركودات المنتج غير صالحة أو غير مكتملة.",
          PRODUCT_BARCODE_MUTATION_RESPONSE_INVALID: "استجابة تعديل الباركود غير صالحة أو غير مكتملة.",
          PRODUCT_BARCODES_SCOPE_MISMATCH: "بيانات الباركود لا تطابق المنتج المحدد.",
          PRODUCT_BARCODES_CURSOR_DUPLICATE: "صفحات الباركود تحتوي سجلاً مكرراً.",
          PRODUCT_IMPORT_ACCEPTED_RESPONSE_INVALID: "استجابة بدء استيراد المنتجات غير صالحة أو غير مكتملة.",
          PRODUCT_IMPORT_COMMAND_RESPONSE_INVALID: "استجابة أمر استيراد المنتجات غير صالحة أو غير مكتملة.",
          PRODUCT_IMPORT_COMMAND_SCOPE_MISMATCH: "استجابة أمر الاستيراد لا تطابق عملية الاستيراد الحالية.",
          PRODUCT_IMPORT_STATE_RESPONSE_INVALID: "استجابة حالة استيراد المنتجات غير صالحة أو غير مكتملة.",
          PRODUCT_IMPORT_ERRORS_RESPONSE_INVALID: "استجابة أخطاء استيراد المنتجات غير صالحة أو غير مكتملة.",
          COMPANY_NOT_FOUND: "الشركة غير موجودة أو غير متاحة.",
          PRODUCT_NOT_FOUND: "المنتج غير موجود أو غير متاح.",
          SIMPLE_PRODUCT_FIELD_REQUIRED: "أحد الحقول المطلوبة للمنتج مفقود.",
          SIMPLE_PRODUCT_FIELD_INVALID: "إحدى قيم المنتج غير صالحة.",
          SIMPLE_PRODUCT_FILTER_INVALID: "أحد فلاتر المنتجات غير صالح.",
          SIMPLE_PRODUCT_SORT_INVALID: "خيار فرز المنتجات غير صالح.",
          SIMPLE_PRODUCT_PRICE_FILTER_FORBIDDEN: "فلترة المنتجات حسب السعر تتطلب صلاحية عرض الأسعار.",
          SIMPLE_PRODUCT_PACKAGE_UOM_UNSUPPORTED: "وحدة العبوة المحددة غير مدعومة في مسار المنتجات المبسط.",
          SIMPLE_PRODUCT_PACKAGING_INVALID: "بيانات تعبئة المنتج غير صالحة.",
          SIMPLE_PRODUCT_NO_PACKAGE_FACTOR_INVALID: "المنتج بدون عبوة خارجية يجب أن يستخدم حبة واحدة كوحدة أساس.",
          SIMPLE_PRODUCT_PACKAGE_PRICE_WITHOUT_PACKAGE: "لا يمكن إدخال سعر عبوة لمنتج لا يملك عبوة خارجية.",
          SIMPLE_PRODUCT_PACKAGE_FACTOR_INVALID: "العبوة الخارجية يجب أن تحتوي وحدتين أساسيتين على الأقل.",
          SIMPLE_PRODUCT_PACKAGE_BARCODE_WITHOUT_PACKAGE: "لا يمكن إضافة باركود عبوة لمنتج بدون عبوة خارجية.",
          SIMPLE_PRODUCT_UOM_MISSING: "بيانات وحدة قياس مطلوبة للمنتج مفقودة.",
          SIMPLE_PRODUCT_UOM_SHAPE_UNSUPPORTED: "تركيب وحدات هذا المنتج متقدم ولا يمكن تعديله بأمان من المسار المبسط.",
          SIMPLE_PRODUCT_EMPTY: "لم يتم تقديم أي منتج للعملية.",
          SIMPLE_PRODUCT_FAMILY_NOT_FOUND: "عائلة المنتج غير موجودة.",
          SIMPLE_PRODUCT_FAMILY_AMBIGUOUS: "اختر عائلة موجودة أو أدخل عائلة جديدة، وليس الاثنين معاً.",
          SIMPLE_PRODUCT_FAMILY_NAME_AMBIGUOUS: "يوجد أكثر من عائلة بالاسم نفسه. اختر العائلة من القائمة.",
          SIMPLE_PRODUCT_FAMILY_CONFLICT: "تعذر حفظ عائلة المنتج بسبب تعارض في البيانات.",
          SIMPLE_PRODUCT_FAMILY_IDEMPOTENCY_CONFLICT: "طلب حفظ العائلة يتعارض مع طلب سابق.",
          SIMPLE_PRODUCT_CONFLICT: "تعذر إنشاء المنتج بسبب تعارض في البيانات.",
          SIMPLE_PRODUCT_PRICE_CONFLICT: "تعذر تحديث السعر بسبب تعارض في البيانات.",
          SIMPLE_PRODUCTS_APPROVAL_MODE_UNSUPPORTED: "مسار المنتجات المبسط غير متاح عند تفعيل مراجعة واعتماد التسعير.",
          SIMPLE_PRODUCTS_ADVANCED_PRICING_ACTIVE: "يوجد تسعير متقدم فعال أو مجدول؛ استخدم مسار التسعير المتقدم.",
          SIMPLE_PRODUCTS_FUTURE_PRICING_ACTIVE: "يوجد تسعير افتراضي مستقبلي مجدول للشركة.",
          SIMPLE_PRODUCTS_MULTIPLE_DEFAULT_PRICES: "يوجد أكثر من تسعير افتراضي فعال للشركة.",
          SIMPLE_PRODUCTS_OFFERS_BLOCKED: "إعداد التسعير الافتراضي الحالي لا يسمح بهذا المسار المبسط.",
          SIMPLE_PRODUCT_DEFAULT_PRICE_BOOK_INVALID: "دفتر الأسعار الافتراضي للشركة غير صالح.",
          SIMPLE_PRODUCT_CURRENCY_MISMATCH: "عملة دفتر الأسعار الافتراضي لا تطابق عملة الشركة.",
          SIMPLE_PRODUCT_DEFAULT_BOOK_CONFLICT: "تعذر إنشاء دفتر أسعار افتراضي آمن للشركة.",
          PRODUCT_IMPORT_FILE_NAME_INVALID: "اسم ملف الاستيراد غير صالح.",
          PRODUCT_IMPORT_MAPPING_NAME_REQUIRED: "يجب ربط عمود باسم المنتج قبل المتابعة.",
          PRODUCT_IMPORT_MAPPING_PRICE_REQUIRED: "يجب ربط عمود سعر واحد على الأقل قبل المتابعة.",
          PRODUCT_IMPORT_MAPPING_CONFLICT: "ربط أعمدة الاستيراد يتعارض مع حالة العملية الحالية.",
          PRODUCT_IMPORT_NOT_FOUND: "عملية استيراد المنتجات غير موجودة أو غير متاحة.",
          PRODUCT_IMPORT_NOT_RETRYABLE: "عملية الاستيراد الحالية لا يمكن إعادة محاولتها.",
          PRODUCT_IMPORT_QUEUE_UNAVAILABLE: "خدمة استيراد المنتجات غير متاحة حالياً. أعد المحاولة لاحقاً.",
          INVALID_CURSOR: "مؤشر الصفحة غير صالح أو لا يطابق نطاق الطلب الحالي.",
          IDEMPOTENCY_CONFLICT: "رقم العملية مستخدم لطلب مختلف.",
          VARIANT_NOT_FOUND: "الصنف المحدد غير موجود أو غير متاح.",
          VARIANT_VERSION_CONFLICT: "تغير الصنف منذ فتحه. حدّث البيانات وأعد المحاولة.",
          VARIANT_STRUCTURE_LOCKED: "لا يمكن تعديل بنية الصنف بعد خروجه من حالة المسودة.",
          VARIANT_IDENTITY_CONFLICT: "هوية الصنف أو SKU/GTIN مستخدمة مسبقاً.",
          VARIANT_CONFLICT: "تعذر تعديل الصنف بسبب تعارض في البيانات.",
          UOM_NOT_FOUND: "وحدة القياس المحددة غير موجودة.",
          UOM_STRUCTURE_LOCKED: "تحويلات وحدات القياس قابلة للتعديل في حالة المسودة فقط.",
          UOM_CONVERSION_CONFLICT: "تحويل وحدة القياس موجود مسبقاً أو يتعارض مع تحويل آخر.",
          UOM_CONVERSION_NOT_FOUND: "تحويل وحدة القياس غير موجود.",
          UOM_CONVERSION_VERSION_CONFLICT: "تغير تحويل وحدة القياس منذ فتحه. حدّث البيانات وأعد المحاولة.",
          BARCODE_NOT_FOUND: "الباركود غير موجود.",
          BARCODE_VERSION_CONFLICT: "تغير الباركود منذ فتحه. حدّث البيانات وأعد المحاولة.",
          BARCODE_VALIDITY_INVALID: "فترة صلاحية الباركود غير صالحة.",
          BARCODE_CONFLICT: "الباركود الفعال أو الأساسي يتعارض مع سجل آخر.",
          GS1_INVALID: "قيمة GS1 غير صالحة.",
          PRODUCT_CODE_CONFLICT: "كود المنتج مستخدم مسبقاً.",
          PRODUCT_STATE_CONFLICT: "حالة المنتج تغيرت أو تتعارض مع العملية المطلوبة.",
          PRODUCT_VERSION_CONFLICT: "تغير المنتج منذ فتحه. حدّث البيانات وأعد المحاولة.",
          PRODUCT_PUBLISH_READINESS_FAILED: "المنتج غير جاهز للنشر. أكمل البيانات المطلوبة أولاً.",
          PRODUCT_PUBLISH_TRANSITION_INVALID: "لا يمكن نشر المنتج من حالته الحالية.",
          PRODUCT_STATE_INVALID: "حالة المنتج غير صالحة.",
          PRODUCT_RETIRE_TRANSITION_INVALID: "لا يمكن بدء إيقاف المنتج من حالته الحالية.",
          PRODUCT_RESTORE_TRANSITION_INVALID: "لا يمكن استعادة المنتج من حالته الحالية.",
          PRODUCT_RESTORE_READINESS_FAILED: "المنتج غير جاهز للاستعادة إلى الحالة الفعالة.",
          PRODUCT_ARCHIVE_TRANSITION_INVALID: "لا يمكن أرشفة المنتج من حالته الحالية.",
          PRODUCT_ARCHIVE_BLOCKED: "لا يمكن أرشفة المنتج قبل معالجة الموانع الحالية.",
          PRODUCT_HOLD_OPEN: "يوجد إيقاف تشغيلي مفتوح يجب معالجته أولاً.",
          PRODUCT_RECALL_OPEN: "يوجد استدعاء منتج مفتوح يجب معالجته أولاً.",
          PRODUCT_RECALL_COMPLETION_REQUIRED: "يجب إكمال متطلبات الاستدعاء قبل متابعة العملية.",
          PRODUCT_RECALL_TRANSITION_INVALID: "لا يمكن إصدار استدعاء للمنتج من حالته الحالية.",
          PRODUCT_RECALL_CLOSE_INVALID: "لا يوجد استدعاء مفتوح يمكن إغلاقه.",
          PRODUCT_SALES_HOLD_TRANSITION_INVALID: "لا يمكن إيقاف بيع المنتج من حالته الحالية.",
          PRODUCT_SALES_HOLD_RELEASE_INVALID: "لا يوجد إيقاف بيع يمكن تحريره.",
          PRODUCT_DRAFT_DELETE_BLOCKED: "لا يمكن حذف المسودة قبل معالجة الارتباطات أو الموانع الحالية.",
          PRODUCT_DELETE_DRAFT_TRANSITION_INVALID: "حذف المنتج متاح للمسودة فقط.",
          PRODUCT_TRACKING_MODE_INVALID: "إعداد تتبع الدفعة أو الصلاحية غير صالح.",
          PRODUCT_TRACKING_ID_INVALID: "هوية المنتج المستخدمة لتعديل التتبع غير صالحة.",
          PRODUCT_TRACKING_DATE_INVALID: "تاريخ التتبع غير صالح.",
          PRODUCT_TRACKING_INTERNAL_BATCH_INVALID: "هوية الدفعة الداخلية غير صالحة.",
          LIVE_STOCK_PROJECTION_FAILED: "تعذر تحديث إسقاط الرصيد الحي بعد العملية.",
          PRICE_AMOUNT_INVALID: "قيمة السعر غير صالحة.",
          PRICE_NOT_RESOLVED: "تعذر تحديد سعر فعال لهذا المنتج.",
          PRICE_PRECISION_UNSUPPORTED: "دقة السعر المطلوبة غير مدعومة.",
          PRICE_BOOK_NOT_FOUND: "دفتر الأسعار غير موجود.",
          PRICE_BOOK_INACTIVE: "دفتر الأسعار غير فعال.",
          PRICE_BOOK_VERSION_CONFLICT: "تغير دفتر الأسعار. حدّث البيانات وأعد المحاولة.",
          PRICE_ENTRY_NOT_FOUND: "سجل السعر غير موجود.",
          PRICE_ENTRY_VERSION_CONFLICT: "تغير سجل السعر. حدّث البيانات وأعد المحاولة.",
          PRICE_ENTRY_IMMUTABLE: "لا يمكن تعديل سجل سعر منشور مباشرة.",
          PRICE_EFFECTIVITY_INVALID: "فترة فعالية السعر غير صالحة.",
          PRICE_EFFECTIVITY_CONFLICT: "فترة فعالية السعر تتعارض مع سعر آخر.",
          PRICE_EFFECTIVITY_BEFORE_PUBLICATION: "لا يمكن أن يبدأ السعر قبل نشره.",
          PRICE_VARIANT_NOT_FOUND: "الصنف المطلوب للتسعير غير موجود.",
          PRICE_UOM_MAPPING_UNRESOLVED: "تعذر ربط وحدة السعر بوحدة المنتج.",
          PRICE_UOM_MAPPING_AMBIGUOUS: "يوجد أكثر من ربط محتمل لوحدة السعر.",
          PRICE_ASSIGNMENT_SCOPE_INVALID: "نطاق تعيين السعر غير صالح.",
          PRICE_ASSIGNMENT_SCOPE_NOT_FOUND: "نطاق تعيين السعر غير موجود.",
          PRICE_ASSIGNMENT_SCOPE_RESERVED: "نطاق تعيين السعر محجوز ولا يمكن استخدامه هنا.",
          PRICE_ASSIGNMENT_TIE: "يوجد أكثر من سعر بنفس أولوية المطابقة.",
          PRICE_BRANCH_NOT_FOUND: "الفرع المحدد للتسعير غير موجود.",
          PRICE_CUSTOMER_NOT_FOUND: "العميل المحدد للتسعير غير موجود.",
          COMMERCIAL_CONTEXT_LOCKED: "السياق التجاري مقفل ولا يمكن تغييره أثناء هذه العملية.",
          PRICE_RESOLVE_INPUT_INVALID: "مدخلات احتساب السعر غير صالحة.",
          PRICE_PUBLICATION_NOT_FOUND: "نشرة الأسعار غير موجودة.",
          PRICE_PUBLICATION_NOT_EDITABLE: "نشرة الأسعار لم تعد قابلة للتعديل.",
          PRICE_PUBLICATION_STATE_CONFLICT: "حالة نشرة الأسعار لا تسمح بهذه العملية.",
          PRICE_PUBLICATION_VERSION_CONFLICT: "تغيرت نشرة الأسعار. حدّث البيانات وأعد المحاولة.",
          PRICE_PUBLICATION_EMPTY: "لا يمكن نشر قائمة أسعار فارغة.",
          PRICE_PUBLICATION_EFFECTIVE_AT_REQUIRED: "تاريخ بدء فعالية الأسعار مطلوب.",
          PRICING_APPROVAL_POLICY_INVALID: "إعداد مراجعة واعتماد التسعير غير صالح.",
          PRICING_APPROVAL_NOT_ENABLED: "مراجعة واعتماد التسعير غير مفعلة.",
          PRICING_APPROVAL_REQUIRED: "هذه العملية تحتاج اعتماداً قبل التنفيذ.",
          PRICING_DATETIME_OFFSET_REQUIRED: "تاريخ التسعير يجب أن يتضمن المنطقة الزمنية.",
          PRICING_SEPARATION_OF_DUTIES: "سياسة فصل الصلاحيات تمنع نفس المستخدم من تنفيذ المرحلتين.",
          TENANT_NOT_FOUND: "الشركة غير موجودة أو غير متاحة.",
          PRODUCT_NOT_OPERATIONAL: "المنتج غير متاح تشغيلياً حالياً.",
          SIMPLE_PRODUCTS_RESPONSE_INVALID: "استجابة قائمة المنتجات غير صالحة أو غير مكتملة.",
          SIMPLE_PRODUCT_CREATE_RESPONSE_INVALID: "استجابة إنشاء المنتج غير صالحة أو غير مكتملة.",
          SIMPLE_PRODUCT_PRICE_RESPONSE_INVALID: "استجابة تحديث سعر المنتج غير صالحة أو غير مكتملة.",
          SIMPLE_PRODUCT_PRICE_SCOPE_MISMATCH: "استجابة تحديث السعر لا تطابق المنتج المحدد.",
          PRODUCT_TRACKING_DEFAULTS_RESPONSE_INVALID: "استجابة إعدادات تتبع المنتجات غير صالحة.",
          PRODUCT_TRACKING_MUTATION_RESPONSE_INVALID: "استجابة تعديل تتبع المنتج غير صالحة.",
          PRODUCT_TRACKING_LOCKED: "لا يمكن تغيير إعدادات التتبع بالطريقة العادية لأن للمنتج سجل دفعات سابقاً. استخدم مسار ترحيل معتمد إذا كان التغيير ضرورياً.",
          PRODUCT_TRACKING_VERSION_CONFLICT: "تم تعديل المنتج منذ فتحه. حدّث قائمة المنتجات ثم أعد المحاولة.",
          PRODUCT_TRACKING_LIFECYCLE_BLOCKED: "لا يمكن تعديل إعدادات التتبع لمنتج قيد الإيقاف أو مؤرشف.",
          PRODUCT_TRACKING_VARIANT_NOT_FOUND: "المنتج غير موجود أو لا يتبع هذه الشركة.",
          PRODUCT_TRACKING_DEFAULTS_CONFLICT: "تعذر حفظ إعدادات التتبع الافتراضية بسبب تعارض في البيانات.",
          PRODUCT_TRACKING_CONFLICT: "تعذر حفظ إعدادات تتبع المنتج بسبب تعارض في البيانات.",
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
          DURABLE_OPERATION_PENDING:
            "يوجد طلب سابق لنفس العملية لم تُحسم نتيجته بعد. أعد نفس الطلب أو أكمل تسويته قبل إرسال طلب مختلف.",
          DURABLE_OPERATION_CORRUPT:
            "تعذر التحقق من الطلب المعلّق المحفوظ على هذا الجهاز. أُوقفت العملية لحمايتها من التكرار حتى تتم تسويتها.",
          PRODUCT_FAMILY_MUTATION_RESPONSE_INVALID:
            "تم استلام رد غير متوقع بعد حفظ العائلة. أُبقي الطلب معلّقاً لمنع تكرار العملية حتى تتم تسويته.",
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
          IMPORT_NAME_TOO_LONG:
            "اسم المنتج أطول من الحد المسموح.",
          IMPORT_PACKAGE_BARCODE_WITHOUT_PACKAGE:
            "لا يمكن إضافة باركود عبوة لمنتج بدون عبوة خارجية.",
          IMPORT_ROW_INVALID:
            "بيانات الصف غير صالحة للاستيراد.",
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
          "Search by product, family, SKU, or barcode...",
        filters: {
          show: "Filters & sorting",
          hide: "Hide filters",
          clear: "Clear filters",
          all: "All",
          family: "Family",
          familySearch:
            "Search families to filter...",
          familyLoadFailed:
            "Could not load family options. Click to retry.",
          lifecycle: "Product status",
          trackingType: "Tracking type",
          compatibility: "Configuration type",
          barcode: "Barcode",
          price: "Price",
          lot: "Lot tracking",
          expiry: "Expiry tracking",
          sortBy: "Sort by",
          sortDirection: "Sort direction",
          simple: "Simple",
          advanced: "Advanced",
          present: "Present",
          missing: "Missing",
          tracked: "Tracked",
          notTracked: "Not tracked",
          ascending: "Ascending",
          descending: "Descending",
          trackingTypes: {
            NONE: "No tracking",
            LOT: "Lot only",
            EXPIRY: "Expiry only",
            LOT_EXPIRY: "Lot and expiry",
          },
          sortFields: {
            id: "Oldest / record ID",
            name: "Product name",
            family: "Family",
            sku: "SKU",
            lifecycle: "Product status",
          },
        },
        addProduct: "Add product",
        importFile: "Import file",
        families: "Families",
        advancedPricing: "Advanced pricing",
        advancedPricingHint:
          "Not enabled yet. It will be activated in a later stage.",
        advancedUom: {
          action: "Advanced UOM management",
          productAction: "Manage units of measure",
          title: "Advanced units of measure",
          description:
            "Use this page only for products that need UOM conversions beyond the simple product flow. Unit structure becomes read-only after the SKU is published.",
          back: "Back to products",
          searchPlaceholder: "Search by SKU name or code...",
          noAccess: "You do not have permission to read the product catalog.",
          variantsLoadFailed: "Could not load catalog SKUs.",
          noVariants: "No matching SKUs.",
          selectVariant: "Select a SKU to review its UOM conversions.",
          variantLoadFailed: "Could not load the selected SKU.",
          variantNotFound: "The selected SKU does not exist or is no longer available.",
          baseUom: "Base unit",
          lockedAfterPublish:
            "This SKU has been published, so its unit structure is locked to protect operational history. You can still review the conversions.",
          draftEditable:
            "This SKU is still a draft, so its UOM conversions can be edited before publication.",
          readOnly:
            "You can review conversions, but catalog management permission is required to change them.",
          conversions: "UOM conversions",
          conversionsLoadFailed: "Could not load UOM conversions.",
          noConversions: "No conversions are registered for this SKU.",
          addConversion: "Add conversion",
          editConversion: "Edit conversion",
          from: "From unit",
          to: "To unit",
          chooseUom: "Choose a unit...",
          uomRequired: "Choose a unit of measure.",
          invalidValue: "Enter a valid value.",
          numerator: "Numerator",
          denominator: "Denominator",
          scale: "Quantity scale",
          uomsLoadFailed: "Could not load the UOM catalog.",
          saved: "UOM conversion saved.",
          saveFailed: "Could not save the UOM conversion.",
          pendingRetry:
            "The previous attempt has an unknown outcome. The exact same command must be retried before values can change.",
          pendingBlocked:
            "The saved pending command could not be verified. Editing is blocked to prevent duplicate or conflicting changes.",
        },
        quickCreate: {
          advancedTitle: "Advanced settings",
          advancedHint:
            "Use these for barcodes or a product-specific tracking override. The basic fields are enough for most products.",
          showAdvanced: "Show settings",
          hideAdvanced: "Hide settings",
          trackingAdvancedHint:
            "This product uses the company defaults. Open Advanced settings only when this product needs an exception.",
          systemManagedHint:
            "Quick Create generates the SKU and applies the approved publish lifecycle automatically. Review identity and status from Product details after saving.",
        },
        emptyTitle: "No products yet",
        emptyDescription:
          "Add a product or import a file.",
        columns: {
          product: "Product",
          package: "Package",
          unitsPerPackage:
            "Units / package",
          tracking: "Tracking",
          lifecycle: "Product status",
          unitBarcode: "Unit barcode",
          packageBarcode: "Package barcode",
          packagePrice: "Package price",
          unitPrice: "Unit price",
          action: "Action",
        },
        displayPreferences: {
          action: "Customize view",
          title: "Product display preferences",
          userScopedHint:
            "These preferences apply only to your account in this company. They do not change product data or company settings.",
          visibleColumns: "Visible columns",
          fixedColumnsHint:
            "Product identity and core actions always remain visible.",
          density: "Table density",
          densities: {
            comfortable: "Comfortable",
            compact: "Compact",
          },
          defaultSort: "Default sort",
          detailSections: "Product detail sections",
          restoreDefaults: "Restore defaults",
          saved: "Display preferences saved.",
          saveFailed: "Could not save display preferences.",
          columns: {
            package: "Package",
            unitsPerPackage: "Units / package",
            tracking: "Tracking summary",
            lifecycle: "Product status",
            unitBarcode: "Unit barcode",
            packageBarcode: "Package barcode",
            packagePrice: "Package price",
            unitPrice: "Unit price",
          },
          detailSectionsOptions: {
            package: "Packaging and UOM",
            tracking: "Tracking",
            barcodes: "Barcodes",
            pricing: "Pricing",
            compatibility: "Compatibility",
          },
        },
        editPrice: "Edit price",
        details: {
          open: "View details",
          title: "Product details",
          identity: "Product identity",
          lifecycle: "Product status",
          operationalHold:
            "Operational hold",
          lifecycleModes: {
            DRAFT: "Draft",
            ACTIVE: "Active",
            RETIRING: "Retiring",
            ARCHIVED: "Archived",
          },
          holdModes: {
            NONE: "No hold",
            SALES_HOLD: "Sales hold",
            RECALL: "Recall",
          },
          package: "Packaging",
          tracking: "Tracking",
          barcodes: "Barcodes",
          pricing: "Pricing",
          compatibility: "Compatibility",
          simpleCompatible:
            "This product is compatible with the simple product workflow and can be managed from this page.",
          advancedOnly:
            "This product has advanced settings; review its details here and use advanced management when an edit is required.",
          notSet: "Not set",
        },
        lifecycleManager: {
          action: "Manage lifecycle",
          title:
            "Manage lifecycle — {{name}}",
          loadFailed:
            "Could not load the product's current operational state.",
        },
        barcodeManager: {
          action: "Manage barcodes",
          title: "Manage barcodes — {{name}}",
          current: "Current barcodes",
          none: "No barcodes are registered.",
          add: "Add barcode",
          scope: "Associated unit",
          unit: "Base unit",
          package: "Package",
          type: "Barcode type",
          types: {
            INTERNAL: "Internal",
            EAN8: "EAN-8",
            EAN13: "EAN-13",
            UPC_A: "UPC-A",
            GTIN14: "GTIN-14",
            GS1_128: "GS1-128",
          },
          value: "Barcode value",
          makePrimary: "Make this the primary barcode for the unit",
          primary: "Primary",
          inactive: "Inactive",
          deactivate: "Deactivate",
          save: "Add barcode",
          added: "Barcode added.",
          deactivated: "Barcode deactivated and its history was preserved.",
          loadMore: "Load more",
          pendingRetry:
            "A previous attempt has an unknown outcome. Fields are locked until the same command is retried safely.",
          pendingBlocked:
            "The saved pending command could not be verified. New barcode creation is blocked until the command is safely reconciled.",
          retryPending: "Retry pending command",
          sharedPackageHint:
            "The package barcode currently shares the base-unit barcode. A distinct package barcode requires changing the barcode policy in advanced management first.",
          historyHint:
            "Barcode history is preserved. To replace a barcode, deactivate the old record and add a new one.",
          loadFailed: "Could not load product barcodes.",
          saveFailed: "Could not save the barcode change.",
        },
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
        familySearchPlaceholder: "Search families...",
        familyPrevious: "Previous",
        familyNext: "Next",
        variantCount: "{{count}} variants",
        noFamilies: "No families yet.",
        noMatchingFamilies: "No families match this search.",
        familyPendingRetry:
          "A previous family request has an unknown outcome. Retry the exact same request to reconcile it safely.",
        familyPendingBlocked:
          "The pending family request could not be verified. New submission is blocked until it can be reconciled without duplication risk.",
        importTitle: "Import products",
        importIntro:
          "CSV and Excel are supported. Column order does not matter; unclear columns are never guessed and will be mapped before import.",
        importTrackingTitle:
          "Tracking for this import",
        importTrackingHint:
          "This import uses your company defaults automatically. Change them only when this file needs different tracking rules.",
        importTrackingSummary:
          "Batch / lot: {{lot}} — expiry: {{expiry}}",
        importTrackingCompanyScope:
          "Using the current company defaults.",
        importTrackingCustomScope:
          "Tracking is customized for this import only.",
        importTrackingChange:
          "Change for this import",
        importTrackingReset:
          "Use company defaults",
        importTrackingOnlyThisImport:
          "Changes here apply only to this import and do not change company defaults or existing products.",
        importTrackingOverrideHint:
          "When lot or expiry tracking columns are mapped, a non-empty row value overrides this import selection.",
        importTrackingValueHint:
          "Inside the file use: {{none}} / {{optional}} / {{required}}. Blank values use this import selection.",
        trackingDefaultsLoading:
          "Loading company tracking defaults...",
        tracking: {
          createTitle: "Batch and expiry tracking",
          createHint:
            "This product uses your company defaults automatically. Change them only when this product needs different tracking rules.",
          createSummary:
            "Batch / lot: {{lot}} — expiry: {{expiry}}",
          createCompanyScope:
            "Using the current company defaults.",
          createCustomScope:
            "Tracking is customized for this product only.",
          createChange:
            "Change for this product",
          createReset:
            "Use company defaults",
          createOnlyThisProduct:
            "Changes here apply only to this product and do not change company defaults or other products.",
          createDefaultHint:
            "This choice applies only to the new product and does not change the company default for other products.",
          lotLabel: "Manufacturer batch / lot number",
          lotHelp:
            "When this product is received, is there a manufacturer batch or lot number on the package that staff should record? It distinguishes one production run from another for traceability or recalls.",
          lotModes: {
            NONE: "No — this product does not use a batch or lot number",
            OPTIONAL: "Optional — record it when it appears on the product",
            REQUIRED: "Required — record it on every receipt",
          },
          importValues: {
            NONE: "No",
            OPTIONAL: "Optional",
            REQUIRED: "Required",
          },
          shortLot: "Lot",
          shortExpiry: "Expiry",
          shortModes: {
            NONE: "None",
            OPTIONAL: "Optional",
            REQUIRED: "Required",
          },
          lotExample:
            "Example: the same chips may arrive as lot A123 and later as lot B456; recording the lot identifies which quantity came from each run.",
          expiryLabel: "Expiry date",
          expiryHelp:
            "When this product is received, should staff record its expiry date so the system can track expiration, alerts, and sellability rules?",
          expiryModes: {
            NONE: "No — this product does not require an expiry date",
            OPTIONAL: "Optional — record it when available",
            REQUIRED: "Required — record it on every receipt",
          },
          expiryExample:
            "Example: food often needs expiry tracking, while spare parts and tools may have no expiry date at all.",
        },
        trackingSettings: {
          action: "Tracking defaults",
          title: "Defaults for new products",
          descriptionTitle: "When are these defaults used?",
          description:
            "They are the starting point when adding a new product or starting a new import. They do not change existing products, and each product or import can override them.",
          save: "Save company defaults",
          saved: "Company tracking defaults saved.",
          companySource: "Saved for company",
          platformSource: "Initial system value",
          sourceSummary:
            "Current setting status — batches: {{lot}}, expiry: {{expiry}}.",
        },
        trackingEditor: {
          action: "Edit tracking",
          title: "Product tracking settings",
          save: "Save product settings",
          saved: "Product tracking settings updated.",
          warning:
            "These settings control what the system will require when this product is received in the future. Do not change them just to alter how the page looks.",
          lockHint:
            "If the product already has batch history, the normal edit is blocked to protect inventory history and traceability.",
        },
        downloadTemplate: "Download template",
        importTemplateSampleName: "Lolo Chips Cheese 20g",
        importTemplateSampleFamily: "Lolo Chips",
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
          sku: "SKU",
          packageUom: "Package type",
          unitsPerPackage:
            "Units inside package",
          packagePrice: "Package price",
          unitPrice: "Unit price",
          unitBarcode: "Unit barcode",
          packageBarcode: "Package barcode",
          lotControlMode: "Batch / lot tracking",
          expiryControlMode: "Expiry tracking",
        },
        errors: {
          listLoadTitle: "Products could not be loaded",
          listLoadDescription:
            "The products request failed, so an empty catalog is not shown. Check the connection and try again.",
          familiesLoad:
            "Could not load families. Try again.",
          packageUomsLoad:
            "Could not load package types. Retry before saving the product.",
          importStatusLoad:
            "Could not refresh the import status. Automatic retries will continue, or retry now.",
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
          trackingDefaultsLoad:
            "Could not load the company tracking defaults.",
          trackingDefaultsRequired:
            "Tracking settings could not be resolved.",
          trackingDefaultsSave:
            "Could not save the default tracking settings.",
          trackingProductRequired:
            "Choose the product tracking settings before saving.",
          trackingProductSave:
            "Could not save the product tracking settings.",
          mappingFailed:
            "Could not save the column mapping.",
          retryFailed:
            "Could not retry the import.",
        },
      },
      catalogLifecycle: {
        title: "Lifecycle and operational hold",
        summary:
          "Status: {{lifecycle}} · Hold: {{hold}} · Version: {{version}}",
        reason: "Reason",
        reasonPlaceholder:
          "Provide a clear reason of at least 3 characters",
        preflightPassed:
          "Archive preflight passed; no blockers remain.",
        blockersTitle:
          "Archiving is blocked until these dependencies are resolved:",
        pendingRetry:
          "A previous {{action}} command has an unknown outcome. Retry the same command before sending a different lifecycle action.",
        retryPending:
          "Retry pending command",
        pendingBlocked:
          "The saved pending lifecycle command could not be verified. Lifecycle actions are blocked until it is safely reconciled.",
        actions: {
          publish: "Publish",
          deleteDraft: "Delete draft",
          retire: "Start retirement",
          restore: "Restore",
          checkArchive: "Check archive",
          archive: "Archive",
          salesHold: "Sales hold",
          releaseSalesHold: "Release hold",
          recall: "Recall",
          closeRecall: "Close recall",
        },
        success: {
          publish: "Product published.",
          deleteDraft:
            "Draft product deleted.",
          retire:
            "Product retirement started.",
          restore:
            "Product restored.",
          archive:
            "Product archived.",
          salesHold:
            "Product sales placed on hold.",
          releaseSalesHold:
            "Product sales hold released.",
          recall:
            "Product placed under recall.",
          closeRecall:
            "Product recall closed.",
        },
        assignments: {
          title:
            "Warehouse product setup",
          description:
            "This assignment does not create stock or a stock policy.",
          removeReason:
            "Removal reason",
          removeReasonPlaceholder:
            "Required only when removing an existing assignment",
          loading:
            "Loading assignments...",
          empty:
            "This product is not assigned to any warehouse.",
          inbound: "Inbound",
          outbound: "Outbound",
          chooseLocation:
            "Choose a warehouse...",
          link: "Assign",
          remove:
            "Remove warehouse product assignment",
          pendingRetry:
            "A previous assignment command ({{action}}) has an unknown outcome. Retry the same command before making a different change.",
          retryPending:
            "Retry pending assignment command",
          pendingBlocked:
            "The saved pending assignment command could not be verified. Assignment changes are blocked until it is safely reconciled.",
          actions: {
            create: "Create assignment",
            update: "Update assignment",
            delete: "Delete assignment",
          },
          success: {
            create:
              "Product assigned to the warehouse.",
            update:
              "Warehouse product operation settings updated.",
            delete:
              "Warehouse product assignment removed.",
          },
          errors: {
            load:
              "Could not load product-location assignments.",
            locationRequired:
              "Choose a valid warehouse.",
            create:
              "Could not assign the product to the warehouse.",
            update:
              "Could not update warehouse product operation settings.",
            delete:
              "Could not remove the warehouse product assignment.",
            reason:
              "A removal reason of at least 3 characters is required.",
            pending:
              "Could not verify the saved pending assignment command.",
          },
        },
        errors: {
          action:
            "Could not complete the lifecycle action.",
          preflight:
            "Could not check archive blockers.",
          preflightRequired:
            "Run a current archive preflight before archiving.",
          reason:
            "A reason of at least 3 characters is required.",
        },
        blockers: {
          INVENTORY_BALANCE: "Inventory balance or reservation",
          PRODUCT_LOCATION: "Operational location assignment",
          STOCK_POLICY: "Active stock policy",
          OPEN_TRANSFER: "Open transfer",
          ACTIVE_ROUTE_LOAD: "Active route load",
          OPEN_STOCKTAKE: "Open stocktake",
          ACTIVE_INVENTORY_LOCK: "Active inventory lock",
          OPEN_CUSTODY: "Open driver custody",
          OPEN_SHORTAGE: "Open shortage request",
          ACTIVE_OFFER: "Active offer",
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
        loadMoreBatches: "Load more batches",
        batchCount: "{{count}} batches",
        loadedBatchCount: "{{count}} batches loaded",
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
        loadingReference: "Loading all movements for this reference...",
        confirmAdjustment: "Confirm adjustment",
        errors: {
          loadFailed: "Could not load the movement ledger.",
          referenceDetailsFailed: "Could not load reference details.",
          receiptNetFailed: "Could not calculate the receipt net quantity.",
          adjustmentFailed: "An error occurred while applying the adjustment.",
          adjustmentPermission: "You do not have permission to adjust inbound receipts in this warehouse.",
        },
      },
      inventoryWarehouses: {
        processing: "Processing...",
        noChanges: "There are no changes to save.",
        errors: {
          loadFailed: "Could not load warehouse management.",
          nameInvalid: "Warehouse name is required and must be at most 150 characters.",
          codeInvalid: "Warehouse code must start with a letter or number and contain only A-Z, 0-9, _ and -.",
          systemCodeReserved: "TRANSIT-SYS is reserved for the system.",
          saveFailed: "Could not save warehouse changes.",
          stateFailed: "Could not change warehouse status.",
          deactivationReasonRequired: "A deactivation reason is required for audit purposes.",
          reasonTooLong: "The operation reason must not exceed 1000 characters.",
        },
      },
      inventoryAccessAdmin: {
        saved: "Permissions were saved.",
        errors: {
          loadFailed: "Could not load permission data.",
          saveFailed: "Could not save permissions.",
        },
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
          LIVE_STOCK_PROJECTION_NOT_READY: "Live stock is being refreshed. Try again in a moment.",
          LIVE_STOCK_SEARCH_TOO_SHORT: "Enter at least two characters to search inventory.",
          LIVE_STOCK_FAMILY_SEARCH_TOO_SHORT: "Enter at least two characters to search product families.",
          LIVE_STOCK_ALERT_FILTER_CONFLICT: "Alert-only filtering cannot be combined with another stock state.",
          LIVE_STOCK_FAMILY_INVALID: "The selected product family is invalid.",
          WAREHOUSE_LOCATION_RESPONSE_INVALID: "The warehouse-list response is invalid or incomplete.",
          WAREHOUSE_LOCATION_MUTATION_RESPONSE_INVALID: "The warehouse-operation response is invalid or incomplete.",
          INVENTORY_ACCESS_ADMIN_RESPONSE_INVALID: "The permission-management response is invalid or incomplete.",
          LEDGER_REFERENCE_DUPLICATE_MOVEMENT: "Reference details contain a duplicated movement across pages.",
          LEDGER_REFERENCE_CURSOR_INVALID: "Reference-detail pagination is inconsistent.",
          LEDGER_REFERENCE_TOO_LARGE: "This reference contains too many movements for direct display; use a dedicated report.",
          INVENTORY_ACCESS_RESPONSE_INVALID: "The inventory-permissions response is invalid or incomplete.",
          INVENTORY_ACCESS_SCOPE_MISMATCH: "The inventory-permissions response does not match the selected location.",
          INVENTORY_LOCATION_CAPABILITIES_RESPONSE_INVALID: "The location-capabilities response is invalid or incomplete.",
          WAREHOUSE_SETUP_RESPONSE_INVALID: "The warehouse-setup response is invalid or incomplete.",
          WAREHOUSE_STATUS_RESPONSE_INVALID: "The warehouse-lock response is invalid or incomplete.",
          LIVE_STOCK_BATCH_SCOPE_MISMATCH: "Batch details do not match the selected warehouse or product.",
          STOCK_MINIMUM_BULK_RESPONSE_INVALID: "The minimum-stock management response is invalid or incomplete.",
          LIVE_STOCK_BATCH_DETAILS_FAILED: "Batch details could not be loaded.",
          OPERATIONS_RESPONSE_INVALID: "The operations response is invalid or incomplete.",
          INBOUND_DUPLICATE_BATCH_UOM_LINE: "Do not repeat the same product, batch, and purchasing unit on multiple lines. Add another line only for a different purchasing unit.",
          VALIDATION_ERROR: "The request data is invalid. Review the entered fields.",
          RATE_LIMITED: "The request limit was exceeded. Try again later.",
          REQUEST_TOO_LARGE: "The request is larger than the allowed limit.",
          INTERNAL_SERVER_ERROR: "An internal server error occurred.",
          IDENTITY_NOT_READY: "The company or user identity is not ready yet. Refresh and try again.",
          CATALOG_CONTRACT_INVALID: "The catalog response is invalid or incomplete.",
          CATALOG_LIFECYCLE_SCOPE_MISMATCH: "The lifecycle response does not match the selected product.",
          CATALOG_LIFECYCLE_PREFLIGHT_STALE: "The product changed after archive preflight. Refresh and run the check again.",
          CATALOG_PRODUCT_LOCATIONS_LIMIT_EXCEEDED: "The product has more warehouse assignments than this screen can safely load.",
          CATALOG_PRODUCT_LOCATION_SCOPE_MISMATCH: "The warehouse assignment response does not match the requested scope.",
          PRODUCT_LOCATION_NOT_FOUND: "The warehouse product assignment was not found or is no longer available.",
          PRODUCT_LOCATION_TARGET_NOT_FOUND: "The warehouse was not found or cannot be assigned.",
          PRODUCT_LOCATION_VARIANT_NOT_ACTIVE: "A new warehouse assignment can be created only for an active product.",
          PRODUCT_LOCATION_CONFLICT: "The warehouse product assignment could not be saved because the data conflicted.",
          PRODUCT_LOCATION_VERSION_CONFLICT: "The warehouse product assignment changed. Refresh and retry.",
          PRODUCT_LOCATION_DELETE_BLOCKED: "A used or operationally referenced warehouse assignment cannot be removed.",
          PRODUCT_LOCATION_SCOPE_MISMATCH: "The supplied warehouse does not match the requested product assignment.",
          PACKAGE_UOMS_RESPONSE_INVALID: "The package-UOM response is invalid or incomplete.",
          PRODUCT_FAMILIES_RESPONSE_INVALID: "The product-family response is invalid or incomplete.",
          PRODUCT_BARCODES_RESPONSE_INVALID: "The product-barcode response is invalid or incomplete.",
          PRODUCT_BARCODE_MUTATION_RESPONSE_INVALID: "The barcode mutation response is invalid or incomplete.",
          PRODUCT_BARCODES_SCOPE_MISMATCH: "The barcode data does not match the selected product.",
          PRODUCT_BARCODES_CURSOR_DUPLICATE: "Barcode pagination returned a duplicate record.",
          PRODUCT_IMPORT_ACCEPTED_RESPONSE_INVALID: "The product-import start response is invalid or incomplete.",
          PRODUCT_IMPORT_COMMAND_RESPONSE_INVALID: "The product-import command response is invalid or incomplete.",
          PRODUCT_IMPORT_COMMAND_SCOPE_MISMATCH: "The import-command response does not match the active import job.",
          PRODUCT_IMPORT_STATE_RESPONSE_INVALID: "The product-import status response is invalid or incomplete.",
          PRODUCT_IMPORT_ERRORS_RESPONSE_INVALID: "The product-import error response is invalid or incomplete.",
          COMPANY_NOT_FOUND: "The company was not found or is unavailable.",
          PRODUCT_NOT_FOUND: "The product was not found or is unavailable.",
          SIMPLE_PRODUCT_FIELD_REQUIRED: "A required product field is missing.",
          SIMPLE_PRODUCT_FIELD_INVALID: "A product field value is invalid.",
          SIMPLE_PRODUCT_FILTER_INVALID: "A product filter is invalid.",
          SIMPLE_PRODUCT_SORT_INVALID: "The product sort option is invalid.",
          SIMPLE_PRODUCT_PRICE_FILTER_FORBIDDEN: "Filtering products by price requires price-view permission.",
          SIMPLE_PRODUCT_PACKAGE_UOM_UNSUPPORTED: "The selected package unit is not supported by the simple product workflow.",
          SIMPLE_PRODUCT_PACKAGING_INVALID: "The product packaging data is invalid.",
          SIMPLE_PRODUCT_NO_PACKAGE_FACTOR_INVALID: "A product without an outer package must use one base unit.",
          SIMPLE_PRODUCT_PACKAGE_PRICE_WITHOUT_PACKAGE: "A package price cannot be entered for a product without an outer package.",
          SIMPLE_PRODUCT_PACKAGE_FACTOR_INVALID: "An outer package must contain at least two base units.",
          SIMPLE_PRODUCT_PACKAGE_BARCODE_WITHOUT_PACKAGE: "A package barcode cannot be added to a product without an outer package.",
          SIMPLE_PRODUCT_UOM_MISSING: "Required product unit-of-measure data is missing.",
          SIMPLE_PRODUCT_UOM_SHAPE_UNSUPPORTED: "This product uses an advanced UOM structure that cannot be edited safely in the simple workflow.",
          SIMPLE_PRODUCT_EMPTY: "No product was provided for this operation.",
          SIMPLE_PRODUCT_FAMILY_NOT_FOUND: "The product family was not found.",
          SIMPLE_PRODUCT_FAMILY_AMBIGUOUS: "Choose an existing family or enter a new family, not both.",
          SIMPLE_PRODUCT_FAMILY_NAME_AMBIGUOUS: "More than one family has this name. Select the family from the list.",
          SIMPLE_PRODUCT_FAMILY_CONFLICT: "The product family could not be saved because of a data conflict.",
          SIMPLE_PRODUCT_FAMILY_IDEMPOTENCY_CONFLICT: "This family request conflicts with an earlier request.",
          SIMPLE_PRODUCT_CONFLICT: "The product could not be created because of a data conflict.",
          SIMPLE_PRODUCT_PRICE_CONFLICT: "The price could not be updated because of a data conflict.",
          SIMPLE_PRODUCTS_APPROVAL_MODE_UNSUPPORTED: "The simple product workflow is unavailable while pricing approval is enabled.",
          SIMPLE_PRODUCTS_ADVANCED_PRICING_ACTIVE: "Advanced pricing is active or scheduled; use the advanced pricing workflow.",
          SIMPLE_PRODUCTS_FUTURE_PRICING_ACTIVE: "A future company-default price is already scheduled.",
          SIMPLE_PRODUCTS_MULTIPLE_DEFAULT_PRICES: "More than one company-default price is currently active.",
          SIMPLE_PRODUCTS_OFFERS_BLOCKED: "The current default pricing configuration does not allow this simple workflow.",
          SIMPLE_PRODUCT_DEFAULT_PRICE_BOOK_INVALID: "The company default price book is invalid.",
          SIMPLE_PRODUCT_CURRENCY_MISMATCH: "The default price-book currency does not match the company currency.",
          SIMPLE_PRODUCT_DEFAULT_BOOK_CONFLICT: "A safe default price book could not be created.",
          PRODUCT_IMPORT_FILE_NAME_INVALID: "The import file name is invalid.",
          PRODUCT_IMPORT_MAPPING_NAME_REQUIRED: "Map a product-name column before continuing.",
          PRODUCT_IMPORT_MAPPING_PRICE_REQUIRED: "Map at least one price column before continuing.",
          PRODUCT_IMPORT_MAPPING_CONFLICT: "The import column mapping conflicts with the current job state.",
          PRODUCT_IMPORT_NOT_FOUND: "The product-import job was not found or is unavailable.",
          PRODUCT_IMPORT_NOT_RETRYABLE: "The current import job cannot be retried.",
          PRODUCT_IMPORT_QUEUE_UNAVAILABLE: "The product-import service is unavailable right now. Try again later.",
          INVALID_CURSOR: "The page cursor is invalid or does not match the current request scope.",
          IDEMPOTENCY_CONFLICT: "This operation id was already used for a different request.",
          VARIANT_NOT_FOUND: "The selected SKU was not found or is unavailable.",
          VARIANT_VERSION_CONFLICT: "The SKU changed after you opened it. Refresh and try again.",
          VARIANT_STRUCTURE_LOCKED: "The SKU structure cannot be edited after it leaves Draft status.",
          VARIANT_IDENTITY_CONFLICT: "The SKU or GTIN identity is already in use.",
          VARIANT_CONFLICT: "The SKU could not be changed because of a data conflict.",
          UOM_NOT_FOUND: "The selected unit of measure was not found.",
          UOM_STRUCTURE_LOCKED: "Unit conversions can only be edited while the SKU is a draft.",
          UOM_CONVERSION_CONFLICT: "The unit conversion already exists or conflicts with another conversion.",
          UOM_CONVERSION_NOT_FOUND: "The unit conversion was not found.",
          UOM_CONVERSION_VERSION_CONFLICT: "The unit conversion changed after you opened it. Refresh and try again.",
          BARCODE_NOT_FOUND: "The barcode was not found.",
          BARCODE_VERSION_CONFLICT: "The barcode changed after you opened it. Refresh and try again.",
          BARCODE_VALIDITY_INVALID: "The barcode validity period is invalid.",
          BARCODE_CONFLICT: "The active or primary barcode conflicts with another record.",
          GS1_INVALID: "The GS1 value is invalid.",
          PRODUCT_CODE_CONFLICT: "The product code is already in use.",
          PRODUCT_STATE_CONFLICT: "The product state changed or conflicts with the requested operation.",
          PRODUCT_VERSION_CONFLICT: "The product changed after you opened it. Refresh and try again.",
          PRODUCT_PUBLISH_READINESS_FAILED: "The product is not ready to publish. Complete the required data first.",
          PRODUCT_PUBLISH_TRANSITION_INVALID: "The product cannot be published from its current state.",
          PRODUCT_STATE_INVALID: "The product state is invalid.",
          PRODUCT_RETIRE_TRANSITION_INVALID: "The product cannot begin retirement from its current state.",
          PRODUCT_RESTORE_TRANSITION_INVALID: "The product cannot be restored from its current state.",
          PRODUCT_RESTORE_READINESS_FAILED: "The product is not ready to be restored to Active status.",
          PRODUCT_ARCHIVE_TRANSITION_INVALID: "The product cannot be archived from its current state.",
          PRODUCT_ARCHIVE_BLOCKED: "The product cannot be archived until the current blockers are resolved.",
          PRODUCT_HOLD_OPEN: "An operational hold is still open and must be resolved first.",
          PRODUCT_RECALL_OPEN: "A product recall is still open and must be resolved first.",
          PRODUCT_RECALL_COMPLETION_REQUIRED: "Recall requirements must be completed before continuing.",
          PRODUCT_RECALL_TRANSITION_INVALID: "A recall cannot be issued from the product's current state.",
          PRODUCT_RECALL_CLOSE_INVALID: "There is no open recall to close.",
          PRODUCT_SALES_HOLD_TRANSITION_INVALID: "Sales cannot be put on hold from the product's current state.",
          PRODUCT_SALES_HOLD_RELEASE_INVALID: "There is no sales hold to release.",
          PRODUCT_DRAFT_DELETE_BLOCKED: "The draft cannot be deleted until its current links or blockers are resolved.",
          PRODUCT_DELETE_DRAFT_TRANSITION_INVALID: "Product deletion is only available for drafts.",
          PRODUCT_TRACKING_MODE_INVALID: "The lot or expiry tracking mode is invalid.",
          PRODUCT_TRACKING_ID_INVALID: "The product identity used for tracking is invalid.",
          PRODUCT_TRACKING_DATE_INVALID: "The tracking date is invalid.",
          PRODUCT_TRACKING_INTERNAL_BATCH_INVALID: "The internal batch identity is invalid.",
          LIVE_STOCK_PROJECTION_FAILED: "The live-stock projection could not be refreshed after the operation.",
          PRICE_AMOUNT_INVALID: "The price amount is invalid.",
          PRICE_NOT_RESOLVED: "No effective price could be resolved for this product.",
          PRICE_PRECISION_UNSUPPORTED: "The requested price precision is not supported.",
          PRICE_BOOK_NOT_FOUND: "The price book was not found.",
          PRICE_BOOK_INACTIVE: "The price book is inactive.",
          PRICE_BOOK_VERSION_CONFLICT: "The price book changed. Refresh and try again.",
          PRICE_ENTRY_NOT_FOUND: "The price entry was not found.",
          PRICE_ENTRY_VERSION_CONFLICT: "The price entry changed. Refresh and try again.",
          PRICE_ENTRY_IMMUTABLE: "A published price entry cannot be edited directly.",
          PRICE_EFFECTIVITY_INVALID: "The price effective period is invalid.",
          PRICE_EFFECTIVITY_CONFLICT: "The price effective period conflicts with another price.",
          PRICE_EFFECTIVITY_BEFORE_PUBLICATION: "A price cannot become effective before it is published.",
          PRICE_VARIANT_NOT_FOUND: "The SKU required for pricing was not found.",
          PRICE_UOM_MAPPING_UNRESOLVED: "The price unit could not be mapped to a product unit.",
          PRICE_UOM_MAPPING_AMBIGUOUS: "More than one price-unit mapping is possible.",
          PRICE_ASSIGNMENT_SCOPE_INVALID: "The price-assignment scope is invalid.",
          PRICE_ASSIGNMENT_SCOPE_NOT_FOUND: "The price-assignment scope was not found.",
          PRICE_ASSIGNMENT_SCOPE_RESERVED: "The price-assignment scope is reserved and cannot be used here.",
          PRICE_ASSIGNMENT_TIE: "More than one price has the same matching priority.",
          PRICE_BRANCH_NOT_FOUND: "The branch selected for pricing was not found.",
          PRICE_CUSTOMER_NOT_FOUND: "The customer selected for pricing was not found.",
          COMMERCIAL_CONTEXT_LOCKED: "The commercial context is locked and cannot be changed during this operation.",
          PRICE_RESOLVE_INPUT_INVALID: "The price-resolution input is invalid.",
          PRICE_PUBLICATION_NOT_FOUND: "The price publication was not found.",
          PRICE_PUBLICATION_NOT_EDITABLE: "The price publication is no longer editable.",
          PRICE_PUBLICATION_STATE_CONFLICT: "The price-publication state does not allow this operation.",
          PRICE_PUBLICATION_VERSION_CONFLICT: "The price publication changed. Refresh and try again.",
          PRICE_PUBLICATION_EMPTY: "An empty price publication cannot be published.",
          PRICE_PUBLICATION_EFFECTIVE_AT_REQUIRED: "The price effective date is required.",
          PRICING_APPROVAL_POLICY_INVALID: "The pricing approval configuration is invalid.",
          PRICING_APPROVAL_NOT_ENABLED: "Pricing approval is not enabled.",
          PRICING_APPROVAL_REQUIRED: "This operation requires approval before it can be completed.",
          PRICING_DATETIME_OFFSET_REQUIRED: "Pricing dates must include a time-zone offset.",
          PRICING_SEPARATION_OF_DUTIES: "Separation-of-duties policy prevents the same user from completing both steps.",
          TENANT_NOT_FOUND: "The company was not found or is unavailable.",
          PRODUCT_NOT_OPERATIONAL: "The product is not operationally available right now.",
          SIMPLE_PRODUCTS_RESPONSE_INVALID: "The product-list response is invalid or incomplete.",
          SIMPLE_PRODUCT_CREATE_RESPONSE_INVALID: "The product-create response is invalid or incomplete.",
          SIMPLE_PRODUCT_PRICE_RESPONSE_INVALID: "The product-price update response is invalid or incomplete.",
          SIMPLE_PRODUCT_PRICE_SCOPE_MISMATCH: "The price-update response does not match the selected product.",
          PRODUCT_TRACKING_DEFAULTS_RESPONSE_INVALID: "The product-tracking defaults response is invalid.",
          PRODUCT_TRACKING_MUTATION_RESPONSE_INVALID: "The product-tracking update response is invalid.",
          PRODUCT_TRACKING_LOCKED: "Tracking settings cannot be changed through the normal editor because this product already has batch history. Use an approved migration workflow if a change is required.",
          PRODUCT_TRACKING_VERSION_CONFLICT: "This product changed after you opened it. Refresh the product list and try again.",
          PRODUCT_TRACKING_LIFECYCLE_BLOCKED: "Tracking settings cannot be edited for a retiring or archived product.",
          PRODUCT_TRACKING_VARIANT_NOT_FOUND: "The product was not found or does not belong to this company.",
          PRODUCT_TRACKING_DEFAULTS_CONFLICT: "Default tracking settings could not be saved because of a data conflict.",
          PRODUCT_TRACKING_CONFLICT: "Product tracking settings could not be saved because of a data conflict.",
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
          DURABLE_OPERATION_PENDING:
            "A previous command for this operation still has an unknown outcome. Retry that exact command or reconcile it before sending a different one.",
          DURABLE_OPERATION_CORRUPT:
            "The saved pending command on this device could not be verified. The operation was blocked to prevent a duplicate until it is reconciled.",
          PRODUCT_FAMILY_MUTATION_RESPONSE_INVALID:
            "An unexpected response was received after saving the family. The command remains pending to prevent a duplicate until it is reconciled.",
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
          IMPORT_NAME_TOO_LONG:
            "Product name exceeds the supported length.",
          IMPORT_PACKAGE_BARCODE_WITHOUT_PACKAGE:
            "A package barcode cannot be supplied without an outer package.",
          IMPORT_ROW_INVALID:
            "The row contains invalid import data.",
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
