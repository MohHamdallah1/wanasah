import 'package:flutter/widgets.dart';

enum AppCopyKey {
  dashboardConnectivityCached,
  dashboardServiceCached,
  dashboardGenericError,
  retry,
  home,
  route,
  custody,
  brand,
  account,
  refresh,
  logout,
  logoutTitle,
  logoutPrompt,
  cancel,
  confirm,
  greeting,
  region,
  today,
  routeSummary,
  completedVisits,
  salesVisits,
  pendingVisits,
  offlineVisits,
  financialSummary,
  salesCash,
  debtCash,
  totalCash,
  openRoute,
  openCustody,
  pendingTransfers,
}

class AppCopy {
  static const Map<AppCopyKey, String> _ar = {
    AppCopyKey.dashboardConnectivityCached:
        'تعذر الوصول إلى النظام مؤقتًا. نعرض آخر بيانات محفوظة ويمكنك المحاولة مجددًا.',
    AppCopyKey.dashboardServiceCached:
        'تعذر تحديث البيانات بسبب مشكلة مؤقتة في الخدمة. بياناتك المحفوظة ما زالت متاحة.',
    AppCopyKey.dashboardGenericError:
        'تعذر تحميل هذه البيانات الآن. حاول مرة أخرى، وإذا استمرت المشكلة تواصل مع الدعم.',
    AppCopyKey.retry: 'إعادة المحاولة',
    AppCopyKey.home: 'الرئيسية',
    AppCopyKey.route: 'خط السير',
    AppCopyKey.custody: 'العهدة',
    AppCopyKey.brand: 'وناسة',
    AppCopyKey.account: 'الحساب',
    AppCopyKey.refresh: 'تحديث البيانات',
    AppCopyKey.logout: 'تسجيل الخروج',
    AppCopyKey.logoutTitle: 'تأكيد الخروج',
    AppCopyKey.logoutPrompt: 'هل تريد تسجيل الخروج؟',
    AppCopyKey.cancel: 'إلغاء',
    AppCopyKey.confirm: 'نعم، تأكيد',
    AppCopyKey.greeting: 'أهلاً بك، {name}!',
    AppCopyKey.region: 'المنطقة المخصصة: {region}',
    AppCopyKey.today: 'تاريخ اليوم: {date}',
    AppCopyKey.routeSummary: 'ملخص الجولة',
    AppCopyKey.completedVisits: 'الزيارات المكتملة: {count}',
    AppCopyKey.salesVisits: 'الزيارات الناجحة (مبيعات): {count}',
    AppCopyKey.pendingVisits: 'الزيارات المعلقة: {count}',
    AppCopyKey.offlineVisits: 'بانتظار المزامنة: {count}',
    AppCopyKey.financialSummary: 'الملخص المالي',
    AppCopyKey.salesCash: 'إجمالي كاش المبيعات: {amount}',
    AppCopyKey.debtCash: 'إجمالي الذمم المحصلة: ({count}) {amount}',
    AppCopyKey.totalCash: 'إجمالي الكاش المستلم: {amount}',
    AppCopyKey.openRoute: 'عرض قائمة زيارات اليوم',
    AppCopyKey.openCustody: 'عرض العهدة',
    AppCopyKey.pendingTransfers: 'مراجعة الحوالات المعلقة',
  };

  static const Map<AppCopyKey, String> _en = {
    AppCopyKey.dashboardConnectivityCached:
        'The service is temporarily unreachable. Saved data remains available.',
    AppCopyKey.dashboardServiceCached:
        'The service could not refresh your data. Saved data remains available.',
    AppCopyKey.dashboardGenericError:
        'Unable to load this data. Try again or contact support.',
    AppCopyKey.retry: 'Try again',
    AppCopyKey.home: 'Home',
    AppCopyKey.route: 'Route',
    AppCopyKey.custody: 'Custody',
    AppCopyKey.brand: 'Wanasah',
    AppCopyKey.account: 'Account',
    AppCopyKey.refresh: 'Refresh data',
    AppCopyKey.logout: 'Sign out',
    AppCopyKey.logoutTitle: 'Confirm sign out',
    AppCopyKey.logoutPrompt: 'Do you want to sign out?',
    AppCopyKey.cancel: 'Cancel',
    AppCopyKey.confirm: 'Confirm',
    AppCopyKey.greeting: 'Welcome, {name}!',
    AppCopyKey.region: 'Assigned region: {region}',
    AppCopyKey.today: 'Today: {date}',
    AppCopyKey.routeSummary: 'Route summary',
    AppCopyKey.completedVisits: 'Completed visits: {count}',
    AppCopyKey.salesVisits: 'Visits with sales: {count}',
    AppCopyKey.pendingVisits: 'Pending visits: {count}',
    AppCopyKey.offlineVisits: 'Awaiting sync: {count}',
    AppCopyKey.financialSummary: 'Financial summary',
    AppCopyKey.salesCash: 'Sales cash: {amount}',
    AppCopyKey.debtCash: 'Debt collections: ({count}) {amount}',
    AppCopyKey.totalCash: 'Total cash received: {amount}',
    AppCopyKey.openRoute: "View today's visits",
    AppCopyKey.openCustody: 'View custody',
    AppCopyKey.pendingTransfers: 'Review pending transfers',
  };

  static String of(
    BuildContext context,
    AppCopyKey key, {
    Map<String, String> values = const {},
  }) {
    final languageCode = Localizations.localeOf(context).languageCode;
    var text = (languageCode == 'en' ? _en : _ar)[key]!;
    for (final entry in values.entries) {
      text = text.replaceAll('{${entry.key}}', entry.value);
    }
    return text;
  }
}
