part of 'package:wanasah_frontend/blocs/dashboard/dashboard_bloc.dart';

Future<void> _handleStartSession(
  DashboardBloc bloc,
  StartSessionEvent event,
  Emitter<DashboardState> emit,
) async {
  try {
    final position = await bloc._locationService.getCurrentLocation();
    await bloc._dashboardRepo.startSession(
      position?.latitude,
      position?.longitude,
    );

    if (bloc.state is DashboardLoaded) {
      emit(
        (bloc.state as DashboardLoaded).copyWith(
          actionSuccessMessage: 'تم بدء جلسة العمل!',
        ),
      );
    }
    bloc.add(FetchDashboardData(driverId: event.driverId));
  } on DioException catch (e) {
    if (e.response?.statusCode == 409) {
      if (bloc.state is DashboardLoaded) {
        emit(
          (bloc.state as DashboardLoaded).copyWith(
            actionSuccessMessage: 'يوجد جلسة عمل نشطة بالفعل.',
          ),
        );
      }
      bloc.add(FetchDashboardData(driverId: event.driverId));
    } else if (e.response?.statusCode != 401) {
      final data = e.response?.data;
      final msg =
          (data is Map)
              ? (data['message'] ?? data['detail'])
              : 'فشل (استجابة غير متوقعة)';
      emit(DashboardError(message: 'خطأ: $msg'));
    }
  } catch (e) {
    if (e.toString().contains('GPS_DISABLED')) {
      emit(
        DashboardError(
          message: 'الرجاء تفعيل خدمة الموقع (GPS) لبدء العمل.',
        ),
      );
    } else if (e.toString().contains('GPS_DENIED_FOREVER')) {
      emit(
        DashboardError(
          message:
              'صلاحية الموقع مرفوضة نهائياً. افتح إعدادات الجهاز وامنح التطبيق صلاحية الموقع ثم أعد المحاولة.',
        ),
      );
    } else if (e.toString().contains('GPS_DENIED')) {
      emit(
        DashboardError(
          message: 'صلاحية الموقع مطلوبة لبدء العمل.',
        ),
      );
    } else if (e.toString().contains('FAKE_GPS_DETECTED')) {
      emit(
        DashboardError(
          message:
              'تحذير أمني: تم رصد تطبيق تزوير موقع (Fake GPS). أوقفه لمتابعة العمل.',
        ),
      );
    } else if (e.toString().contains('GPS_TIMEOUT')) {
      emit(
        DashboardError(
          message:
              'فشل تحديد الموقع. الرجاء التأكد من قوة إشارة الـ GPS والمحاولة في مكان مفتوح.',
        ),
      );
    } else {
      emit(
        DashboardError(
          message:
              'حدث خطأ غير متوقع: ${e.toString().replaceAll('Exception: ', '')}',
        ),
      );
    }
  }
}

Future<void> _handleEndSession(
  DashboardBloc bloc,
  EndSessionEvent event,
  Emitter<DashboardState> emit,
) async {
  try {
    await bloc._dashboardRepo.endSession();
    if (bloc.state is DashboardLoaded) {
      emit(
        (bloc.state as DashboardLoaded).copyWith(
          actionSuccessMessage: 'تم إنهاء العمل.',
        ),
      );
    }
    bloc.add(FetchDashboardData(driverId: event.driverId));
  } on DioException catch (e) {
    if (e.response?.statusCode == 401) return;

    if (e.response?.statusCode == 404) {
      await bloc._dashboardRepo.clearSessionLocally();
      if (bloc.state is DashboardLoaded) {
        emit(
          (bloc.state as DashboardLoaded).copyWith(
            actionSuccessMessage:
                'تم اكتشاف تصفير للسيرفر. تم تنظيف الجلسة الوهمية محلياً 🧹',
          ),
        );
      }
      bloc.add(FetchDashboardData(driverId: event.driverId));
      return;
    }

    final isOffline =
        e.response == null ||
        e.type == DioExceptionType.connectionTimeout ||
        e.type == DioExceptionType.receiveTimeout ||
        e.type == DioExceptionType.sendTimeout ||
        e.type == DioExceptionType.connectionError ||
        e.type == DioExceptionType.unknown ||
        e.error.toString().contains('SocketException');

    final data = e.response?.data;
    final msg =
        (data is Map)
            ? (data['message'] ?? data['detail'])
            : 'فشل (استجابة غير متوقعة)';
    emit(
      DashboardError(
        message:
            isOffline
                ? 'لا يمكن إنهاء العمل وأنت أوفلاين. يجب الاتصال بالإنترنت لمطابقة العهدة وتسليمها.'
                : 'خطأ: $msg',
      ),
    );
  } catch (e) {
    emit(DashboardError(message: 'حدث خطأ أثناء إنهاء الجلسة.'));
  }
}

Future<void> _handleToggleBreak(
  DashboardBloc bloc,
  ToggleBreakEvent event,
  Emitter<DashboardState> emit,
) async {
  try {
    final wasSentLive = await bloc._dashboardRepo.toggleBreak(
      event.driverId,
      event.action,
    );

    if (bloc.state is DashboardLoaded) {
      final actionText =
          event.action == 'start' ? 'تم بدء الاستراحة' : 'تم إنهاء الاستراحة';
      final successMsg =
          wasSentLive
              ? '$actionText (مسجلة).'
              : '$actionText (محفوظة أوفلاين 📡).';
      emit(
        (bloc.state as DashboardLoaded).copyWith(
          actionSuccessMessage: successMsg,
        ),
      );
    }
    bloc.add(FetchDashboardData(driverId: event.driverId));
  } on DioException catch (e) {
    if (e.response?.statusCode == 401) return;
    if (e.response?.statusCode == 404) {
      await bloc._dashboardRepo.clearSessionLocally();
      if (bloc.state is DashboardLoaded) {
        emit(
          (bloc.state as DashboardLoaded).copyWith(
            actionSuccessMessage:
                'الجلسة غير موجودة على السيرفر! تم إعادة الضبط محلياً.',
          ),
        );
      }
      bloc.add(FetchDashboardData(driverId: event.driverId));
      return;
    }

    if (e.response == null) {
      emit(
        DashboardError(
          message:
              'بدء أو إنهاء الاستراحة يحتاج اتصالاً مباشراً بالسيرفر ولا يُحفظ كأمر أوفلاين.',
        ),
      );
      return;
    }

    final data = e.response?.data;
    final msg =
        (data is Map)
            ? (data['message'] ?? data['detail'])
            : 'فشل (استجابة غير متوقعة)';
    emit(DashboardError(message: 'خطأ: $msg'));
  } catch (e) {
    emit(DashboardError(message: 'فشل في عملية الاستراحة.'));
  }
}
