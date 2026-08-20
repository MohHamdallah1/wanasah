import 'package:geolocator/geolocator.dart';
import 'dart:developer' as developer;

class LocationService {
  // تطبيق نمط الـ Singleton لمنع استهلاك الذاكرة
  static final LocationService instance = LocationService._internal();
  LocationService._internal();

  Future<Position?> getCurrentLocation() async {
    bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) throw Exception('GPS_DISABLED'); // +++ الكي الجراحي لـ Bug 5: إجبار المندوب +++
    
    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied || permission == LocationPermission.deniedForever) {
        throw Exception('GPS_DENIED'); // +++ الكي الجراحي لـ Bug 5: إجبار المندوب +++
      }
    }
    
    try {
      Position? lastPosition = await Geolocator.getLastKnownPosition();
      // +++ الكي الجراحي لـ Bug 4: استخدام abs() لمنع ثغرة تزوير وقت الهاتف (Future Timestamp) +++
      if (lastPosition != null && DateTime.now().difference(lastPosition.timestamp).abs().inSeconds < 60) {
        return lastPosition;
      }
      return await Geolocator.getCurrentPosition(desiredAccuracy: LocationAccuracy.high)
          .timeout(const Duration(seconds: 8));
    } catch (e) {
      developer.log('[LocationService] Error getting location: $e');
      throw Exception('GPS_TIMEOUT');
    }
  }
}