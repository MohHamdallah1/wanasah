import '../../../services/location_failure.dart';

/// Translation keys are typed device states, never exception text.
String shopLocationFailureMessage(LocationFailureKind kind,
    {required String languageCode}) =>
    (languageCode == 'ar' ? _ar : _en)[kind]!;

const _ar = {
  LocationFailureKind.serviceDisabled: 'الرجاء تفعيل خدمات الموقع (GPS) في جهازك.',
  LocationFailureKind.permissionDenied: 'تم رفض إذن الوصول للموقع.',
  LocationFailureKind.permissionDeniedForever: 'صلاحية الموقع مرفوضة نهائياً. يرجى تفعيلها من إعدادات التطبيق.',
  LocationFailureKind.timeout: 'فشل الاتصال بالـ GPS (Timeout). حاول في مكان مفتوح.',
  LocationFailureKind.mockedLocation: 'تحذير أمني: يرجى إيقاف تطبيقات تزوير الموقع (Fake GPS).',
  LocationFailureKind.unexpected: 'حدث خطأ غير متوقع في تحديد الموقع.',
};
const _en = {
  LocationFailureKind.serviceDisabled: 'Enable device location services (GPS).',
  LocationFailureKind.permissionDenied: 'Location permission was denied.',
  LocationFailureKind.permissionDeniedForever: 'Enable location permission in app settings.',
  LocationFailureKind.timeout: 'Location timed out. Try again in an open area.',
  LocationFailureKind.mockedLocation: 'Turn off mock location applications.',
  LocationFailureKind.unexpected: 'An unexpected location error occurred.',
};
