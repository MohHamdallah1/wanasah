// File: lib/blocs/auth/auth_bloc.dart
//
// المنطق الأساسي لإدارة حالة التوثيق.
// يتعامل مع FlutterSecureStorage مباشرة لقراءة/مسح بيانات الجلسة.

import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:dio/dio.dart'; // +++ للتعامل مع مسار الشبكة +++
import 'dart:developer' as developer;

import '../../core/network/api_client.dart'; // +++ استدعاء عميل الشبكة +++
import '../../core/db/local_database.dart'; // +++ الدرع الواقي لمنع تسريب البيانات +++
import 'auth_event.dart';
import 'auth_state.dart';

class AuthBloc extends Bloc<AuthEvent, AuthState> {
  final FlutterSecureStorage _storage;

  AuthBloc({FlutterSecureStorage? storage})
    : _storage = storage ?? const FlutterSecureStorage(),
      super(const AuthInitial()) {
    on<CheckAuthEvent>(_onCheckAuth);
    on<LoginRequested>(_onLogin); // +++ تغيير اسم الحدث +++
    on<LogoutEvent>(_onLogout);
  }

  // ─── CheckAuthEvent ────────────────────────────────────────────────────────
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
          // +++ إغلاق فخ نوع البيانات وتسجيل الخطأ للـ Debugging +++
          developer.log(
            '[AuthBloc] CheckAuth → Failed to parse driver_id: "$driverIdString" is not an integer.',
          );
          emit(const AuthUnauthenticated());
        }
      } else {
        developer.log('[AuthBloc] CheckAuth → No valid session found.');
        emit(const AuthUnauthenticated());
      }
    } catch (e) {
      developer.log('[AuthBloc] CheckAuth → Error reading storage: $e');
      emit(AuthError(message: 'خطأ في قراءة بيانات الجلسة: $e'));
    }
  }

  // ─── LoginRequested ────────────────────────────────────────────────────────────
  /// الـ BLoC هنا يتولى مسؤولية الاتصال بالسيرفر وحفظ التوكن (Single Source of Truth).
  Future<void> _onLogin(LoginRequested event, Emitter<AuthState> emit) async {
    emit(const AuthLoading());

    try {
      // 1. الاتصال المباشر بالسيرفر عبر ApiClient الموحد
      final response = await ApiClient.instance.post(
        '/driver/login',
        data: {'username': event.username, 'password': event.password},
      );

      final data = response.data;
      final String token = data['token'];
      final int driverId = data['driver_id'];

      // 2. حفظ البيانات محلياً (هنا فقط، لمنع التكرار)
      await _storage.write(key: 'auth_token', value: token);
      await _storage.write(key: 'driver_id', value: driverId.toString());

      developer.log('[AuthBloc] Login → Authenticated (driverId=$driverId)');
      emit(AuthAuthenticated(driverId: driverId));
    } on DioException catch (e) {
      developer.log(
        '[AuthBloc] Login API Error: ${e.response?.statusCode} - ${e.message}',
      );
      String errorMsg = 'تأكد من اسم المستخدم وكلمة المرور.';

      if (e.response != null && e.response?.data != null) {
        if (e.response?.data is Map && e.response?.data['message'] != null) {
          errorMsg = e.response?.data['message'];
        }
      }
      emit(AuthError(message: errorMsg));
    } catch (e) {
      developer.log('[AuthBloc] Login Unexpected Error: $e');
      emit(AuthError(message: 'حدث خطأ غير متوقع أثناء تسجيل الدخول.'));
    }
  }

  // ─── LogoutEvent ───────────────────────────────────────────────────────────
  Future<void> _onLogout(LogoutEvent event, Emitter<AuthState> emit) async {
    try {
      await _storage.deleteAll();

      // +++ الحماية القصوى: تدمير بيانات الـ SQLite بالكامل لمنع تسريبها للمندوب التالي +++
      try {
        final db = await LocalDatabase.instance.database;
        await db.transaction((txn) async {
          await txn.delete('products');
          await txn.delete('visits');
          await txn.delete('pending_sync');
        });
        developer.log(
          '[AuthBloc] Local SQLite tables wiped successfully. No cross-account leaks.',
        );
      } catch (dbError) {
        developer.log('[AuthBloc] Error wiping SQLite: $dbError');
      }

      developer.log('[AuthBloc] Logout → Session cleared.');
    } catch (e) {
      developer.log('[AuthBloc] Logout → Error clearing storage: $e');
    } finally {
      // +++ ضمان إطلاق الحالة دائماً حتى لو فشل مسح الذاكرة، ليتم طرد المستخدم +++
      emit(const AuthUnauthenticated());
    }
  }
}
