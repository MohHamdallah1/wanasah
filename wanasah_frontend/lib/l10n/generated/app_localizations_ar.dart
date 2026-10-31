// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Arabic (`ar`).
class AppLocalizationsAr extends AppLocalizations {
  AppLocalizationsAr([String locale = 'ar']) : super(locale);

  @override
  String get appTitle => 'وناسة';

  @override
  String get dashboardConnectivityCached => 'تعذر الوصول إلى النظام مؤقتًا. نعرض آخر بيانات محفوظة ويمكنك المحاولة مجددًا.';

  @override
  String get dashboardServiceCached => 'تعذر تحديث البيانات بسبب مشكلة مؤقتة في الخدمة. بياناتك المحفوظة ما زالت متاحة.';

  @override
  String get dashboardGenericError => 'تعذر تحميل هذه البيانات الآن. حاول مرة أخرى، وإذا استمرت المشكلة تواصل مع الدعم.';

  @override
  String get retry => 'إعادة المحاولة';

  @override
  String get home => 'الرئيسية';

  @override
  String get route => 'خط السير';

  @override
  String get custody => 'العهدة';

  @override
  String get brand => 'وناسة';

  @override
  String get account => 'الحساب';

  @override
  String get refresh => 'تحديث البيانات';

  @override
  String get logout => 'تسجيل الخروج';

  @override
  String get logoutTitle => 'تأكيد الخروج';

  @override
  String get logoutPrompt => 'هل تريد تسجيل الخروج؟';

  @override
  String get cancel => 'إلغاء';

  @override
  String get confirm => 'نعم، تأكيد';

  @override
  String greeting(String name) {
    return 'أهلاً بك، $name!';
  }

  @override
  String region(String region) {
    return 'المنطقة المخصصة: $region';
  }

  @override
  String today(String date) {
    return 'تاريخ اليوم: $date';
  }

  @override
  String get routeSummary => 'ملخص الجولة';

  @override
  String completedVisits(String count) {
    return 'الزيارات المكتملة: $count';
  }

  @override
  String salesVisits(String count) {
    return 'الزيارات الناجحة (مبيعات): $count';
  }

  @override
  String pendingVisits(String count) {
    return 'الزيارات المعلقة: $count';
  }

  @override
  String offlineVisits(String count) {
    return 'بانتظار المزامنة: $count';
  }

  @override
  String get financialSummary => 'الملخص المالي';

  @override
  String salesCash(String amount) {
    return 'إجمالي كاش المبيعات: $amount';
  }

  @override
  String debtCash(String count, String amount) {
    return 'إجمالي الذمم المحصلة: ($count) $amount';
  }

  @override
  String totalCash(String amount) {
    return 'إجمالي الكاش المستلم: $amount';
  }

  @override
  String get pendingTransfers => 'مراجعة الحوالات المعلقة';

  @override
  String get recoveryChecking => 'جارٍ التحقق';

  @override
  String get recoveryNoPending => 'لا عمليات معلّقة';

  @override
  String recoveryPendingCompact(String count) {
    return 'معلّقة: $count';
  }

  @override
  String recoveryBlockedCompact(String count) {
    return 'تحتاج انتباهًا: $count';
  }

  @override
  String get recoveryUnavailableCompact => 'الحالة غير مؤكدة';

  @override
  String get recoveryUnreachableCompact => 'تعذر الوصول للخدمة';

  @override
  String get recoveryServiceCompact => 'تعذر تحديث الخدمة';

  @override
  String get recoveryCachedCompact => 'البيانات المحفوظة';

  @override
  String get recoverySyncingCompact => 'جارٍ المزامنة';

  @override
  String get recoveryRefreshAction => 'مزامنة وتحديث';

  @override
  String get recoveryInspectAction => 'إعادة قراءة الحالة';

  @override
  String get recoveryDetailsAction => 'عرض الأدلة المحفوظة';

  @override
  String recoveryPendingBanner(String count) {
    return 'عمليات بانتظار المزامنة: $count';
  }

  @override
  String recoveryBlockedBanner(String count) {
    return 'عمليات تحتاج استرداداً: $count';
  }

  @override
  String recoveryCombinedBanner(String pending, String blocked) {
    return 'بانتظار المزامنة: $pending • تحتاج استرداداً: $blocked';
  }

