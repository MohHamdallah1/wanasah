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

// ─── تسجيل الدخول بعد نجاح API Login ───────────────────────────────────────
/// يُرسَل من LoginScreen بعد استلام token و driverId من السيرفر.
class LoginEvent extends AuthEvent {
  final String token;
  final int driverId;

  const LoginEvent({required this.token, required this.driverId});

  @override
  List<Object?> get props => [token, driverId];
}

// ─── تسجيل الخروج ───────────────────────────────────────────────────────────
/// يُرسَل من أي شاشة (أو من AuthInterceptor عبر 401) لمسح الجلسة.
class LogoutEvent extends AuthEvent {
  const LogoutEvent();
}
