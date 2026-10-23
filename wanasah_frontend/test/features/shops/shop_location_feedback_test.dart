import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/services/location_failure.dart';
import 'package:wanasah_frontend/features/shops/presentation/shop_location_feedback.dart';

void main() {
  for (final entry in {
    LocationFailureKind.serviceDisabled: 'الرجاء تفعيل خدمات الموقع (GPS) في جهازك.',
    LocationFailureKind.permissionDenied: 'تم رفض إذن الوصول للموقع.',
    LocationFailureKind.permissionDeniedForever: 'صلاحية الموقع مرفوضة نهائياً. يرجى تفعيلها من إعدادات التطبيق.',
    LocationFailureKind.timeout: 'فشل الاتصال بالـ GPS (Timeout). حاول في مكان مفتوح.',
    LocationFailureKind.mockedLocation: 'تحذير أمني: يرجى إيقاف تطبيقات تزوير الموقع (Fake GPS).',
    LocationFailureKind.unexpected: 'حدث خطأ غير متوقع في تحديد الموقع.',
  }.entries) {
    test('typed ${entry.key.name} uses its translation key', () {
      expect(shopLocationFailureMessage(entry.key, languageCode: 'ar'), entry.value);
      expect(shopLocationFailureMessage(entry.key, languageCode: 'en'), isNotEmpty);
    });
  }
  test('screen maps only typed failures and retains accepted Shop/route contracts', () {
    final source = File('lib/screens/add_shop_screen.dart').readAsStringSync();
    expect(source, contains('error is LocationFailure'));
    expect(source, contains('shopLocationFailureMessage(failure.kind'));
    expect(source, isNot(contains('errStr')));
    expect(source, isNot(contains('.contains(')));
    expect(source, isNot(contains('FlutterSecureStorage')));
    expect(source, contains('_pendingShopCommand ??= _shopCreationService.prepare('));
    expect(source, contains('_shopCreationService.execute(command)'));
    expect(source, contains("locationText.startsWith('Lat:')"));
  });
}
