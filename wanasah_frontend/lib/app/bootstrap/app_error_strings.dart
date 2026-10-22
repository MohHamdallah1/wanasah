enum AppErrorStringKey {
  criticalSystemError,
}

const Map<AppErrorStringKey, String> _ar = <AppErrorStringKey, String>{
  AppErrorStringKey.criticalSystemError:
      'حدث خطأ حرج في النظام.\nيرجى التواصل مع الدعم الفني.',
};

const Map<AppErrorStringKey, String> _en = <AppErrorStringKey, String>{
  AppErrorStringKey.criticalSystemError:
      'A critical system error occurred.\nPlease contact technical support.',
};

String appErrorString(
  AppErrorStringKey key, {
  String localeCode = 'ar',
}) {
  final language = localeCode.split(RegExp('[-_]')).first.toLowerCase();
  return (language == 'en' ? _en : _ar)[key] ?? _ar[key]!;
}
