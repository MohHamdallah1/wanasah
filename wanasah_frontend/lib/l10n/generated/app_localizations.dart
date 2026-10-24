import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_ar.dart';
import 'app_localizations_en.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'generated/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale) : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations)!;
  }

  static const LocalizationsDelegate<AppLocalizations> delegate = _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates = <LocalizationsDelegate<dynamic>>[
    delegate,
    GlobalMaterialLocalizations.delegate,
    GlobalCupertinoLocalizations.delegate,
    GlobalWidgetsLocalizations.delegate,
  ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('ar'),
    Locale('en')
  ];

  /// No description provided for @appTitle.
  ///
  /// In ar, this message translates to:
  /// **'وناسة'**
  String get appTitle;

  /// No description provided for @dashboardConnectivityCached.
  ///
  /// In ar, this message translates to:
  /// **'تعذر الوصول إلى النظام مؤقتًا. نعرض آخر بيانات محفوظة ويمكنك المحاولة مجددًا.'**
  String get dashboardConnectivityCached;

  /// No description provided for @dashboardServiceCached.
  ///
  /// In ar, this message translates to:
  /// **'تعذر تحديث البيانات بسبب مشكلة مؤقتة في الخدمة. بياناتك المحفوظة ما زالت متاحة.'**
  String get dashboardServiceCached;

  /// No description provided for @dashboardGenericError.
  ///
  /// In ar, this message translates to:
  /// **'تعذر تحميل هذه البيانات الآن. حاول مرة أخرى، وإذا استمرت المشكلة تواصل مع الدعم.'**
  String get dashboardGenericError;

  /// No description provided for @retry.
  ///
  /// In ar, this message translates to:
  /// **'إعادة المحاولة'**
  String get retry;

  /// No description provided for @home.
  ///
  /// In ar, this message translates to:
  /// **'الرئيسية'**
  String get home;

  /// No description provided for @route.
  ///
  /// In ar, this message translates to:
  /// **'خط السير'**
  String get route;

  /// No description provided for @custody.
  ///
  /// In ar, this message translates to:
  /// **'العهدة'**
  String get custody;

  /// No description provided for @brand.
  ///
  /// In ar, this message translates to:
  /// **'وناسة'**
  String get brand;

  /// No description provided for @account.
  ///
  /// In ar, this message translates to:
  /// **'الحساب'**
  String get account;

  /// No description provided for @refresh.
  ///
  /// In ar, this message translates to:
  /// **'تحديث البيانات'**
  String get refresh;

  /// No description provided for @logout.
  ///
  /// In ar, this message translates to:
  /// **'تسجيل الخروج'**
  String get logout;

  /// No description provided for @logoutTitle.
  ///
  /// In ar, this message translates to:
  /// **'تأكيد الخروج'**
  String get logoutTitle;

  /// No description provided for @logoutPrompt.
  ///
  /// In ar, this message translates to:
  /// **'هل تريد تسجيل الخروج؟'**
  String get logoutPrompt;

  /// No description provided for @cancel.
  ///
  /// In ar, this message translates to:
  /// **'إلغاء'**
  String get cancel;

  /// No description provided for @confirm.
  ///
  /// In ar, this message translates to:
  /// **'نعم، تأكيد'**
  String get confirm;

  /// No description provided for @greeting.
  ///
  /// In ar, this message translates to:
  /// **'أهلاً بك، {name}!'**
  String greeting(String name);

  /// No description provided for @region.
  ///
  /// In ar, this message translates to:
  /// **'المنطقة المخصصة: {region}'**
  String region(String region);

  /// No description provided for @today.
  ///
  /// In ar, this message translates to:
  /// **'تاريخ اليوم: {date}'**
  String today(String date);

  /// No description provided for @routeSummary.
  ///
  /// In ar, this message translates to:
  /// **'ملخص الجولة'**
  String get routeSummary;

  /// No description provided for @completedVisits.
  ///
  /// In ar, this message translates to:
  /// **'الزيارات المكتملة: {count}'**
  String completedVisits(String count);

  /// No description provided for @salesVisits.
  ///
  /// In ar, this message translates to:
  /// **'الزيارات الناجحة (مبيعات): {count}'**
  String salesVisits(String count);

  /// No description provided for @pendingVisits.
  ///
  /// In ar, this message translates to:
  /// **'الزيارات المعلقة: {count}'**
  String pendingVisits(String count);

  /// No description provided for @offlineVisits.
  ///
  /// In ar, this message translates to:
  /// **'بانتظار المزامنة: {count}'**
  String offlineVisits(String count);

  /// No description provided for @financialSummary.
  ///
  /// In ar, this message translates to:
  /// **'الملخص المالي'**
  String get financialSummary;

  /// No description provided for @salesCash.
  ///
  /// In ar, this message translates to:
  /// **'إجمالي كاش المبيعات: {amount}'**
  String salesCash(String amount);

  /// No description provided for @debtCash.
  ///
  /// In ar, this message translates to:
  /// **'إجمالي الذمم المحصلة: ({count}) {amount}'**
  String debtCash(String count, String amount);

  /// No description provided for @totalCash.
  ///
  /// In ar, this message translates to:
  /// **'إجمالي الكاش المستلم: {amount}'**
  String totalCash(String amount);

  /// No description provided for @pendingTransfers.
  ///
  /// In ar, this message translates to:
  /// **'مراجعة الحوالات المعلقة'**
  String get pendingTransfers;

  /// No description provided for @recoveryChecking.
  ///
  /// In ar, this message translates to:
  /// **'جارٍ التحقق'**
  String get recoveryChecking;

  /// No description provided for @recoveryNoPending.
  ///
  /// In ar, this message translates to:
  /// **'لا عمليات معلّقة'**
  String get recoveryNoPending;

  /// No description provided for @recoveryPendingCompact.
  ///
  /// In ar, this message translates to:
  /// **'معلّقة: {count}'**
  String recoveryPendingCompact(String count);

  /// No description provided for @recoveryBlockedCompact.
  ///
  /// In ar, this message translates to:
  /// **'تحتاج انتباهًا: {count}'**
  String recoveryBlockedCompact(String count);

  /// No description provided for @recoveryUnavailableCompact.
  ///
  /// In ar, this message translates to:
  /// **'الحالة غير مؤكدة'**
  String get recoveryUnavailableCompact;

  /// No description provided for @recoveryUnreachableCompact.
  ///
  /// In ar, this message translates to:
  /// **'تعذر الوصول للخدمة'**
  String get recoveryUnreachableCompact;

  /// No description provided for @recoveryServiceCompact.
  ///
  /// In ar, this message translates to:
  /// **'تعذر تحديث الخدمة'**
  String get recoveryServiceCompact;

  /// No description provided for @recoveryCachedCompact.
  ///
  /// In ar, this message translates to:
  /// **'البيانات المحفوظة'**
  String get recoveryCachedCompact;

  /// No description provided for @recoverySyncingCompact.
  ///
  /// In ar, this message translates to:
  /// **'جارٍ المزامنة'**
  String get recoverySyncingCompact;

  /// No description provided for @recoveryRefreshAction.
  ///
  /// In ar, this message translates to:
  /// **'مزامنة وتحديث'**
  String get recoveryRefreshAction;

  /// No description provided for @recoveryInspectAction.
  ///
  /// In ar, this message translates to:
  /// **'إعادة قراءة الحالة'**
  String get recoveryInspectAction;

  /// No description provided for @recoveryDetailsAction.
  ///
  /// In ar, this message translates to:
  /// **'عرض الأدلة المحفوظة'**
  String get recoveryDetailsAction;

  /// No description provided for @recoveryPendingBanner.
  ///
  /// In ar, this message translates to:
  /// **'عمليات بانتظار المزامنة: {count}'**
  String recoveryPendingBanner(String count);

  /// No description provided for @recoveryBlockedBanner.
  ///
  /// In ar, this message translates to:
  /// **'عمليات تحتاج استرداداً: {count}'**
  String recoveryBlockedBanner(String count);

  /// No description provided for @recoveryCombinedBanner.
  ///
  /// In ar, this message translates to:
  /// **'بانتظار المزامنة: {pending} • تحتاج استرداداً: {blocked}'**
  String recoveryCombinedBanner(String pending, String blocked);

  /// No description provided for @recoveryDetailsHint.
  ///
  /// In ar, this message translates to:
  /// **'اضغط لعرض التفاصيل.'**
  String get recoveryDetailsHint;

  /// No description provided for @recoveryPanelTitle.
  ///
  /// In ar, this message translates to:
  /// **'حالة المزامنة والاسترداد'**
  String get recoveryPanelTitle;

  /// No description provided for @recoveryPanelDescription.
  ///
  /// In ar, this message translates to:
  /// **'السجلات المعلقة والمحجوبة دليل محفوظ. لا تُحذف لمجرد إخفاء الخطأ.'**
  String get recoveryPanelDescription;

  /// No description provided for @recoveryPendingSection.
  ///
  /// In ar, this message translates to:
  /// **'بانتظار المزامنة'**
  String get recoveryPendingSection;

  /// No description provided for @recoveryBlockedSection.
  ///
  /// In ar, this message translates to:
  /// **'تحتاج استرداداً'**
  String get recoveryBlockedSection;

  /// No description provided for @recoveryPendingState.
  ///
  /// In ar, this message translates to:
  /// **'معلّقة'**
  String get recoveryPendingState;

  /// No description provided for @recoveryBlockedState.
  ///
  /// In ar, this message translates to:
  /// **'محجوبة'**
  String get recoveryBlockedState;

  /// No description provided for @recoveryOperationLabel.
  ///
  /// In ar, this message translates to:
  /// **'العملية'**
  String get recoveryOperationLabel;

  /// No description provided for @recoveryCommandIdLabel.
  ///
  /// In ar, this message translates to:
  /// **'معرّف الأمر'**
  String get recoveryCommandIdLabel;

  /// No description provided for @recoveryLocalRecordLabel.
  ///
  /// In ar, this message translates to:
  /// **'السجل المحلي'**
  String get recoveryLocalRecordLabel;

  /// No description provided for @recoveryAttemptsLabel.
  ///
  /// In ar, this message translates to:
  /// **'عدد المحاولات'**
  String get recoveryAttemptsLabel;

  /// No description provided for @recoveryErrorCodeLabel.
  ///
  /// In ar, this message translates to:
  /// **'رمز الخطأ'**
  String get recoveryErrorCodeLabel;

  /// No description provided for @recoveryRequestIdLabel.
  ///
  /// In ar, this message translates to:
  /// **'رقم التتبع'**
  String get recoveryRequestIdLabel;

  /// No description provided for @recoveryCreatedAtLabel.
  ///
  /// In ar, this message translates to:
  /// **'التاريخ'**
  String get recoveryCreatedAtLabel;

  /// No description provided for @recoveryVisitLabel.
  ///
  /// In ar, this message translates to:
  /// **'الزيارة'**
  String get recoveryVisitLabel;

  /// No description provided for @recoveryTransferLabel.
  ///
  /// In ar, this message translates to:
  /// **'الحوالة'**
  String get recoveryTransferLabel;

  /// No description provided for @recoveryReferenceLabel.
  ///
  /// In ar, this message translates to:
  /// **'مرجع'**
  String get recoveryReferenceLabel;

  /// No description provided for @recoveryReasonLabel.
  ///
  /// In ar, this message translates to:
  /// **'التفصيل'**
  String get recoveryReasonLabel;

  /// No description provided for @recoveryMissingValue.
  ///
  /// In ar, this message translates to:
  /// **'غير متوفر'**
  String get recoveryMissingValue;

  /// No description provided for @recoveryNoRecoveryItems.
  ///
  /// In ar, this message translates to:
  /// **'لا توجد عمليات معلقة أو محجوبة.'**
  String get recoveryNoRecoveryItems;

  /// No description provided for @recoveryReadUnavailable.
  ///
  /// In ar, this message translates to:
  /// **'تعذر قراءة حالة المزامنة المحلية. لم يتم افتراض أنها فارغة.'**
  String get recoveryReadUnavailable;

  /// No description provided for @recoverySyncInProgress.
  ///
  /// In ar, this message translates to:
  /// **'جاري مزامنة العمليات المحفوظة…'**
  String get recoverySyncInProgress;

  /// No description provided for @recoverySyncSuccess.
  ///
  /// In ar, this message translates to:
  /// **'تمت المزامنة بالكامل.'**
  String get recoverySyncSuccess;

  /// No description provided for @recoverySyncIncomplete.
  ///
  /// In ar, this message translates to:
  /// **'المزامنة غير مكتملة؛ ما زالت هناك عمليات معلقة.'**
  String get recoverySyncIncomplete;

  /// No description provided for @recoverySyncRecoveryRequired.
  ///
  /// In ar, this message translates to:
  /// **'توجد عمليات محجوبة تحتاج استرداداً قبل اعتبار المزامنة مكتملة.'**
  String get recoverySyncRecoveryRequired;

  /// No description provided for @recoverySyncConnectivityUnresolved.
  ///
  /// In ar, this message translates to:
  /// **'تعذر الاتصال أثناء المزامنة. السجلات المحلية ما زالت محفوظة.'**
  String get recoverySyncConnectivityUnresolved;

  /// No description provided for @recoverySyncTimedOut.
  ///
  /// In ar, this message translates to:
  /// **'انتهت مهلة المزامنة قبل تأكيد النتيجة. السجلات المحلية ما زالت محفوظة.'**
  String get recoverySyncTimedOut;

  /// No description provided for @recoverySyncUnresolved.
  ///
  /// In ar, this message translates to:
  /// **'تعذر تأكيد نتيجة المزامنة. حالة السجلات المحلية ما زالت محفوظة.'**
  String get recoverySyncUnresolved;

  /// No description provided for @recoverySubmitSale.
  ///
  /// In ar, this message translates to:
  /// **'زيارة / فاتورة'**
  String get recoverySubmitSale;

  /// No description provided for @recoveryTransferResponse.
  ///
  /// In ar, this message translates to:
  /// **'رد حوالة'**
  String get recoveryTransferResponse;

  /// No description provided for @recoveryLegacyBreak.
  ///
  /// In ar, this message translates to:
  /// **'استراحة قديمة'**
  String get recoveryLegacyBreak;

  /// No description provided for @recoveryCorrupt.
  ///
  /// In ar, this message translates to:
  /// **'سجل غير صالح'**
  String get recoveryCorrupt;

  /// No description provided for @recoveryUnknownOperation.
  ///
  /// In ar, this message translates to:
  /// **'عملية غير معروفة'**
  String get recoveryUnknownOperation;

  /// No description provided for @recoveryReadOnlyNotice.
  ///
  /// In ar, this message translates to:
  /// **'السجلات المحجوبة للقراءة فقط في هذه المرحلة ولا يوجد حذف شامل.'**
  String get recoveryReadOnlyNotice;

  /// No description provided for @homeTodayRoute.
  ///
  /// In ar, this message translates to:
  /// **'جولة اليوم'**
  String get homeTodayRoute;

  /// No description provided for @homeCompletedLabel.
  ///
  /// In ar, this message translates to:
  /// **'مكتملة'**
  String get homeCompletedLabel;

  /// No description provided for @homeRemainingLabel.
  ///
  /// In ar, this message translates to:
  /// **'متبقية'**
  String get homeRemainingLabel;

  /// No description provided for @homeSalesLabel.
  ///
  /// In ar, this message translates to:
  /// **'مبيعات'**
  String get homeSalesLabel;

  /// No description provided for @homeAwaitingSync.
  ///
  /// In ar, this message translates to:
  /// **'{count} زيارة بانتظار المزامنة'**
  String homeAwaitingSync(String count);

  /// No description provided for @homeCashReceived.
  ///
  /// In ar, this message translates to:
  /// **'إجمالي الكاش المستلم'**
  String get homeCashReceived;

  /// No description provided for @homeCashSales.
  ///
  /// In ar, this message translates to:
  /// **'مبيعات نقدية'**
  String get homeCashSales;

  /// No description provided for @homeDebtCollections.
  ///
  /// In ar, this message translates to:
  /// **'تحصيل ذمم'**
  String get homeDebtCollections;

  /// No description provided for @homeDebtOperations.
  ///
  /// In ar, this message translates to:
  /// **'{count} عملية'**
  String homeDebtOperations(String count);

  /// No description provided for @workSessionReadyStatus.
  ///
  /// In ar, this message translates to:
  /// **'جاهز للبدء'**
  String get workSessionReadyStatus;

  /// No description provided for @workSessionActiveStatus.
  ///
  /// In ar, this message translates to:
  /// **'العمل جارٍ'**
  String get workSessionActiveStatus;

  /// No description provided for @workSessionBreakStatus.
  ///
  /// In ar, this message translates to:
  /// **'في استراحة'**
  String get workSessionBreakStatus;

  /// No description provided for @workSessionReadyTitle.
  ///
  /// In ar, this message translates to:
  /// **'ابدأ يومك'**
  String get workSessionReadyTitle;

  /// No description provided for @workSessionActiveTitle.
  ///
  /// In ar, this message translates to:
  /// **'الجولة مستمرة'**
  String get workSessionActiveTitle;

  /// No description provided for @workSessionBreakTitle.
  ///
  /// In ar, this message translates to:
  /// **'أنت في استراحة'**
  String get workSessionBreakTitle;

  /// No description provided for @workSessionReadyHint.
  ///
  /// In ar, this message translates to:
  /// **'ابدأ جلسة العمل عندما تكون جاهزًا للانطلاق.'**
  String get workSessionReadyHint;

  /// No description provided for @workSessionActiveHint.
  ///
  /// In ar, this message translates to:
  /// **'جلسة العمل الحالية فعّالة وحالة اليوم مستمرة.'**
  String get workSessionActiveHint;

  /// No description provided for @workSessionBreakHint.
  ///
  /// In ar, this message translates to:
  /// **'الجلسة محفوظة. أنهِ الاستراحة عندما تكون جاهزًا للمتابعة.'**
  String get workSessionBreakHint;

  /// No description provided for @workSessionStartUnknown.
  ///
  /// In ar, this message translates to:
  /// **'وقت بدء الجلسة غير متوفر.'**
  String get workSessionStartUnknown;

  /// No description provided for @workSessionStartedAt.
  ///
  /// In ar, this message translates to:
  /// **'بدأت {time}'**
  String workSessionStartedAt(String time);

  /// No description provided for @workSessionElapsed.
  ///
  /// In ar, this message translates to:
  /// **'مضى {duration}'**
  String workSessionElapsed(String duration);

  /// No description provided for @workSessionStartAction.
  ///
  /// In ar, this message translates to:
  /// **'بدء العمل'**
  String get workSessionStartAction;

  /// No description provided for @workSessionEndAction.
  ///
  /// In ar, this message translates to:
  /// **'إنهاء العمل'**
  String get workSessionEndAction;

  /// No description provided for @workSessionStartBreakAction.
  ///
  /// In ar, this message translates to:
  /// **'بدء الاستراحة'**
  String get workSessionStartBreakAction;

  /// No description provided for @workSessionEndBreakAction.
  ///
  /// In ar, this message translates to:
  /// **'إنهاء الاستراحة'**
  String get workSessionEndBreakAction;

  /// No description provided for @workSessionConfirmStartTitle.
  ///
  /// In ar, this message translates to:
  /// **'بدء العمل؟'**
  String get workSessionConfirmStartTitle;

  /// No description provided for @workSessionConfirmStartBody.
  ///
  /// In ar, this message translates to:
  /// **'هل تريد بدء جلسة عمل جديدة؟'**
  String get workSessionConfirmStartBody;

  /// No description provided for @workSessionConfirmEndTitle.
  ///
  /// In ar, this message translates to:
  /// **'إنهاء العمل؟'**
  String get workSessionConfirmEndTitle;

  /// No description provided for @workSessionConfirmEndBody.
  ///
  /// In ar, this message translates to:
  /// **'هل تريد إنهاء جلسة العمل الحالية؟'**
  String get workSessionConfirmEndBody;

  /// No description provided for @workSessionStartSuccess.
  ///
  /// In ar, this message translates to:
  /// **'تم بدء جلسة العمل.'**
  String get workSessionStartSuccess;

  /// No description provided for @workSessionEndSuccess.
  ///
  /// In ar, this message translates to:
  /// **'تم إنهاء جلسة العمل.'**
  String get workSessionEndSuccess;

  /// No description provided for @workSessionBreakStartSuccess.
  ///
  /// In ar, this message translates to:
  /// **'تم بدء الاستراحة (مسجلة على السيرفر).'**
  String get workSessionBreakStartSuccess;

  /// No description provided for @workSessionBreakEndSuccess.
  ///
  /// In ar, this message translates to:
  /// **'تم إنهاء الاستراحة (مسجلة على السيرفر).'**
  String get workSessionBreakEndSuccess;

  /// No description provided for @workSessionStartReconciled.
  ///
  /// In ar, this message translates to:
  /// **'تم تأكيد أن جلسة العمل نشطة بعد مطابقة حالتها مع السيرفر.'**
  String get workSessionStartReconciled;

  /// No description provided for @workSessionEndReconciled.
  ///
  /// In ar, this message translates to:
  /// **'تم تأكيد انتهاء جلسة العمل بعد مطابقة حالتها مع السيرفر.'**
  String get workSessionEndReconciled;

  /// No description provided for @workSessionBreakStartReconciled.
  ///
  /// In ar, this message translates to:
  /// **'تم تأكيد بدء الاستراحة بعد مطابقة حالتها مع السيرفر.'**
  String get workSessionBreakStartReconciled;

  /// No description provided for @workSessionBreakEndReconciled.
  ///
  /// In ar, this message translates to:
  /// **'تم تأكيد انتهاء الاستراحة بعد مطابقة حالتها مع السيرفر.'**
  String get workSessionBreakEndReconciled;

  /// No description provided for @workSessionUnresolved.
  ///
  /// In ar, this message translates to:
  /// **'تعذر تأكيد نتيجة العملية. حدّث البيانات قبل المحاولة مجدداً.'**
  String get workSessionUnresolved;

  /// No description provided for @workSessionAuthRejected.
  ///
  /// In ar, this message translates to:
  /// **'انتهت صلاحية الجلسة أو لا تملك صلاحية تنفيذ العملية.'**
  String get workSessionAuthRejected;

  /// No description provided for @workSessionBusinessRejected.
  ///
  /// In ar, this message translates to:
  /// **'رفض السيرفر العملية بسبب حالة العمل الحالية.'**
  String get workSessionBusinessRejected;

  /// No description provided for @workSessionRateLimited.
  ///
  /// In ar, this message translates to:
  /// **'عدد الطلبات مرتفع حالياً. أعد المحاولة بعد قليل.'**
  String get workSessionRateLimited;

  /// No description provided for @workSessionNetworkUnresolved.
  ///
  /// In ar, this message translates to:
  /// **'تعذر تأكيد نتيجة العملية بسبب الاتصال. تم الحفاظ على حالة السيرفر كمرجع وحيد.'**
  String get workSessionNetworkUnresolved;

  /// No description provided for @workSessionTimeoutUnresolved.
  ///
  /// In ar, this message translates to:
  /// **'انتهت مهلة الاتصال قبل تأكيد نتيجة العملية. حالة السيرفر ما زالت المرجع الوحيد.'**
  String get workSessionTimeoutUnresolved;

  /// No description provided for @workSessionServerUnresolved.
  ///
  /// In ar, this message translates to:
  /// **'تعذر تأكيد نتيجة العملية بسبب خطأ في السيرفر.'**
  String get workSessionServerUnresolved;

  /// No description provided for @workSessionRequestIdLabel.
  ///
  /// In ar, this message translates to:
  /// **'رقم التتبع'**
  String get workSessionRequestIdLabel;

  /// No description provided for @workSessionStatusCodeLabel.
  ///
  /// In ar, this message translates to:
  /// **'رمز الحالة'**
  String get workSessionStatusCodeLabel;

  /// No description provided for @workSessionServerDetailLabel.
  ///
  /// In ar, this message translates to:
  /// **'تفصيل السيرفر'**
  String get workSessionServerDetailLabel;

  /// No description provided for @workSessionIssueAuthentication.
  ///
  /// In ar, this message translates to:
  /// **'يلزم تأكيد تسجيل الدخول قبل تنفيذ إجراء الجلسة.'**
  String get workSessionIssueAuthentication;

  /// No description provided for @workSessionIssueInvalidStartEvidence.
  ///
  /// In ar, this message translates to:
  /// **'بيانات بدء العمل التي وصلت للسيرفر غير صالحة. حدّث البيانات ثم أعد المحاولة.'**
  String get workSessionIssueInvalidStartEvidence;

  /// No description provided for @workSessionIssueVehicleCustody.
  ///
  /// In ar, this message translates to:
  /// **'عهدة السيارة التشغيلية غير جاهزة لبدء العمل. راجع مسؤول التوزيع أو العهدة.'**
  String get workSessionIssueVehicleCustody;

  /// No description provided for @workSessionIssueStartPrerequisite.
  ///
  /// In ar, this message translates to:
  /// **'السيرفر رفض بدء العمل بسبب متطلب تشغيلي في خط السير أو السيارة أو العهدة. راجع مسؤول التوزيع ثم أعد المحاولة.'**
  String get workSessionIssueStartPrerequisite;

  /// No description provided for @workSessionIssueEndPrerequisite.
  ///
  /// In ar, this message translates to:
  /// **'السيرفر رفض إنهاء العمل بسبب متطلب تشغيلي قائم. عالج الاستراحة أو الحوالات المعلقة الظاهرة ثم أعد المحاولة.'**
  String get workSessionIssueEndPrerequisite;

  /// No description provided for @workSessionIssueBreakState.
  ///
  /// In ar, this message translates to:
  /// **'حالة الاستراحة على السيرفر لا تسمح بهذا الإجراء. حدّث حالة الجلسة ثم أعد المحاولة.'**
  String get workSessionIssueBreakState;

  /// No description provided for @workSessionIssueRateLimited.
  ///
  /// In ar, this message translates to:
  /// **'تم تأجيل إجراء الجلسة بسبب حد الطلبات. أعد المحاولة بعد قليل.'**
  String get workSessionIssueRateLimited;

  /// No description provided for @workSessionIssueConnectivity.
  ///
  /// In ar, this message translates to:
  /// **'تعذر الاتصال بالسيرفر. تحقق من الشبكة وحدّث حالة الجلسة قبل إعادة المحاولة.'**
  String get workSessionIssueConnectivity;

  /// No description provided for @workSessionIssueTimeout.
  ///
  /// In ar, this message translates to:
  /// **'انتهت مهلة الاتصال قبل تأكيد النتيجة. حدّث حالة الجلسة قبل إعادة المحاولة.'**
  String get workSessionIssueTimeout;

  /// No description provided for @workSessionIssueUnresolved.
  ///
  /// In ar, this message translates to:
  /// **'لم يتم تأكيد نتيجة إجراء الجلسة. حالة السيرفر هي المرجع؛ حدّث البيانات قبل إعادة المحاولة.'**
  String get workSessionIssueUnresolved;
}

class _AppLocalizationsDelegate extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) => <String>['ar', 'en'].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {


  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'ar': return AppLocalizationsAr();
    case 'en': return AppLocalizationsEn();
  }

  throw FlutterError(
    'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
    'an issue with the localizations generation tool. Please file an issue '
    'on GitHub with a reproducible sample app and the gen-l10n configuration '
    'that was used.'
  );
}
