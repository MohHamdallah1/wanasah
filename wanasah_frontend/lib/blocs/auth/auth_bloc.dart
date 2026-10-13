// File: lib/blocs/auth/auth_bloc.dart
//
// المنطق الأساسي لإدارة حالة التوثيق.
// يتعامل مع FlutterSecureStorage مباشرة لقراءة/مسح بيانات الجلسة.

import 'dart:async';
import 'dart:developer' as developer;

import 'package:dio/dio.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../core/db/local_database.dart';
import '../../core/network/api_client.dart';
import 'auth_event.dart';
import 'auth_state.dart';
import 'offline_owner_guard.dart';

class AuthBloc extends Bloc<AuthEvent, AuthState> {
  static const String _offlineOwnerDriverKey = 'offline_pending_owner_driver_id';
  static const String _offlineOwnerCompanyKey = 'offline_pending_owner_company_code';

  final FlutterSecureStorage _storage;

  AuthBloc({FlutterSecureStorage? storage})
    : _storage = storage ?? const FlutterSecureStorage(),
      super(const AuthInitial()) {
    on<CheckAuthEvent>(_onCheckAuth);
    on<LoginRequested>(_onLogin);
    on<LogoutEvent>(_onLogout);
  }

  Future<void> _clearOfflineOwnerMarker() async {
    await _storage.delete(key: _offlineOwnerDriverKey);
    await _storage.delete(key: _offlineOwnerCompanyKey);
  }

  Future<void> _captureOfflineOwnerBeforeLogout() async {
    final driverId = await _storage.read(key: 'driver_id');
    final companyCode = await _storage.read(key: 'company_code');
    final parsedDriverId = int.tryParse(driverId ?? '');
    if (parsedDriverId == null || parsedDriverId <= 0 || companyCode == null || companyCode.isEmpty) {
      return;
    }

    try {
      final pending = await LocalDatabase.instance.getPendingSyncs();
      final activePending = pending.where((p) => !p['type'].toString().startsWith('quarantined_')).toList();
      if (activePending.isNotEmpty) {
        await _storage.write(key: _offlineOwnerDriverKey, value: parsedDriverId.toString());
        await _storage.write(key: _offlineOwnerCompanyKey, value: companyCode);
        developer.log(
          '[AuthBloc] Logout → Preserved offline queue owner (driverId=$parsedDriverId, Tenant=$companyCode).',
        );
        return;
      }

      final markedCompany = await _storage.read(key: _offlineOwnerCompanyKey);
      if (markedCompany == companyCode) {
        await _clearOfflineOwnerMarker();
      }
    } catch (e) {
      // Fail closed: if local inspection is unavailable while a current field
      // identity exists, retain its locator so a later different account cannot
      // silently replay this tenant's queue.
      await _storage.write(key: _offlineOwnerDriverKey, value: parsedDriverId.toString());
      await _storage.write(key: _offlineOwnerCompanyKey, value: companyCode);
      developer.log('[AuthBloc] Logout → Pending inspection failed; owner retained defensively: $e');
    }
  }

