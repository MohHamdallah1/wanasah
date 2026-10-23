enum WorkSessionStringKey {
  startSuccess,
  endSuccess,
  breakStartSuccess,
  breakEndSuccess,
  startReconciled,
  endReconciled,
  breakStartReconciled,
  breakEndReconciled,
  unresolved,
  authRejected,
  businessRejected,
  rateLimited,
  networkUnresolved,
  timeoutUnresolved,
  serverUnresolved,
  requestIdLabel,
  statusCodeLabel,
  serverDetailLabel,
  issueAuthentication,
  issueInvalidStartEvidence,
  issueVehicleCustody,
  issueStartPrerequisite,
  issueEndPrerequisite,
  issueBreakState,
  issueRateLimited,
  issueConnectivity,
  issueTimeout,
  issueUnresolved,
}

const Map<WorkSessionStringKey, String> _ar = {
  WorkSessionStringKey.startSuccess: 'تم بدء جلسة العمل.',
  WorkSessionStringKey.endSuccess: 'تم إنهاء جلسة العمل.',
  WorkSessionStringKey.breakStartSuccess:
      'تم بدء الاستراحة (مسجلة على السيرفر).',
  WorkSessionStringKey.breakEndSuccess:
      'تم إنهاء الاستراحة (مسجلة على السيرفر).',
  WorkSessionStringKey.startReconciled:
      'تم تأكيد أن جلسة العمل نشطة بعد مطابقة حالتها مع السيرفر.',
  WorkSessionStringKey.endReconciled:
      'تم تأكيد انتهاء جلسة العمل بعد مطابقة حالتها مع السيرفر.',
  WorkSessionStringKey.breakStartReconciled:
      'تم تأكيد بدء الاستراحة بعد مطابقة حالتها مع السيرفر.',
  WorkSessionStringKey.breakEndReconciled:
      'تم تأكيد انتهاء الاستراحة بعد مطابقة حالتها مع السيرفر.',
  WorkSessionStringKey.unresolved:
      'تعذر تأكيد نتيجة العملية. حدّث البيانات قبل المحاولة مجدداً.',
  WorkSessionStringKey.authRejected:
      'انتهت صلاحية الجلسة أو لا تملك صلاحية تنفيذ العملية.',
  WorkSessionStringKey.businessRejected:
      'رفض السيرفر العملية بسبب حالة العمل الحالية.',
  WorkSessionStringKey.rateLimited:
      'عدد الطلبات مرتفع حالياً. أعد المحاولة بعد قليل.',
  WorkSessionStringKey.networkUnresolved:
      'تعذر تأكيد نتيجة العملية بسبب الاتصال. تم الحفاظ على حالة السيرفر كمرجع وحيد.',
  WorkSessionStringKey.timeoutUnresolved:
      'انتهت مهلة الاتصال قبل تأكيد نتيجة العملية. حالة السيرفر ما زالت المرجع الوحيد.',
  WorkSessionStringKey.serverUnresolved:
      'تعذر تأكيد نتيجة العملية بسبب خطأ في السيرفر.',
  WorkSessionStringKey.requestIdLabel: 'رقم التتبع',
  WorkSessionStringKey.statusCodeLabel: 'رمز الحالة',
  WorkSessionStringKey.serverDetailLabel: 'تفصيل السيرفر',
  WorkSessionStringKey.issueAuthentication:
      'يلزم تأكيد تسجيل الدخول قبل تنفيذ إجراء الجلسة.',
  WorkSessionStringKey.issueInvalidStartEvidence:
      'بيانات بدء العمل التي وصلت للسيرفر غير صالحة. حدّث البيانات ثم أعد المحاولة.',
  WorkSessionStringKey.issueVehicleCustody:
      'عهدة السيارة التشغيلية غير جاهزة لبدء العمل. راجع مسؤول التوزيع أو العهدة.',
  WorkSessionStringKey.issueStartPrerequisite:
      'السيرفر رفض بدء العمل بسبب متطلب تشغيلي في خط السير أو السيارة أو العهدة. راجع مسؤول التوزيع ثم أعد المحاولة.',
  WorkSessionStringKey.issueEndPrerequisite:
      'السيرفر رفض إنهاء العمل بسبب متطلب تشغيلي قائم. عالج الاستراحة أو الحوالات المعلقة الظاهرة ثم أعد المحاولة.',
  WorkSessionStringKey.issueBreakState:
      'حالة الاستراحة على السيرفر لا تسمح بهذا الإجراء. حدّث حالة الجلسة ثم أعد المحاولة.',
  WorkSessionStringKey.issueRateLimited:
      'تم تأجيل إجراء الجلسة بسبب حد الطلبات. أعد المحاولة بعد قليل.',
  WorkSessionStringKey.issueConnectivity:
      'تعذر الاتصال بالسيرفر. تحقق من الشبكة وحدّث حالة الجلسة قبل إعادة المحاولة.',
  WorkSessionStringKey.issueTimeout:
      'انتهت مهلة الاتصال قبل تأكيد النتيجة. حدّث حالة الجلسة قبل إعادة المحاولة.',
  WorkSessionStringKey.issueUnresolved:
      'لم يتم تأكيد نتيجة إجراء الجلسة. حالة السيرفر هي المرجع؛ حدّث البيانات قبل إعادة المحاولة.',
};

