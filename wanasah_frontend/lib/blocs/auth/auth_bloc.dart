// File: lib/blocs/auth/auth_bloc.dart
//
// المنطق الأساسي لإدارة حالة التوثيق.
// يتعامل مع FlutterSecureStorage مباشرة لقراءة/مسح بيانات الجلسة.

import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'dart:developer' as developer;

import 'auth_event.dart';
import 'auth_state.dart';

class AuthBloc extends Bloc<AuthEvent, AuthState> {
  final FlutterSecureStorage _storage;

  AuthBloc({FlutterSecureStorage? storage})
    : _storage = storage ?? const FlutterSecureStorage(),
      super(const AuthInitial()) {
    on<CheckAuthEvent>(_onCheckAuth);
    on<LoginEvent>(_onLogin);
    on<LogoutEvent>(_onLogout);
  }

  // ─── CheckAuthEvent ────────────────────────────────────────────────────────
  /// يُقرأ التوكن وdriverId من SecureStorage.
  /// النتيجة: AuthAuthenticated أو AuthUnauthenticated أو AuthError.
  Future<void> _onCheckAuth(
    CheckAuthEvent event,
    Emitter<AuthState> emit,
  ) async {
    emit(const AuthLoading());

    try {
      final String? token = await _storage.read(key: 'auth_token');
      final String? driverIdString = await _storage.read(key: 'driver_id');

      if (token != null && token.isNotEmpty && driverIdString != null) {
        final int? driverId = int.tryParse(driverIdString);

        if (driverId != null) {
          developer.log(
            '[AuthBloc] CheckAuth → Authenticated (driverId=$driverId)',
          );
          emit(AuthAuthenticated(driverId: driverId));
        } else {
          // driver_id موجود لكن قيمته غير صالحة — نمسح ونطلب إعادة الدخول
          developer.log(
            '[AuthBloc] CheckAuth → Invalid driver_id "$driverIdString" — clearing.',
          );
          await _storage.deleteAll();
          emit(const AuthUnauthenticated());
        }
      } else {
        developer.log('[AuthBloc] CheckAuth → No valid session found.');
        emit(const AuthUnauthenticated());
      }
    } catch (e) {
      developer.log('[AuthBloc] CheckAuth → Error: $e');
      emit(AuthError(message: e.toString()));
    }
  }

  // ─── LoginEvent ────────────────────────────────────────────────────────────
  /// يُستدعى بعد نجاح API Login وحفظ البيانات في SecureStorage من LoginScreen.
  /// الـ BLoC هنا يكتفي بتحديث الحالة فقط (الحفظ يتم في LoginScreen).
  Future<void> _onLogin(LoginEvent event, Emitter<AuthState> emit) async {
    emit(const AuthLoading());

    try {
      // حفظ البيانات في SecureStorage (للحالات التي تمر عبر الـ BLoC)
      await _storage.write(key: 'auth_token', value: event.token);
      await _storage.write(key: 'driver_id', value: event.driverId.toString());

      developer.log('[AuthBloc] Login → Authenticated (driverId=${event.driverId})');
      emit(AuthAuthenticated(driverId: event.driverId));
    } catch (e) {
      developer.log('[AuthBloc] Login → Error: $e');
      emit(AuthError(message: e.toString()));
    }
  }

  // ─── LogoutEvent ───────────────────────────────────────────────────────────
  /// يمسح كامل الـ SecureStorage ويُرسل AuthUnauthenticated.
  /// يُستدعى من زر الخروج أو تلقائياً من AuthInterceptor عند 401.
  Future<void> _onLogout(LogoutEvent event, Emitter<AuthState> emit) async {
    try {
      await _storage.deleteAll();
      developer.log('[AuthBloc] Logout → Session cleared.');
    } catch (e) {
      developer.log('[AuthBloc] Logout error (non-critical): $e');
    } finally {
      // حتى لو فشل المسح، أرسل Unauthenticated لضمان الخروج
      emit(const AuthUnauthenticated());
    }
  }
}
