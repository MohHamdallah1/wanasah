import 'package:flutter_dotenv/flutter_dotenv.dart';

class ApiConstants {
  static String get baseUrl {
    // +++ الدرع الشبكي: منع اتصال التطبيق بفراغ في حال كان المتغير موجوداً ولكنه فارغ +++
    final String? url = dotenv.env['API_BASE_URL'];
    return (url != null && url.trim().isNotEmpty) ? url.trim() : 'http://10.0.2.2:5000';
  }
}
