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
import 'auth_failure_policy.dart';
import 'auth_messages.dart';
import 'auth_state.dart';
import 'offline_owner_guard.dart';
import 'stored_auth_identity.dart';

class AuthBloc extends Bloc<AuthEvent, AuthState> {
  static const String _offlineOwnerDriverKey =
      'offline_pending_owner_driver_id';
  static const String _offlineOwnerCompanyKey =
      'offline_pending_owner_company_code';

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

  Future<void> _writeOfflineOwnerMarker({
    required String companyCode,
    required int driverId,
  }) async {
    await _storage.write(
      key: _offlineOwnerDriverKey,
      value: driverId.toString(),
    );
    await _storage.write(key: _offlineOwnerCompanyKey, value: companyCode);
  }

  Future<List<Map<String, dynamic>>> _readPendingSyncsForCompany(
    String companyCode,
  ) async {
    await LocalDatabase.instance.setTenant(companyCode);
    return LocalDatabase.instance.getPendingSyncs();
  }

  Future<void> _revokeRejectedLoginSession(String refreshToken) async {
    try {
      await ApiClient.instance.post(
        '/logout',
        options: Options(headers: {'X-Refresh-Token': refreshToken}),
      );
      developer.log(
        '[AuthBloc] Login → Rejected post-auth session revoked best-effort.',
      );
    } catch (e) {
      developer.log(
        '[AuthBloc] Login → Rejected post-auth session cleanup failed; local session remains unpersisted: $e',
      );
    }
  }

  String _offlineOwnerBlockMessage(OfflineOwnerLoginOutcome outcome) {
    switch (outcome) {
      case OfflineOwnerLoginOutcome.blockDifferentDriverSameCompany:
        return 'مرفوض مالياً: توجد عمليات أوفلاين غير متزامنة تخص مندوباً آخر في هذه الشركة. يجب على المندوب صاحب العمليات مزامنتها أو معالجتها عبر مسار الاسترداد المعتمد قبل تسجيل الدخول بهذا الحساب.';
      case OfflineOwnerLoginOutcome.blockDifferentCompany:
        return 'مرفوض مالياً: توجد عمليات أوفلاين غير متزامنة محفوظة لشركة أخرى. يجب مزامنتها أو معالجتها من حسابها الأصلي قبل التبديل إلى شركة أخرى.';
      case OfflineOwnerLoginOutcome.blockUnattributedPending:
        return 'مرفوض مالياً: توجد عمليات أوفلاين غير متزامنة لا يمكن إثبات مالكها بأمان. يجب معالجتها عبر مسار الاسترداد المعتمد قبل تسجيل الدخول.';
      case OfflineOwnerLoginOutcome.blockPendingInspectionFailure:
        return 'تعذر التحقق من ملكية العمليات الأوفلاين بأمان. لم يتم تسجيل الدخول ولم تُحذف أي عمليات. حاول مجدداً أو استخدم مسار الاسترداد المعتمد.';
      case OfflineOwnerLoginOutcome.allowNoPendingOwner:
      case OfflineOwnerLoginOutcome.allowSameOwner:
      case OfflineOwnerLoginOutcome.allowStaleOwner:
        return 'تعذر إكمال تسجيل الدخول بأمان.';
    }
  }