  @override
  String get recoveryDetailsHint => 'اضغط لعرض التفاصيل.';

  @override
  String get recoveryPanelTitle => 'حالة المزامنة والاسترداد';

  @override
  String get recoveryPanelDescription => 'السجلات المعلقة والمحجوبة دليل محفوظ. لا تُحذف لمجرد إخفاء الخطأ.';

  @override
  String get recoveryPendingSection => 'بانتظار المزامنة';

  @override
  String get recoveryBlockedSection => 'تحتاج استرداداً';

  @override
  String get recoveryPendingState => 'معلّقة';

  @override
  String get recoveryBlockedState => 'محجوبة';

  @override
  String get recoveryOperationLabel => 'العملية';

  @override
  String get recoveryCommandIdLabel => 'معرّف الأمر';

  @override
  String get recoveryLocalRecordLabel => 'السجل المحلي';

  @override
  String get recoveryAttemptsLabel => 'عدد المحاولات';

  @override
  String get recoveryErrorCodeLabel => 'رمز الخطأ';

  @override
  String get recoveryRequestIdLabel => 'رقم التتبع';

  @override
  String get recoveryCreatedAtLabel => 'التاريخ';

  @override
  String get recoveryVisitLabel => 'الزيارة';

  @override
  String get recoveryTransferLabel => 'الحوالة';

  @override
  String get recoveryReferenceLabel => 'مرجع';

  @override
  String get recoveryReasonLabel => 'التفصيل';

  @override
  String get recoveryMissingValue => 'غير متوفر';

  @override
  String get recoveryNoRecoveryItems => 'لا توجد عمليات معلقة أو محجوبة.';

  @override
  String get recoveryReadUnavailable => 'تعذر قراءة حالة المزامنة المحلية. لم يتم افتراض أنها فارغة.';

  @override
  String get recoverySyncInProgress => 'جاري مزامنة العمليات المحفوظة…';

  @override
  String get recoverySyncSuccess => 'تمت المزامنة بالكامل.';

  @override
  String get recoverySyncIncomplete => 'المزامنة غير مكتملة؛ ما زالت هناك عمليات معلقة.';

  @override
  String get recoverySyncRecoveryRequired => 'توجد عمليات محجوبة تحتاج استرداداً قبل اعتبار المزامنة مكتملة.';

  @override
  String get recoverySyncConnectivityUnresolved => 'تعذر الاتصال أثناء المزامنة. السجلات المحلية ما زالت محفوظة.';

  @override
  String get recoverySyncTimedOut => 'انتهت مهلة المزامنة قبل تأكيد النتيجة. السجلات المحلية ما زالت محفوظة.';

  @override
  String get recoverySyncUnresolved => 'تعذر تأكيد نتيجة المزامنة. حالة السجلات المحلية ما زالت محفوظة.';

  @override
  String get recoverySubmitSale => 'زيارة / فاتورة';

  @override
  String get recoveryTransferResponse => 'رد حوالة';

  @override
  String get recoveryLegacyBreak => 'استراحة قديمة';

  @override
  String get recoveryCorrupt => 'سجل غير صالح';

  @override
  String get recoveryUnknownOperation => 'عملية غير معروفة';

  @override
  String get recoveryReadOnlyNotice => 'السجلات المحجوبة للقراءة فقط في هذه المرحلة ولا يوجد حذف شامل.';

  @override
  String get homeTodayRoute => 'جولة اليوم';

  @override
  String get homeCompletedLabel => 'مكتملة';

  @override
  String get homeRemainingLabel => 'متبقية';

  @override
  String get homeSalesLabel => 'مبيعات';

  @override
  String homeAwaitingSync(String count) {
    return '$count زيارة بانتظار المزامنة';
  }

  @override
  String get homeCashReceived => 'إجمالي الكاش المستلم';

  @override
  String get homeCashSales => 'مبيعات نقدية';

  @override
  String get homeDebtCollections => 'تحصيل ذمم';

  @override
  String homeDebtOperations(String count) {
    return '$count عملية';
  }

  @override
  String get workSessionReadyStatus => 'جاهز للبدء';

  @override
  String get workSessionActiveStatus => 'العمل جارٍ';

  @override
  String get workSessionBreakStatus => 'في استراحة';

  @override
  String get workSessionReadyTitle => 'ابدأ يومك';

  @override
  String get workSessionActiveTitle => 'الجولة مستمرة';

