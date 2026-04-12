// File: lib/blocs/auth/auth_event.dart
//
// تعريف جميع الأحداث (Events) التي يستطيع الـ AuthBloc استقبالها.

import 'package:equatable/equatable.dart';

abstract class AuthEvent extends Equatable {
  const AuthEvent();

  @override
  List<Object?> get props => [];
}

// ─── فحص حالة التوثيق عند فتح التطبيق ──────────────────────────────────────
/// يُرسَل من SplashScreen عند initState لتحديد الشاشة الأولى.
class CheckAuthEvent extends AuthEvent {
  const CheckAuthEvent();
}

// ─── طلب تسجيل الدخول ───────────────────────────────────────
/// يُرسَل من LoginScreen مع بيانات الدخول، ليقوم العقل المدبر بالاتصال بالسيرفر.
class LoginRequested extends AuthEvent {
  final String username;
  final String password;

  const LoginRequested({required this.username, required this.password});

  @override
  List<Object?> get props => [username, password];
}

// ─── تسجيل الخروج ───────────────────────────────────────────────────────────
/// يُرسَل من أي شاشة (أو من AuthInterceptor عبر 401) لمسح الجلسة.
class LogoutEvent extends AuthEvent {
  const LogoutEvent();
}