  Future<void> _captureOfflineOwnerBeforeLogout() async {
    final driverId = await _storage.read(key: 'driver_id');
    final companyCode = await _storage.read(key: 'company_code');
    final parsedDriverId = int.tryParse(driverId ?? '');
    if (parsedDriverId == null ||
        parsedDriverId <= 0 ||
        companyCode == null ||
        companyCode.isEmpty) {
      return;
    }

    try {
      final pending = await LocalDatabase.instance.getPendingSyncs();
      if (hasActivePendingSyncs(pending)) {
        await _writeOfflineOwnerMarker(
          companyCode: companyCode,
          driverId: parsedDriverId,
        );
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
      await _writeOfflineOwnerMarker(
        companyCode: companyCode,
        driverId: parsedDriverId,
      );
      developer.log(
        '[AuthBloc] Logout → Pending inspection failed; owner retained defensively: $e',
      );
    }
  }

  Future<void> _onCheckAuth(
    CheckAuthEvent event,
    Emitter<AuthState> emit,
  ) async {
    emit(const AuthLoading());

    try {
      final identity = StoredAuthIdentity.tryParse(
        token: await _storage.read(key: 'auth_token'),
        refreshToken: await _storage.read(key: 'refresh_token'),
        driverId: await _storage.read(key: 'driver_id'),
        companyCode: await _storage.read(key: 'company_code'),
      );

      if (identity == null) {
        developer.log(
          '[AuthBloc] CheckAuth → Stored session identity is incomplete or malformed.',
        );
        emit(const AuthUnauthenticated());
        return;
      }

      await LocalDatabase.instance.setTenant(identity.companyCode);

      developer.log(
        '[AuthBloc] CheckAuth → Authenticated '
        '(driverId=${identity.driverId}, Tenant=${identity.companyCode})',
      );
      emit(AuthAuthenticated(driverId: identity.driverId));
    } catch (e) {
      developer.log('[AuthBloc] CheckAuth → Error reading storage: $e');
      emit(
        AuthError(
          message: authMessage(AuthMessageKey.sessionReadFailure),
        ),
      );
    }
  }
  Future<void> _onLogin(LoginRequested event, Emitter<AuthState> emit) async {
    emit(const AuthLoading());

    try {
      final response = await ApiClient.instance.post(
        '/driver/login',
        data: {
          'company_code': event.companyCode,
          'username': event.username,
          'password': event.password,
        },
      );

      if (response.data is! Map) {
        developer.log(
          '[AuthBloc] Login → Invalid response type: ${response.data.runtimeType}',
        );
        emit(
          AuthError(
            message: authMessage(AuthMessageKey.invalidServerResponse),
          ),
        );
        return;
      }

      final Map<String, dynamic> data = Map<String, dynamic>.from(
        response.data as Map,
      );
      final rawDriverId = data['driver_id'];
      final driverIdText =
          rawDriverId is num
              ? rawDriverId.toInt().toString()
              : rawDriverId?.toString();
      final returnedCompanyCodeRaw =
          data['company_code']?.toString() ?? event.companyCode;
      final String? refreshTokenRaw = data['refresh_token']?.toString();
      final identity = StoredAuthIdentity.tryParse(
        token: data['token']?.toString(),
        refreshToken: refreshTokenRaw,
        driverId: driverIdText,
        companyCode: returnedCompanyCodeRaw,
      );

      if (identity == null) {
        developer.log(
          '[AuthBloc] Login → Missing or malformed session identity in server response.',
        );
        emit(
          AuthError(
            message:
                refreshTokenRaw == null ||
                        refreshTokenRaw.trim().isEmpty ||
                        refreshTokenRaw.trim() == 'null'
                    ? authMessage(AuthMessageKey.missingRefreshToken)
                    : authMessage(AuthMessageKey.incompleteServerSession),
          ),
        );
        return;
      }

      final String token = identity.token;
      final String refreshToken = identity.refreshToken;
      final int driverId = identity.driverId;
      final String returnedCompanyCode = identity.companyCode;
      final String? oldDriverId = await _storage.read(key: 'driver_id');
      final String? oldCompanyCode = await _storage.read(key: 'company_code');
      final String? offlineOwnerDriverId = await _storage.read(
        key: _offlineOwnerDriverKey,
      );
      final String? offlineOwnerCompanyCode = await _storage.read(
        key: _offlineOwnerCompanyKey,
      );

      final markerDriverId = int.tryParse(offlineOwnerDriverId?.trim() ?? '');
      final markerCompanyCode = offlineOwnerCompanyCode?.trim();
      final hasValidMarker =
          markerDriverId != null &&
          markerDriverId > 0 &&
          markerCompanyCode != null &&
          markerCompanyCode.isNotEmpty;
      final previousDriverId = int.tryParse(oldDriverId?.trim() ?? '');
      final previousCompanyCode = oldCompanyCode?.trim();
      final hasValidPreviousOwner =
          previousDriverId != null &&
          previousDriverId > 0 &&
          previousCompanyCode != null &&
          previousCompanyCode.isNotEmpty;

      final String? protectedOwnerCompanyCode =
          hasValidMarker
              ? markerCompanyCode
              : (hasValidPreviousOwner ? previousCompanyCode : null);
      final int? protectedOwnerDriverId =
          hasValidMarker
              ? markerDriverId
              : (hasValidPreviousOwner ? previousDriverId : null);

      final offlineGuard = await evaluateOfflineOwnerLoginSafety(
        ownerCompanyCode: protectedOwnerCompanyCode,
        ownerDriverId: protectedOwnerDriverId?.toString(),
        returnedCompanyCode: returnedCompanyCode,
        returnedDriverId: driverId,
        returnedRefreshToken: refreshToken,
        readPendingSyncs: _readPendingSyncsForCompany,
        revokeRejectedRefresh: _revokeRejectedLoginSession,
      );

      if (!offlineGuard.allowsLogin) {
        if (protectedOwnerCompanyCode != null &&
            protectedOwnerCompanyCode.isNotEmpty &&
            protectedOwnerDriverId != null &&
            protectedOwnerDriverId > 0) {
          try {
            await _writeOfflineOwnerMarker(
              companyCode: protectedOwnerCompanyCode,
              driverId: protectedOwnerDriverId,
            );
          } catch (e) {
            developer.log(
              '[AuthBloc] Login → Failed to refresh offline owner marker while keeping login blocked: $e',
            );
          }
        }
        developer.log(
          '[AuthBloc] Login → Blocked by offline financial ownership guard: ${offlineGuard.outcome}.',
        );
        emit(
          AuthError(message: _offlineOwnerBlockMessage(offlineGuard.outcome)),
        );
        return;
      }

      if (offlineGuard.shouldClearStaleMarker) {
        await _clearOfflineOwnerMarker();
      }

      await LocalDatabase.instance.setTenant(returnedCompanyCode);

      final switchedCompany =
          oldCompanyCode != null &&
          oldCompanyCode.isNotEmpty &&
          oldCompanyCode != returnedCompanyCode;
      final switchedDriverSameCompany =
          previousDriverId != null &&
          previousDriverId > 0 &&
          oldCompanyCode == returnedCompanyCode &&
          previousDriverId != driverId;
      final needToClearCache = switchedCompany || switchedDriverSameCompany;

      if (needToClearCache) {
        // Financial safety invariant: authentication/account switching never
        // deletes pending_sync. This call re-checks active pending work and
        // skips cache clearing if any appeared after the ownership guard.
        await LocalDatabase.instance.clearSessionData(clearPendingSyncs: false);

        final allKeys = await _storage.readAll();
        for (final k in allKeys.keys) {
          if (k.startsWith('cached_') ||
              k == 'is_on_break' ||
              k == 'is_authorized') {
            await _storage.delete(key: k);
          }
        }
      }

      // Persist the returned session only after the offline ownership guard has
      // accepted it. A blocked post-auth response therefore never becomes the
      // locally active session.
      await _storage.write(key: 'company_code', value: returnedCompanyCode);
      await _storage.write(key: 'auth_token', value: token);
      await _storage.write(key: 'refresh_token', value: refreshToken);
      await _storage.write(key: 'driver_id', value: driverId.toString());
      if (offlineGuard.shouldClearMarkerAfterAcceptedSession) {
        await _clearOfflineOwnerMarker();
      }

      developer.log(
        '[AuthBloc] Login → Authenticated (driverId=$driverId, Tenant=$returnedCompanyCode)',
      );
      emit(AuthAuthenticated(driverId: driverId));
    } on DioException catch (e) {
      final failure = AuthLoginFailure.fromDioException(e);
      developer.log(
        '[AuthBloc] Login API failure '
        '(kind=${failure.kind.name}, status=${failure.status}, '
        'code=${failure.code}, requestId=${failure.requestId}, '
        'context=${failure.context}).',
      );
      emit(
        AuthError(
          message: authLoginFailureMessage(failure),
        ),
      );
    } catch (e) {
      developer.log('[AuthBloc] Login Unexpected Error: $e');
      emit(
        AuthError(
          message: authMessage(AuthMessageKey.genericLoginFailure),
        ),
      );
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
        ApiClient.instance
            .post(
              '/logout',
              options: Options(headers: {'X-Refresh-Token': oldRefresh}),
            )
            .ignore();
      }
    } catch (_) {}

    await _storage.delete(key: 'auth_token');
    await _storage.delete(key: 'refresh_token');
    await _storage.delete(key: 'driver_id');
    await _storage.delete(key: 'company_code');

    final allKeys = await _storage.readAll();
    for (final k in allKeys.keys) {
      if (k.startsWith('cached_') ||
          k == 'is_on_break' ||
          k == 'is_authorized') {
        await _storage.delete(key: k);
      }
    }

    try {
      await LocalDatabase.instance.clearSessionData(clearPendingSyncs: false);
      await LocalDatabase.instance.resetTenant();
      developer.log(
        '[AuthBloc] Logout → Session cleared (offline invoices preserved) and DB closed.',
      );
    } catch (dbError) {
      developer.log('[AuthBloc] Logout → Error wiping SQLite: $dbError');
    }

    emit(const AuthUnauthenticated());
  }
}