const Map<WorkSessionStringKey, String> _en = {
  WorkSessionStringKey.startSuccess: 'Work session started.',
  WorkSessionStringKey.endSuccess: 'Work session ended.',
  WorkSessionStringKey.breakStartSuccess:
      'Break started and recorded by the server.',
  WorkSessionStringKey.breakEndSuccess:
      'Break ended and recorded by the server.',
  WorkSessionStringKey.startReconciled:
      'The active work session was confirmed with the server.',
  WorkSessionStringKey.endReconciled:
      'The ended work session was confirmed with the server.',
  WorkSessionStringKey.breakStartReconciled:
      'The break start was confirmed with the server.',
  WorkSessionStringKey.breakEndReconciled:
      'The break end was confirmed with the server.',
  WorkSessionStringKey.unresolved:
      'The operation result could not be confirmed. Refresh before retrying.',
  WorkSessionStringKey.authRejected:
      'The session expired or this action is not authorized.',
  WorkSessionStringKey.businessRejected:
      'The server rejected the action because of the current work state.',
  WorkSessionStringKey.rateLimited:
      'Too many requests. Try again shortly.',
  WorkSessionStringKey.networkUnresolved:
      'The result could not be confirmed because of connectivity. Server state remains authoritative.',
  WorkSessionStringKey.timeoutUnresolved:
      'The request timed out before the result was confirmed. Server state remains authoritative.',
  WorkSessionStringKey.serverUnresolved:
      'The result could not be confirmed because of a server error.',
  WorkSessionStringKey.requestIdLabel: 'Request ID',
  WorkSessionStringKey.statusCodeLabel: 'Status code',
  WorkSessionStringKey.serverDetailLabel: 'Server detail',
  WorkSessionStringKey.issueAuthentication:
      'Sign in again before performing this work-session action.',
  WorkSessionStringKey.issueInvalidStartEvidence:
      'The start-session request evidence was invalid. Refresh the data and try again.',
  WorkSessionStringKey.issueVehicleCustody:
      'The vehicle custody is not operationally ready. Contact dispatch or custody operations.',
  WorkSessionStringKey.issueStartPrerequisite:
      'The server refused to start work because a route, vehicle, or custody prerequisite is not ready.',
  WorkSessionStringKey.issueEndPrerequisite:
      'The server refused to end work because an operational prerequisite remains unresolved.',
  WorkSessionStringKey.issueBreakState:
      'The server break state does not allow this action. Refresh the session state and try again.',
  WorkSessionStringKey.issueRateLimited:
      'The work-session action was rate limited. Try again shortly.',
  WorkSessionStringKey.issueConnectivity:
      'The server could not be reached. Check the connection and refresh session state before retrying.',
  WorkSessionStringKey.issueTimeout:
      'The request timed out before the result was confirmed. Refresh session state before retrying.',
  WorkSessionStringKey.issueUnresolved:
      'The work-session result is unresolved. Server state remains authoritative; refresh before retrying.',
};

String workSessionString(
  WorkSessionStringKey key, {
  String localeCode = 'ar',
}) {
  final language = localeCode.split(RegExp('[-_]')).first.toLowerCase();
  final selected = language == 'en' ? _en : _ar;
  return selected[key] ?? _ar[key]!;
}
