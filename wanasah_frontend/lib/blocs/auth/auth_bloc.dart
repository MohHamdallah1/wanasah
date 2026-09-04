// File: lib/blocs/auth/auth_bloc.dart
//
// المنطق الأساسي لإدارة حالة التوثيق.
// يتعامل مع FlutterSecureStorage مباشرة لقراءة/مسح بيانات الجلسة.

import 'dart:async'; // +++ لـ Future.ignore() +++

import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:dio/dio.dart'; // +++ للتعامل مع مسار الشبكة +++
import 'dart:developer' as developer;

import '../../core/network/api_client.dart';
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
      final String? companyCode = await _storage.read(key: 'company_code'); // +++ جلب رمز الشركة +++

      if (token != null && token.isNotEmpty && driverIdString != null && companyCode != null) {
        final int? driverId = int.tryParse(driverIdString);

        if (driverId != null) {
          // +++ تفعيل العزل الفيزيائي فوراً بفتح قاعدة البيانات المخصصة للشركة المحفوظة +++
          await LocalDatabase.instance.setTenant(companyCode);
          
          developer.log(
            '[AuthBloc] CheckAuth → Authenticated (driverId=$driverId, Tenant=$companyCode)',
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
      // +++   إخفاء تفاصيل الكراش عن المندوب برسالة واضحة +++
      emit(AuthError(message: 'تعذر قراءة بيانات الجلسة السابقة. يرجى تسجيل الدخول مجدداً.'));
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
        data: {'company_code': event.companyCode, 'username': event.username, 'password': event.password}, // +++ إرسال رمز الشركة للسيرفر +++
      );

      // +++ الدرع النوعي الصارم (Type Safe Shield): فحص الهيكل الأساسي أولاً +++
      if (response.data is! Map) {
        developer.log('[AuthBloc] Login → Invalid response type: ${response.data}');
        emit(AuthError(message: 'استجابة غير صالحة من الخادم.'));
        return;
      }
      
      // +++  الحقيقي (Elite Cast): إجبار الـ Dart على تحويل أي قاموس مجهول إلى قاموس صريح لمنع كراش الـ TypeError +++
      final Map<String, dynamic> data = Map<String, dynamic>.from(response.data as Map);
      
      // حماية تحويل الأرقام (الـ JSON قد يرسل الرقم كـ double)
      final String? token = data['token']?.toString();
      final int? driverId = (data['driver_id'] as num?)?.toInt();

      if (token == null || token.isEmpty || driverId == null) {
        developer.log('[AuthBloc] Login → Missing token or driver_id in response.');
        emit(AuthError(message: 'فشل تسجيل الدخول: بيانات الخادم غير مكتملة.'));
        return;
      }

      // 2. حفظ البيانات محلياً (هنا فقط، لمنع التكرار)

      // +++ الإصلاح الحرج: استلام وحفظ refresh_token — دونه يموت التجديد الصامت كل 15 دقيقة +++
      final String? refreshToken = data['refresh_token']?.toString();
      if (refreshToken == null || refreshToken.isEmpty || refreshToken == 'null') {
        developer.log('[AuthBloc] Login → Server did not send refresh_token!');
        emit(AuthError(message: 'استجابة ناقصة من الخادم (رمز التجديد مفقود).'));
        return;
      }

      final String returnedCompanyCode = data['company_code']?.toString() ?? event.companyCode;

      final String? oldDriverId = await _storage.read(key: 'driver_id');
      final String? oldCompanyCode = await _storage.read(key: 'company_code');

      // +++ الدرع المالي (P1-2): منع التبديل لشركة أخرى إذا كانت الشركة الحالية تمتلك فواتير أوفلاين غير مرفوعة +++
      if (oldCompanyCode != null && oldCompanyCode.isNotEmpty && oldCompanyCode != returnedCompanyCode) {
        try {
          // جلب المعلقات للشركة الحالية (قبل التبديل للجديدة)
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

      // +++ تفعيل العزل الفيزيائي للشركة الجديدة (سيقوم بفتح/إنشاء قاعدة بيانات مخصصة لها) +++
      await LocalDatabase.instance.setTenant(returnedCompanyCode);

      // +++ درع تعدد الحسابات: مندوب مختلف في نفس الشركة = مسح العهدة، شركة مختلفة = بقاء الداتابيز القديمة معزولة +++
      bool needToClearCache = false;
      if (oldCompanyCode != null && oldCompanyCode != returnedCompanyCode) {
        developer.log('[AuthBloc] Login → Switched to different company ($oldCompanyCode → $returnedCompanyCode). DB isolated.');
        needToClearCache = true;
      } else if (oldDriverId != null && oldDriverId.isNotEmpty && oldDriverId != driverId.toString()) {
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
          // رسائل السيرفر الذكية: تشمل عدّاد المحاولات المتبقية وحظر الـ Brute Force وإيقاف الحساب
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

  // ─── LogoutEvent ───────────────────────────────────────────────────────────
  Future<void> _onLogout(LogoutEvent event, Emitter<AuthState> emit) async {
    // +++ الإصلاح M-6: إبلاغ السيرفر بحرق الـ refresh token عبر العميل الموحد (Fire-and-forget) +++
    try {
      final oldRefresh = await _storage.read(key: 'refresh_token');
      if (oldRefresh != null && oldRefresh.isNotEmpty) {
        // +++   استخدام ApiClient لمنع ازدواجية الـ Dio +++
        ApiClient.instance.post('/logout', options: Options(headers: {'X-Refresh-Token': oldRefresh})).ignore();
      }
    } catch (_) {}

    // +++ الإصلاح M-5: مسح جراحي للمفاتيح (مع إغلاق ثغرة تسريب الخصوصية State Bleed) +++
    await _storage.delete(key: 'auth_token');
    await _storage.delete(key: 'refresh_token');
    await _storage.delete(key: 'driver_id');
    await _storage.delete(key: 'company_code'); // +++ مسح الهوية للعودة إلى حالة الصفر +++
    
    // +++   مسح كل آثار جلسة الداشبورد لتجنب الجلسات الوهمية (Ghost Sessions) عند الدخول مجدداً +++
    final allKeys = await _storage.readAll();
    for (final k in allKeys.keys) {
      if (k.startsWith('cached_') || k == 'is_on_break' || k == 'is_authorized') {
        await _storage.delete(key: k);
      }
    }

    // +++ سياسة موحدة مع الانترسبتور: حفظ فواتير الأوفلاين (pending_sync)،
    //     ودرع تعدد الحسابات في _onLogin يمسحها إذا سجّل مندوب مختلف +++
    try {
      await LocalDatabase.instance.clearSessionData(clearPendingSyncs: false);
      await LocalDatabase.instance.resetTenant(); // +++ إغلاق القاعدة لضمان العزل الفيزيائي التام +++
      developer.log('[AuthBloc] Logout → Session cleared (offline invoices preserved) and DB closed.');
    } catch (dbError) {
      developer.log('[AuthBloc] Logout → Error wiping SQLite: $dbError');
    }

    // +++ ضمان إطلاق حالة الطرد دائماً حتى لو فشل المسح +++
    emit(const AuthUnauthenticated());
  }
}