  Future<void> _onCheckAuth(
    CheckAuthEvent event,
    Emitter<AuthState> emit,
  ) async {
    emit(const AuthLoading());

    try {
      final String? token = await _storage.read(key: 'auth_token');
      final String? driverIdString = await _storage.read(key: 'driver_id');
      final String? companyCode = await _storage.read(key: 'company_code');

      if (token != null && token.isNotEmpty && driverIdString != null && companyCode != null) {
        final int? driverId = int.tryParse(driverIdString);

        if (driverId != null) {
          await LocalDatabase.instance.setTenant(companyCode);

          developer.log(
            '[AuthBloc] CheckAuth → Authenticated (driverId=$driverId, Tenant=$companyCode)',
          );
          emit(AuthAuthenticated(driverId: driverId));
        } else {
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
      emit(AuthError(message: 'تعذر قراءة بيانات الجلسة السابقة. يرجى تسجيل الدخول مجدداً.'));
    }
  }

  Future<void> _onLogin(LoginRequested event, Emitter<AuthState> emit) async {
    emit(const AuthLoading());

    try {
      final response = await ApiClient.instance.post(
        '/driver/login',
        data: {'company_code': event.companyCode, 'username': event.username, 'password': event.password},
      );

      if (response.data is! Map) {
        developer.log('[AuthBloc] Login → Invalid response type: ${response.data}');
        emit(AuthError(message: 'استجابة غير صالحة من الخادم.'));
        return;
      }

      final Map<String, dynamic> data = Map<String, dynamic>.from(response.data as Map);

      final String? token = data['token']?.toString();
      final int? driverId = (data['driver_id'] as num?)?.toInt();

      if (token == null || token.isEmpty || driverId == null) {
        developer.log('[AuthBloc] Login → Missing token or driver_id in response.');
        emit(AuthError(message: 'فشل تسجيل الدخول: بيانات الخادم غير مكتملة.'));
        return;
      }

      final String? refreshToken = data['refresh_token']?.toString();
      if (refreshToken == null || refreshToken.isEmpty || refreshToken == 'null') {
        developer.log('[AuthBloc] Login → Server did not send refresh_token!');
        emit(AuthError(message: 'استجابة ناقصة من الخادم (رمز التجديد مفقود).'));
        return;
      }

      final String returnedCompanyCode = data['company_code']?.toString() ?? event.companyCode;

      final String? oldDriverId = await _storage.read(key: 'driver_id');
      final String? oldCompanyCode = await _storage.read(key: 'company_code');
      final String? offlineOwnerDriverId = await _storage.read(key: _offlineOwnerDriverKey);
      final String? offlineOwnerCompanyCode = await _storage.read(key: _offlineOwnerCompanyKey);
      final offlineOwnerDecision = classifyOfflineOwnerLogin(
        ownerCompanyCode: offlineOwnerCompanyCode,
        ownerDriverId: offlineOwnerDriverId,
        returnedCompanyCode: returnedCompanyCode,
        returnedDriverId: driverId,
      );

      if (offlineOwnerDecision == OfflineOwnerLoginDecision.differentCompany) {
        developer.log(
          '[AuthBloc] Login → Blocked: preserved offline queue belongs to another company ($offlineOwnerCompanyCode).',
        );
        emit(AuthError(message: 'مرفوض مالياً: توجد عمليات أوفلاين محفوظة للشركة السابقة. سجّل الدخول للحساب السابق وارفعها أولاً.'));
        return;
      }

      if (oldCompanyCode != null && oldCompanyCode.isNotEmpty && oldCompanyCode != returnedCompanyCode) {
        try {
          final pending = await LocalDatabase.instance.getPendingSyncs();
          final activePending = pending.where((p) => !p['type'].toString().startsWith('quarantined_')).toList();
          if (activePending.isNotEmpty) {
            developer.log('[AuthBloc] Login → Aborted: Active pending syncs found for old company ($oldCompanyCode).');
            emit(AuthError(message: 'مرفوض مالياً: يرجى استكمال مزامنة فواتير الأوفلاين للشركة السابقة قبل التبديل لشركة أخرى لحماية مبيعاتك.'));
            return;
          }
        } catch (e) {
          developer.log('[AuthBloc] Login → Ignored DB error during pending sync check: $e');
        }
      }

      await LocalDatabase.instance.setTenant(returnedCompanyCode);

      bool needToClearCache = false;
      if (offlineOwnerDecision == OfflineOwnerLoginDecision.differentDriverSameCompany) {
        developer.log(
          '[AuthBloc] Login → Different driver owns preserved offline queue ($offlineOwnerDriverId → $driverId). Wiping legacy data.',
        );
        await LocalDatabase.instance.clearSessionData(clearPendingSyncs: true);
        await _clearOfflineOwnerMarker();
        needToClearCache = true;
      } else if (oldCompanyCode != null && oldCompanyCode != returnedCompanyCode) {
        developer.log('[AuthBloc] Login → Switched to different company ($oldCompanyCode → $returnedCompanyCode). DB isolated.');
        needToClearCache = true;
      } else if (
        offlineOwnerDecision == OfflineOwnerLoginDecision.noOwner &&
        oldDriverId != null &&
        oldDriverId.isNotEmpty &&
        oldDriverId != driverId.toString()
      ) {
        developer.log('[AuthBloc] Login → Different driver for same company ($oldDriverId → $driverId). Wiping legacy data.');
        await LocalDatabase.instance.clearSessionData(clearPendingSyncs: true);
        needToClearCache = true;
      }

      if (needToClearCache) {
        final allKeys = await _storage.readAll();
        for (final k in allKeys.keys) {
          if (k.startsWith('cached_') || k == 'is_on_break' || k == 'is_authorized') {
            await _storage.delete(key: k);
          }
        }
      }

      await _storage.write(key: 'company_code', value: returnedCompanyCode);
      await _storage.write(key: 'auth_token', value: token);
      await _storage.write(key: 'refresh_token', value: refreshToken);
      await _storage.write(key: 'driver_id', value: driverId.toString());
      if (offlineOwnerDecision == OfflineOwnerLoginDecision.sameOwner) {
        await _clearOfflineOwnerMarker();
      }

      developer.log('[AuthBloc] Login → Authenticated (driverId=$driverId, Tenant=$returnedCompanyCode)');
      emit(AuthAuthenticated(driverId: driverId));
    } on DioException catch (e) {
      developer.log(
        '[AuthBloc] Login API Error: ${e.response?.statusCode} - ${e.message}',
      );
      String errorMsg;

      switch (e.response?.statusCode) {
        case 401:
        case 429:
        case 403:
          errorMsg = 'تأكد من اسم المستخدم وكلمة المرور.';
          if (e.response?.data is Map) {
            final dynamic msg = (e.response!.data as Map)['message'] ?? (e.response!.data as Map)['detail'];
            if (msg is String && msg.isNotEmpty) {
              errorMsg = msg;
            }
          }
          break;
        case null:
          errorMsg = 'تعذر الاتصال بالخادم. تحقق من اتصالك بالإنترنت.';
          break;
        default:
          errorMsg = 'خطأ في الخادم (${e.response?.statusCode}). حاول لاحقاً.';
      }
      emit(AuthError(message: errorMsg));
    } catch (e) {
      developer.log('[AuthBloc] Login Unexpected Error: $e');
      emit(AuthError(message: 'حدث خطأ غير متوقع أثناء تسجيل الدخول.'));
    }
  }

  Future<void> _onLogout(LogoutEvent event, Emitter<AuthState> emit) async {
    try {
      await _captureOfflineOwnerBeforeLogout();
    } catch (e) {
      developer.log('[AuthBloc] Logout → Failed to capture offline owner: $e');
    }

    try {
      final oldRefresh = await _storage.read(key: 'refresh_token');
      if (oldRefresh != null && oldRefresh.isNotEmpty) {
        ApiClient.instance.post('/logout', options: Options(headers: {'X-Refresh-Token': oldRefresh})).ignore();
      }
    } catch (_) {}

    await _storage.delete(key: 'auth_token');
    await _storage.delete(key: 'refresh_token');
    await _storage.delete(key: 'driver_id');
    await _storage.delete(key: 'company_code');

    final allKeys = await _storage.readAll();
    for (final k in allKeys.keys) {
      if (k.startsWith('cached_') || k == 'is_on_break' || k == 'is_authorized') {
        await _storage.delete(key: k);
      }
    }

    try {
      await LocalDatabase.instance.clearSessionData(clearPendingSyncs: false);
      await LocalDatabase.instance.resetTenant();
      developer.log('[AuthBloc] Logout → Session cleared (offline invoices preserved) and DB closed.');
    } catch (dbError) {
      developer.log('[AuthBloc] Logout → Error wiping SQLite: $dbError');
    }

    emit(const AuthUnauthenticated());
  }
}