  @override
  String get workSessionBreakTitle => 'أنت في استراحة';

  @override
  String get workSessionReadyHint => 'ابدأ جلسة العمل عندما تكون جاهزًا للانطلاق.';

  @override
  String get workSessionActiveHint => 'جلسة العمل الحالية فعّالة وحالة اليوم مستمرة.';

  @override
  String get workSessionBreakHint => 'الجلسة محفوظة. أنهِ الاستراحة عندما تكون جاهزًا للمتابعة.';

  @override
  String get workSessionStartUnknown => 'وقت بدء الجلسة غير متوفر.';

  @override
  String workSessionStartedAt(String time) {
    return 'بدأت $time';
  }

  @override
  String workSessionElapsed(String duration) {
    return 'مضى $duration';
  }

  @override
  String get workSessionStartAction => 'بدء العمل';

  @override
  String get workSessionEndAction => 'إنهاء العمل';

  @override
  String get workSessionStartBreakAction => 'بدء الاستراحة';

  @override
  String get workSessionEndBreakAction => 'إنهاء الاستراحة';

  @override
  String get workSessionConfirmStartTitle => 'بدء العمل؟';

  @override
  String get workSessionConfirmStartBody => 'هل تريد بدء جلسة عمل جديدة؟';

  @override
  String get workSessionConfirmEndTitle => 'إنهاء العمل؟';

  @override
  String get workSessionConfirmEndBody => 'هل تريد إنهاء جلسة العمل الحالية؟';

  @override
  String get workSessionStartSuccess => 'تم بدء جلسة العمل.';

  @override
  String get workSessionEndSuccess => 'تم إنهاء جلسة العمل.';

  @override
  String get workSessionBreakStartSuccess => 'تم بدء الاستراحة (مسجلة على السيرفر).';

  @override
  String get workSessionBreakEndSuccess => 'تم إنهاء الاستراحة (مسجلة على السيرفر).';

  @override
  String get workSessionStartReconciled => 'تم تأكيد أن جلسة العمل نشطة بعد مطابقة حالتها مع السيرفر.';

  @override
  String get workSessionEndReconciled => 'تم تأكيد انتهاء جلسة العمل بعد مطابقة حالتها مع السيرفر.';

  @override
  String get workSessionBreakStartReconciled => 'تم تأكيد بدء الاستراحة بعد مطابقة حالتها مع السيرفر.';

  @override
  String get workSessionBreakEndReconciled => 'تم تأكيد انتهاء الاستراحة بعد مطابقة حالتها مع السيرفر.';

  @override
  String get workSessionUnresolved => 'تعذر تأكيد نتيجة العملية. حدّث البيانات قبل المحاولة مجدداً.';

  @override
  String get workSessionAuthRejected => 'انتهت صلاحية الجلسة أو لا تملك صلاحية تنفيذ العملية.';

  @override
  String get workSessionBusinessRejected => 'رفض السيرفر العملية بسبب حالة العمل الحالية.';

  @override
  String get workSessionRateLimited => 'عدد الطلبات مرتفع حالياً. أعد المحاولة بعد قليل.';

  @override
  String get workSessionNetworkUnresolved => 'تعذر تأكيد نتيجة العملية بسبب الاتصال. تم الحفاظ على حالة السيرفر كمرجع وحيد.';

  @override
  String get workSessionTimeoutUnresolved => 'انتهت مهلة الاتصال قبل تأكيد نتيجة العملية. حالة السيرفر ما زالت المرجع الوحيد.';

  @override
  String get workSessionServerUnresolved => 'تعذر تأكيد نتيجة العملية بسبب خطأ في السيرفر.';

  @override
  String get workSessionRequestIdLabel => 'رقم التتبع';

  @override
  String get workSessionStatusCodeLabel => 'رمز الحالة';

  @override
  String get workSessionServerDetailLabel => 'تفصيل السيرفر';

  @override
  String get workSessionIssueAuthentication => 'يلزم تأكيد تسجيل الدخول قبل تنفيذ إجراء الجلسة.';

  @override
  String get workSessionIssueInvalidStartEvidence => 'بيانات بدء العمل التي وصلت للسيرفر غير صالحة. حدّث البيانات ثم أعد المحاولة.';

