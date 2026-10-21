import '../application/work_session_failure.dart';
import '../application/work_session_outcome.dart';

String workSessionResultMessage(WorkSessionOperationResult result) {
  if (result.disposition == WorkSessionDisposition.success) {
    switch (result.operation) {
      case WorkSessionOperation.start:
        return 'تم بدء جلسة العمل.';
      case WorkSessionOperation.end:
        return 'تم إنهاء جلسة العمل.';
      case WorkSessionOperation.startBreak:
        return 'تم بدء الاستراحة (مسجلة على السيرفر).';
      case WorkSessionOperation.endBreak:
        return 'تم إنهاء الاستراحة (مسجلة على السيرفر).';
    }
  }

  if (result.disposition == WorkSessionDisposition.reconciledSuccess) {
    switch (result.operation) {
      case WorkSessionOperation.start:
        return 'تم تأكيد أن جلسة العمل نشطة بعد مطابقة حالتها مع السيرفر.';
      case WorkSessionOperation.end:
        return 'تم تأكيد انتهاء جلسة العمل بعد مطابقة حالتها مع السيرفر.';
      case WorkSessionOperation.startBreak:
        return 'تم تأكيد بدء الاستراحة بعد مطابقة حالتها مع السيرفر.';
      case WorkSessionOperation.endBreak:
        return 'تم تأكيد انتهاء الاستراحة بعد مطابقة حالتها مع السيرفر.';
    }
  }

  final failure = result.failure;
  if (failure == null) {
    return 'تعذر تأكيد نتيجة العملية. حدّث البيانات قبل المحاولة مجدداً.';
  }

  switch (failure.kind) {
    case WorkSessionFailureKind.authRejected:
      return _withRequestId(
        'انتهت صلاحية الجلسة أو لا تملك صلاحية تنفيذ العملية.',
        failure.requestId,
      );
    case WorkSessionFailureKind.businessRejected:
      return _withRequestId(
        failure.displayFallback ?? 'رفض السيرفر العملية بسبب حالة العمل الحالية.',
        failure.requestId,
      );
    case WorkSessionFailureKind.rateLimited:
      return _withRequestId(
        'عدد الطلبات مرتفع حالياً. أعد المحاولة بعد قليل.',
        failure.requestId,
      );
    case WorkSessionFailureKind.network:
      return _withRequestId(
        'تعذر تأكيد نتيجة العملية بسبب الاتصال. تم الحفاظ على حالة السيرفر كمرجع وحيد.',
        failure.requestId,
      );
    case WorkSessionFailureKind.server:
      return _withRequestId(
        'تعذر تأكيد نتيجة العملية بسبب خطأ في السيرفر.',
        failure.requestId,
      );
    case WorkSessionFailureKind.unknown:
      return _withRequestId(
        'تعذر تأكيد نتيجة العملية. حدّث البيانات قبل المحاولة مجدداً.',
        failure.requestId,
      );
  }
}

String _withRequestId(String message, String? requestId) {
  if (requestId == null || requestId.isEmpty) return message;
  return '$message\nرقم التتبع: $requestId';
}
