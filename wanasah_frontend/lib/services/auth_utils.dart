// File: lib/utils/auth_utils.dart

import 'package:flutter/material.dart'; // نحتاجه لـ BuildContext و Navigator و ScaffoldMessenger
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'dart:developer' as developer;
// استيراد شاشة الدخول - اضبط المسار إذا كان مختلفاً
import '../screens/login_screen.dart'; // افترض أن login_screen.dart موجود في مجلد screens

// تعريف كائن التخزين مرة واحدة هنا
const _storage = FlutterSecureStorage();
const String _authTokenKey = 'auth_token';

// دالة للحصول على الهيدرز مع التوكن
Future<Map<String, String>> getAuthenticatedHeaders({bool needsContentType = true}) async {
  final String? token = await _storage.read(key: _authTokenKey);
  final Map<String, String> headers = {};
  if (needsContentType) {
    headers['Content-Type'] = 'application/json; charset=UTF-8';
  }
  if (token != null) {
    headers['Authorization'] = 'Bearer $token';
    // developer.log('Auth Header Added by Util.'); // يمكنك إلغاء التعليق للتحقق
  } else {
     developer.log('Util: Token not found, Auth header not added.');
  }
  return headers;
}

// دالة للتعامل مع خطأ 401 (تحتاج BuildContext)
Future<void> handleUnauthorized(BuildContext context) async {
  // قد يكون من الأفضل التحقق من mounted قبل استدعاء هذه الدالة
  // في المكان الذي تستدعيها منه
  await _storage.delete(key: _authTokenKey);
  await _storage.delete(key: 'driver_id');
  developer.log('Util: Token deleted due to 401 Unauthorized.');

  // التأكد أن context لا يزال صالحاً قبل الانتقال (مهم بعد await)
  if (context.mounted) {
      Navigator.of(context).pushAndRemoveUntil(
        // تأكد من استخدام const إذا كانت LoginScreen لا تأخذ معاملات
        MaterialPageRoute(builder: (context) => const LoginScreen()),
        (Route<dynamic> route) => false, // إزالة كل الشاشات السابقة
      );
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('انتهت صلاحية الجلسة، يرجى تسجيل الدخول مرة أخرى.'), backgroundColor: Colors.orange),
      );
  } else {
     developer.log("Util: Context was unmounted before navigation in handleUnauthorized.");
  }
}