  @override
  String get workSessionIssueVehicleCustody => 'عهدة السيارة التشغيلية غير جاهزة لبدء العمل. راجع مسؤول التوزيع أو العهدة.';

  @override
  String get workSessionIssueStartPrerequisite => 'السيرفر رفض بدء العمل بسبب متطلب تشغيلي في خط السير أو السيارة أو العهدة. راجع مسؤول التوزيع ثم أعد المحاولة.';

  @override
  String get workSessionIssueEndPrerequisite => 'السيرفر رفض إنهاء العمل بسبب متطلب تشغيلي قائم. عالج الاستراحة أو الحوالات المعلقة الظاهرة ثم أعد المحاولة.';

  @override
  String get workSessionIssueBreakState => 'حالة الاستراحة على السيرفر لا تسمح بهذا الإجراء. حدّث حالة الجلسة ثم أعد المحاولة.';

  @override
  String get workSessionIssueRateLimited => 'تم تأجيل إجراء الجلسة بسبب حد الطلبات. أعد المحاولة بعد قليل.';

  @override
  String get workSessionIssueConnectivity => 'تعذر الاتصال بالسيرفر. تحقق من الشبكة وحدّث حالة الجلسة قبل إعادة المحاولة.';

  @override
  String get workSessionIssueTimeout => 'انتهت مهلة الاتصال قبل تأكيد النتيجة. حدّث حالة الجلسة قبل إعادة المحاولة.';

  @override
  String get workSessionIssueUnresolved => 'لم يتم تأكيد نتيجة إجراء الجلسة. حالة السيرفر هي المرجع؛ حدّث البيانات قبل إعادة المحاولة.';

  @override
  String get visitListTitle => 'خط السير';

  @override
  String get visitRefreshTooltip => 'تحديث الجولة';

  @override
  String get visitNormalRouteTab => 'جولة اليوم';

  @override
  String get visitEmergencyRouteTab => 'طلبات عاجلة';

  @override
  String visitFilterAll(String count) {
    return 'الكل $count';
  }

  @override
  String visitFilterCompleted(String count) {
    return 'المكتملة $count';
  }

  @override
  String visitFilterPending(String count) {
    return 'المتبقية $count';
  }

  @override
  String get visitStatusCompleted => 'مكتملة';

  @override
  String get visitStatusPending => 'قيد الانتظار';

  @override
  String get visitStatusAttempted => 'محاولة سابقة';

  @override
  String get visitStatusPostponed => 'مؤجلة';

  @override
  String get visitStatusNoSale => 'بدون بيع';

  @override
  String visitStatusUnknown(String status) {
    return 'حالة غير معروفة ($status)';
  }

  @override
  String visitBalanceLabel(String amount) {
    return 'الذمة: $amount د.أ';
  }

  @override
  String get visitMapTooltip => 'فتح موقع المحل';

  @override
  String get visitEmptyNormalAll => 'لا توجد زيارات مجدولة لك حاليًا.';

  @override
  String get visitEmptyEmergencyAll => 'لا توجد طلبات عاجلة حاليًا.';

  @override
  String get visitEmptyNormalPending => 'لا توجد زيارات متبقية.';

  @override
  String get visitEmptyEmergencyPending => 'لا توجد طلبات عاجلة متبقية.';

  @override
  String get visitEmptyNormalCompleted => 'لم تُكمل أي زيارة بعد.';

  @override
  String get visitEmptyEmergencyCompleted => 'لم تُكمل أي طلب عاجل بعد.';

  @override
  String get visitAddShopAction => 'إضافة محل';

  @override
  String get visitGateOnBreak => 'أنت الآن في وقت الاستراحة. أنهِ الاستراحة لمتابعة العمل.';

  @override
  String get visitGateUnauthorizedAdd => 'غير مصرح لك بإضافة محلات.';

  @override
  String get visitGateUnauthorizedOpen => 'غير مصرح لك بفتح الزيارة حاليًا.';

  @override
  String get visitGateUnavailable => 'تعذر تأكيد حالة جلسة العمل والصلاحية. حدّث البيانات ثم أعد المحاولة.';

  @override
  String get visitRefreshSuccess => 'تم تحديث قائمة الزيارات.';

  @override
  String get visitRefreshAlreadySyncing => 'المزامنة جارية بالفعل من مكان آخر.';

