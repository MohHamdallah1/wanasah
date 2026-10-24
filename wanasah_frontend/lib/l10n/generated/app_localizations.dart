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
