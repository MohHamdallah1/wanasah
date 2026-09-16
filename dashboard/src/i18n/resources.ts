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
        codes: {
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
        codes: {
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
