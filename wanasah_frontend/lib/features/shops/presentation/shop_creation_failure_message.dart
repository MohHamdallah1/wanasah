import '../domain/shop_creation.dart';

String shopCreationFailureMessage(
  ShopCreateFailure failure, {
  String languageCode = 'ar',
}) {
  final ar = languageCode.split(RegExp('[-_]')).first.toLowerCase() != 'en';

  switch (failure.kind) {
    case ShopCreateFailureKind.connectivity:
      return ar
          ? 'تعذر الاتصال بالسيرفر. تحقق من الشبكة ثم أعد المحاولة.'
          : 'The server could not be reached. Check the connection and try again.';
    case ShopCreateFailureKind.timeout:
      return ar
          ? 'انتهت مهلة إضافة المحل قبل تأكيد النتيجة. أعد المحاولة من نفس الشاشة بأمان.'
          : 'Shop creation timed out before the result was confirmed. Retry safely from this screen.';
    case ShopCreateFailureKind.authorization:
      return ar
          ? 'انتهت صلاحية الجلسة أو لا تملك صلاحية إضافة المحل.'
          : 'The session expired or shop creation is not authorized.';
    case ShopCreateFailureKind.businessRejected:
      final fallback = failure.displayFallback?.trim();
      if (fallback != null && fallback.isNotEmpty) return fallback;
      return ar
          ? 'رفض السيرفر طلب إضافة المحل.'
          : 'The server rejected the shop creation request.';
    case ShopCreateFailureKind.rateLimited:
      return ar
          ? 'عدد الطلبات مرتفع حالياً. حاول بعد قليل.'
          : 'Too many requests. Try again shortly.';
    case ShopCreateFailureKind.server:
      return ar
          ? 'الخدمة غير متاحة مؤقتاً. لم يتم تأكيد إضافة المحل.'
          : 'The service is temporarily unavailable. Shop creation was not confirmed.';
    case ShopCreateFailureKind.cancelled:
      return ar
          ? 'تم إلغاء طلب إضافة المحل قبل اكتماله.'
          : 'The shop creation request was cancelled before completion.';
    case ShopCreateFailureKind.unexpected:
      return ar
          ? 'حدث خطأ غير متوقع أثناء إضافة المحل.'
          : 'An unexpected error occurred while creating the shop.';
  }
}
