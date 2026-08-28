import 'package:geolocator/geolocator.dart';
import 'dart:developer' as developer;
import 'dart:async';

class LocationService {
  // تطبيق نمط الـ Singleton لمنع استهلاك الذاكرة
  static final LocationService instance = LocationService._internal();
  LocationService._internal();

  Future<Position?> getCurrentLocation() async {
    bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) throw Exception('GPS_DISABLED'); // +++ الكي الجراحي لـ Bug 5: إجبار المندوب +++
    
    LocationPermission permission = await Geolocator.checkPermission();
    
    // +++ LOC-1: إيقاف الفحص مبكراً لمنع تضليل المندوب برسالة "GPS_TIMEOUT" الخاطئة +++
    if (permission == LocationPermission.deniedForever) {
      throw Exception('GPS_DENIED_FOREVER'); 
    }
    
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied) {
        throw Exception('GPS_DENIED');
      }
      if (permission == LocationPermission.deniedForever) {
        throw Exception('GPS_DENIED_FOREVER');
      }
    }
    
    try {
      Position? lastPosition = await Geolocator.getLastKnownPosition();
      
      // +++ الدرع الأمني: فضح تطبيقات تزوير الموقع (Fake GPS) لحماية النظام +++
      if (lastPosition != null && lastPosition.isMocked) {
        throw Exception('FAKE_GPS_DETECTED');
      }

      if (lastPosition != null && DateTime.now().difference(lastPosition.timestamp).abs().inSeconds < 60) {
        return lastPosition;
      }
      
      Position currentPosition = await Geolocator.getCurrentPosition(desiredAccuracy: LocationAccuracy.high)
          .timeout(const Duration(seconds: 8));
          
      // +++ الدرع الأمني: التحقق من الموقع الجديد +++
      if (currentPosition.isMocked) {
        throw Exception('FAKE_GPS_DETECTED');
      }
      return currentPosition;
    } on TimeoutException {
      developer.log('[LocationService] Location request timed out.');
      throw Exception('GPS_TIMEOUT');
    } on LocationServiceDisabledException {
      developer.log('[LocationService] GPS turned off during request.');
      throw Exception('GPS_DISABLED');
    } on PermissionDeniedException {
      developer.log('[LocationService] Permission revoked during request.');
      throw Exception('GPS_DENIED');
    } catch (e) {
      developer.log('[LocationService] Error getting location: $e');
      if (e.toString().contains('FAKE_GPS_DETECTED')) {
        // +++ الكي الجراحي: رمي الرمز الخام ليتم ترجمته في الـ BLoC أو الشاشة (GPS-P1) +++
        throw Exception('FAKE_GPS_DETECTED');
      }
      // رمي الخطأ الفعلي كما هو للواجهة إذا كان غير معروف، بدلاً من طمسه كـ TIMEOUT
      throw Exception(e.toString());
    }
  }
}