import 'package:flutter/foundation.dart'; // +++ لمعرفة بيئة التطبيق (Debug/Release) +++
import 'package:flutter_dotenv/flutter_dotenv.dart';

class ApiConstants {
  static String get baseUrl {
    final String? envUrl = dotenv.env['API_BASE_URL'];

    if (envUrl != null && envUrl.trim().isNotEmpty) {
      // +++  1: نسف ثغرة الـ Double Slash بإزالة كل السلاشات المتتالية في نهاية الرابط +++
      return envUrl.trim().replaceAll(RegExp(r'/+$'), '');
    }

    // +++  2: منع التطبيق من البحث عن راوتر بيتك إذا تم رفعه للإنتاج وفشل الـ env +++
    if (kReleaseMode) {
      // إما أن تضع الرابط الحي (Production URL) المباشر هنا، أو ترمي خطأ صريح لمنع التطبيق من العمل بشكل وهمي
      throw Exception('FATAL ERROR: API_BASE_URL is missing in Release environment!');
      // return 'https://api.wanasah.com'; // (يفضل وضع الرابط الحقيقي كحماية أخيرة)
    }

    // بيئة التطوير (Debug) فقط هي من يسمح لها بالاتصال بالـ IP المحلي
    return 'http://192.168.1.115:8000';
  }
}