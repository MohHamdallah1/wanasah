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
  serverUnresolved,
  requestIdLabel,
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
  WorkSessionStringKey.serverUnresolved:
      'تعذر تأكيد نتيجة العملية بسبب خطأ في السيرفر.',
  WorkSessionStringKey.requestIdLabel: 'رقم التتبع',
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
  WorkSessionStringKey.serverUnresolved:
      'The result could not be confirmed because of a server error.',
  WorkSessionStringKey.requestIdLabel: 'Request ID',
};

String workSessionString(
  WorkSessionStringKey key, {
  String localeCode = 'ar',
}) {
  final language = localeCode.split(RegExp('[-_]')).first.toLowerCase();
  final selected = language == 'en' ? _en : _ar;
  return selected[key] ?? _ar[key]!;
}