  @override
  String get visitRefreshTransportAmbiguous => 'تعذر تأكيد نتيجة التحديث بسبب الاتصال. يتم عرض البيانات المحلية.';

  @override
  String get visitRefreshBlocked => 'يوجد عمل أوفلاين غير محسوم يمنع استبدال البيانات المحلية.';

  @override
  String get visitRefreshDeterministicFailure => 'تعذر تحديث قائمة الزيارات.';

  @override
  String get visitLoadFailure => 'تعذر تحميل قائمة الزيارات المحلية.';

  @override
  String get visitMapNoLocation => 'لا يتوفر موقع مسجل لهذا المحل.';

  @override
  String get visitMapNoApplication => 'لا يوجد تطبيق خرائط مثبت ولا رابط خارجي صالح.';

  @override
  String get visitMapInvalidLink => 'رابط الموقع غير صالح.';

  @override
  String get visitMapOpenFailed => 'تعذر فتح موقع المحل.';

  @override
  String get visitRequestIdLabel => 'رقم التتبع';

  @override
  String visitRouteOverview(String total, String completed, String pending) {
    return '$total زيارة • $completed مكتملة • $pending متبقية';
  }

  @override
  String get visitNextLabel => 'التالي';

  @override
  String get visitUrgentLabel => 'عاجل';

  @override
  String get visitOpenVisitHint => 'فتح الزيارة';

  @override
  String get stockVehicleTitle => 'مخزون سيارة المندوب:';

  @override
  String get stockEmptyVerified => 'لا يوجد مخزون متاح للبيع في السيارة حالياً.';

  @override
  String get stockUnavailable => 'تعذر التحقق من مخزون السيارة؛ الرصيد غير معروف.';

  @override
  String get stockDenied => 'لا توجد صلاحية لعرض العهدة الحالية.';

  @override
  String get stockStale => 'مخزون محفوظ للاستخدام دون اتصال؛ ليس رصيداً حالياً مؤكداً.';

  @override
  String get stockReceived => 'الاستلام';

  @override
  String get stockSold => 'المباع';

  @override
  String get stockRemaining => 'المتبقي';

  @override
  String get stockCarton => 'كرتونة';

  @override
  String get stockPack => 'باكيت';

  @override
  String get stockPiece => 'حبة';

  @override
  String get stockPendingReturns => 'مرتجعات محلية بانتظار الحسم:';

  @override
  String get stockPendingReturnsHint => 'هذه أدلة محلية معلقة وليست رصيد العهدة النهائي من السيرفر.';

  @override
  String get stockNonSellableTitle => 'عهدة غير قابلة للبيع:';

  @override
  String get stockStatusDamaged => 'تالف';

  @override
  String get stockStatusQuarantined => 'محجور';

  @override
  String get stockStatusBlocked => 'محظور';

  @override
  String get stockStatusRecalled => 'مستدعى';

  @override
  String get stockStatusDisposalPending => 'بانتظار الإتلاف';

  @override
  String get stockPending => 'بانتظار المزامنة';

  @override
  String get stockInFlight => 'قيد الإرسال';

  @override
  String get stockNeedsAction => 'يحتاج معالجة';

  @override
  String get stockReasonExpired => 'منتهي الصلاحية';

  @override
  String get stockReasonFactory => 'عيب مصنعي';

  @override
  String get stockAvailableLocal => 'المتوفر محلياً (غير مؤكد حالياً)';

  @override
  String get stockSearchHint => 'ابحث عن صنف...';

  @override
  String get stockConfirmQuantities => 'اعتماد الكميات والعودة للفاتورة';

  @override
  String get stockSaleCartons => 'كراتين المبيع';

  @override
  String get stockSalePacks => 'حبات المبيع';

  @override
  String get stockSampleCartons => 'كراتين العينات (🎁)';

  @override
  String get stockSamplePacks => 'حبات العينات (🎁)';

  @override
  String get stockSampleReasonHint => 'اختر سبب صرف العينة (إجباري)';

  @override
  String get stockSampleReasonDetailsHint => 'اكتب السبب بالتفصيل...';

  @override
  String get stockSampleReasonPromo => 'ترويج منتج جديد';

  @override
  String get stockSampleReasonFree => 'عينة مجانية للزبائن';

  @override
  String get stockSampleReasonCompensation => 'تعويض ودي للمحل';

  @override
  String get stockSampleReasonOther => 'أخرى';
}
