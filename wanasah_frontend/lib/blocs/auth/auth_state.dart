// File: lib/blocs/auth/auth_state.dart
//
// تعريف جميع الحالات (States) التي يمكن أن يكون عليها AuthBloc.

import 'package:equatable/equatable.dart';
import '../../features/auth/application/field_principal_identity.dart';

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
  const AuthAuthenticated({required this.identity});
  final FieldPrincipalIdentity identity;
  int get principalId => identity.principalId;
  int get representativeId => identity.representativeId;
  int get companyId => identity.companyId;
  String get companyCode => identity.companyCode;
  // Existing operational consumers keep the explicit Backend Driver bridge.
  int get driverId => identity.legacyDriverId;

  @override
  List<Object?> get props => [principalId, representativeId, companyId, companyCode, driverId];
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
  final DateTime timestamp; // +++   ختم زمني لإجبار الشاشة على إظهار الخطأ حتى لو تكرر نصاً +++

  AuthError({required this.message}) : timestamp = DateTime.now();

  @override
  List<Object?> get props => [message, timestamp];
}
