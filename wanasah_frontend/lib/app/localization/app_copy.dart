import 'package:flutter/widgets.dart';

enum AppCopyKey {
  dashboardConnectivityCached,
  dashboardServiceCached,
  dashboardGenericError,
  retry,
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
  };

  static String of(BuildContext context, AppCopyKey key) {
    final languageCode = Localizations.localeOf(context).languageCode;
    switch (languageCode) {
      case 'ar':
      default:
        return _ar[key]!;
    }
  }
}
