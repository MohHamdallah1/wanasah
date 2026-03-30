import 'package:flutter_dotenv/flutter_dotenv.dart';

class ApiConstants {
  static String get baseUrl {
    // قراءة الرابط من ملف .env، وإذا لم يوجد لأي سبب نضع الرابط الافتراضي للحماية من الانهيار
    return dotenv.env['API_BASE_URL'] ?? 'http://10.0.2.2:5000';
  }
}
