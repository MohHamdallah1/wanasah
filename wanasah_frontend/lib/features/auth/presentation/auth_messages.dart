import '../application/auth_failure_policy.dart';

enum AuthMessageKey {
  invalidServerResponse,
  incompleteServerSession,
  missingRefreshToken,
  sessionReadFailure,
  authRejected,
  rateLimited,
  connectivityFailure,
  serverFailure,
  requestRejected,
  genericLoginFailure,
}

const Map<String, Map<AuthMessageKey, String>> _authMessages = {
  'ar': {
    AuthMessageKey.invalidServerResponse: 'استجابة غير صالحة من الخادم.',
    AuthMessageKey.incompleteServerSession:
        'فشل تسجيل الدخول: بيانات الجلسة القادمة من الخادم غير مكتملة.',
    AuthMessageKey.missingRefreshToken:
        'استجابة ناقصة من الخادم (رمز التجديد مفقود).',
    AuthMessageKey.sessionReadFailure:
        'تعذر قراءة بيانات الجلسة السابقة. يرجى تسجيل الدخول مجدداً.',
    AuthMessageKey.authRejected:
        'تعذر قبول بيانات تسجيل الدخول. تحقق من الحساب وحالته ثم حاول مجدداً.',
    AuthMessageKey.rateLimited:
        'تم تجاوز حد محاولات تسجيل الدخول. انتظر قليلاً ثم حاول مجدداً.',
    AuthMessageKey.connectivityFailure:
        'تعذر الاتصال بالخادم. تحقق من اتصالك بالإنترنت ثم حاول مجدداً.',
    AuthMessageKey.serverFailure:
        'تعذر إكمال تسجيل الدخول بسبب خطأ في الخادم. حاول لاحقاً. المرجع: {requestId}',
    AuthMessageKey.requestRejected:
        'رفض الخادم طلب تسجيل الدخول.',
    AuthMessageKey.genericLoginFailure:
        'حدث خطأ غير متوقع أثناء تسجيل الدخول.',
  },
  'en': {
    AuthMessageKey.invalidServerResponse: 'The server returned an invalid response.',
    AuthMessageKey.incompleteServerSession:
        'Sign-in failed because the server session data is incomplete.',
    AuthMessageKey.missingRefreshToken:
        'The server response is incomplete (refresh token is missing).',
    AuthMessageKey.sessionReadFailure:
        'The previous session could not be read. Please sign in again.',
    AuthMessageKey.authRejected:
        'The sign-in session was rejected. Check the account and try again.',
    AuthMessageKey.rateLimited:
        'Too many sign-in attempts. Wait briefly and try again.',
    AuthMessageKey.connectivityFailure:
        'The server could not be reached. Check your connection and try again.',
    AuthMessageKey.serverFailure:
        'Sign-in could not be completed because of a server error. Try again later. Reference: {requestId}',
    AuthMessageKey.requestRejected:
        'The server rejected the sign-in request.',
    AuthMessageKey.genericLoginFailure:
        'An unexpected error occurred while signing in.',
  },
};

String authMessage(
  AuthMessageKey key, {
  String localeCode = 'ar',
  String? requestId,
}) {
  final language = _authMessages.containsKey(localeCode) ? localeCode : 'ar';
  var message = _authMessages[language]![key]!;

  if (key == AuthMessageKey.serverFailure) {
    final normalizedRequestId = requestId?.trim();
    if (normalizedRequestId == null || normalizedRequestId.isEmpty) {
      message = message
          .replaceAll(' المرجع: {requestId}', '')
          .replaceAll(' Reference: {requestId}', '');
    } else {
      message = message.replaceAll('{requestId}', normalizedRequestId);
    }
  }

  return message;
}

String authLoginFailureMessage(
  AuthLoginFailure failure, {
  String localeCode = 'ar',
}) {
  switch (failure.kind) {
    case AuthLoginFailureKind.authRejected:
      return authMessage(AuthMessageKey.authRejected, localeCode: localeCode);
    case AuthLoginFailureKind.rateLimited:
      return authMessage(AuthMessageKey.rateLimited, localeCode: localeCode);
    case AuthLoginFailureKind.connectivity:
      return authMessage(
        AuthMessageKey.connectivityFailure,
        localeCode: localeCode,
      );
    case AuthLoginFailureKind.serverFailure:
      return authMessage(
        AuthMessageKey.serverFailure,
        localeCode: localeCode,
        requestId: failure.requestId,
      );
    case AuthLoginFailureKind.requestRejected:
      final fallback = failure.displayFallback?.trim();
      if (fallback != null && fallback.isNotEmpty) {
        return fallback;
      }
      return authMessage(AuthMessageKey.requestRejected, localeCode: localeCode);
    case AuthLoginFailureKind.cancelled:
    case AuthLoginFailureKind.unexpected:
      return authMessage(
        AuthMessageKey.genericLoginFailure,
        localeCode: localeCode,
      );
  }
}
