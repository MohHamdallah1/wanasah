// File: lib/blocs/auth/auth_state.dart
//
// تعريف جميع الحالات (States) التي يمكن أن يكون عليها AuthBloc.

import 'package:equatable/equatable.dart';

abstract class AuthState extends Equatable {
  const AuthState();

  @override
  List<Object?> get props => [];
}

// ─── الحالة الابتدائية قبل أي فحص ──────────────────────────────────────────
/// الحالة الأولى عند إنشاء الـ BLoC — لا تظهر للمستخدم (SplashScreen تغطيها).
class AuthInitial extends AuthState {
  const AuthInitial();
}

// ─── جاري الفحص أو تسجيل الدخول ────────────────────────────────────────────
/// تظهر فيها SplashScreen بـ CircularProgressIndicator.
class AuthLoading extends AuthState {
  const AuthLoading();
}

// ─── مُوثَّق — يوجد توكن وdriverId صالحان ──────────────────────────────────
/// تنتقل SplashScreen بناءً عليها إلى DashboardScreen.
class AuthAuthenticated extends AuthState {
  final int driverId;

  const AuthAuthenticated({required this.driverId});

  @override
  List<Object?> get props => [driverId];
}

// ─── غير مُوثَّق — لا يوجد توكن أو انتهت صلاحيته ──────────────────────────
/// تنتقل SplashScreen بناءً عليها إلى LoginScreen.
class AuthUnauthenticated extends AuthState {
  const AuthUnauthenticated();
}

// ─── خطأ غير متوقع أثناء قراءة الـ Storage ─────────────────────────────────
/// نادراً ما تُستخدم، لكنها موجودة لاستيعاب أي استثناء.
class AuthError extends AuthState {
  final String message;

  const AuthError({required this.message});

  @override
  List<Object?> get props => [message];
}
