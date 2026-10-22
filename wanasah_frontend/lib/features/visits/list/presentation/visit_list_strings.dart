enum VisitListStringKey {
  title,
  refreshTooltip,
  normalRouteTab,
  emergencyRouteTab,
  filterAll,
  filterCompleted,
  filterPending,
  statusCompleted,
  statusPending,
  statusAttempted,
  statusPostponed,
  statusNoSale,
  statusUnknown,
  balanceLabel,
  mapTooltip,
  emptyNormalAll,
  emptyEmergencyAll,
  emptyNormalPending,
  emptyEmergencyPending,
  emptyNormalCompleted,
  emptyEmergencyCompleted,
  addShopTooltip,
  gateOnBreak,
  gateUnauthorizedAdd,
  gateUnauthorizedOpen,
  gateUnavailable,
  refreshSuccess,
  refreshAlreadySyncing,
  refreshTransportAmbiguous,
  refreshBlocked,
  refreshDeterministicFailure,
  loadFailure,
  retry,
  mapNoLocation,
  mapNoApplication,
  mapInvalidLink,
  mapOpenFailed,
  requestIdLabel,
}

const Map<VisitListStringKey, String> _ar = {
  VisitListStringKey.title: 'قائمة المحلات',
  VisitListStringKey.refreshTooltip: 'تحديث القائمة',
  VisitListStringKey.normalRouteTab: 'جولة اليوم 📍',
  VisitListStringKey.emergencyRouteTab: 'طلبات عاجلة 🚨 ({count})',
  VisitListStringKey.filterAll: 'الكل ({count})',
  VisitListStringKey.filterCompleted: 'المكتملة ({count})',
  VisitListStringKey.filterPending: 'المتبقية ({count})',
  VisitListStringKey.statusCompleted: 'مكتملة',
  VisitListStringKey.statusPending: 'قيد الانتظار',
  VisitListStringKey.statusAttempted: 'محاولة سابقة',
  VisitListStringKey.statusPostponed: 'مؤجلة',
  VisitListStringKey.statusNoSale: 'بدون بيع',
  VisitListStringKey.statusUnknown: 'حالة غير معروفة ({status})',
  VisitListStringKey.balanceLabel: 'الذمة: {amount} د.أ',
  VisitListStringKey.mapTooltip: 'عرض الموقع',
  VisitListStringKey.emptyNormalAll: 'لا توجد زيارات مجدولة لك حالياً 📍',
  VisitListStringKey.emptyEmergencyAll: 'لا توجد طلبات طارئة حالياً 🚨',
  VisitListStringKey.emptyNormalPending: 'لا توجد زيارات متبقية.',
  VisitListStringKey.emptyEmergencyPending: 'لا توجد طلبات طارئة متبقية.',
  VisitListStringKey.emptyNormalCompleted: 'لم تقم بإكمال أي زيارة بعد.',
  VisitListStringKey.emptyEmergencyCompleted:
      'لم تقم بإكمال أي طلب طارئ بعد.',
  VisitListStringKey.addShopTooltip: 'إضافة محل جديد',
  VisitListStringKey.gateOnBreak:
      'أنت الآن في وقت الاستراحة. قم بإنهاء الاستراحة لمتابعة العمل.',
  VisitListStringKey.gateUnauthorizedAdd: 'غير مصرح لك بإضافة محلات.',
  VisitListStringKey.gateUnauthorizedOpen:
      'غير مصرح لك بفتح الزيارة حالياً.',
  VisitListStringKey.gateUnavailable:
      'تعذر تأكيد حالة جلسة العمل والصلاحية. حدّث البيانات ثم أعد المحاولة.',
  VisitListStringKey.refreshSuccess: 'تم تحديث قائمة الزيارات.',
  VisitListStringKey.refreshAlreadySyncing:
      'المزامنة جارية بالفعل من مكان آخر.',
  VisitListStringKey.refreshTransportAmbiguous:
      'تعذر تأكيد نتيجة التحديث بسبب الاتصال. يتم عرض البيانات المحلية.',
  VisitListStringKey.refreshBlocked:
      'يوجد عمل أوفلاين غير محسوم يمنع استبدال البيانات المحلية.',
  VisitListStringKey.refreshDeterministicFailure:
      'تعذر تحديث قائمة الزيارات.',
  VisitListStringKey.loadFailure:
      'تعذر تحميل قائمة الزيارات المحلية.',
  VisitListStringKey.retry: 'إعادة المحاولة',
  VisitListStringKey.mapNoLocation: 'لا يتوفر موقع مسجل لهذا المحل.',
  VisitListStringKey.mapNoApplication:
      'لا يوجد تطبيق خرائط مثبت ولا رابط خارجي صالح.',
  VisitListStringKey.mapInvalidLink: 'رابط الموقع غير صالح.',
  VisitListStringKey.mapOpenFailed: 'تعذر فتح موقع المحل.',
  VisitListStringKey.requestIdLabel: 'رقم التتبع',
};

const Map<VisitListStringKey, String> _en = {
  VisitListStringKey.title: 'Shop visits',
  VisitListStringKey.refreshTooltip: 'Refresh list',
  VisitListStringKey.normalRouteTab: 'Today route 📍',
  VisitListStringKey.emergencyRouteTab: 'Urgent requests 🚨 ({count})',
  VisitListStringKey.filterAll: 'All ({count})',
  VisitListStringKey.filterCompleted: 'Completed ({count})',
  VisitListStringKey.filterPending: 'Remaining ({count})',
  VisitListStringKey.statusCompleted: 'Completed',
  VisitListStringKey.statusPending: 'Pending',
  VisitListStringKey.statusAttempted: 'Attempted',
  VisitListStringKey.statusPostponed: 'Postponed',
  VisitListStringKey.statusNoSale: 'No sale',
  VisitListStringKey.statusUnknown: 'Unknown status ({status})',
  VisitListStringKey.balanceLabel: 'Balance: {amount} JOD',
  VisitListStringKey.mapTooltip: 'Open location',
  VisitListStringKey.emptyNormalAll: 'No scheduled visits right now 📍',
  VisitListStringKey.emptyEmergencyAll: 'No urgent requests right now 🚨',
  VisitListStringKey.emptyNormalPending: 'No remaining visits.',
  VisitListStringKey.emptyEmergencyPending: 'No remaining urgent requests.',
  VisitListStringKey.emptyNormalCompleted: 'No completed visits yet.',
  VisitListStringKey.emptyEmergencyCompleted:
      'No completed urgent requests yet.',
  VisitListStringKey.addShopTooltip: 'Add shop',
  VisitListStringKey.gateOnBreak:
      'You are on break. End the break before continuing.',
  VisitListStringKey.gateUnauthorizedAdd:
      'You are not authorized to add shops.',
  VisitListStringKey.gateUnauthorizedOpen:
      'You are not authorized to open this visit.',
  VisitListStringKey.gateUnavailable:
      'Work-session and authorization state could not be confirmed. Refresh and try again.',
  VisitListStringKey.refreshSuccess: 'Visit list refreshed.',
  VisitListStringKey.refreshAlreadySyncing:
      'A sync is already running elsewhere.',
  VisitListStringKey.refreshTransportAmbiguous:
      'The refresh result could not be confirmed because of connectivity. Local data is shown.',
  VisitListStringKey.refreshBlocked:
      'Unresolved offline work prevents replacing local data.',
  VisitListStringKey.refreshDeterministicFailure:
      'The visit list could not be refreshed.',
  VisitListStringKey.loadFailure:
      'The local visit list could not be loaded.',
  VisitListStringKey.retry: 'Retry',
  VisitListStringKey.mapNoLocation: 'No location is recorded for this shop.',
  VisitListStringKey.mapNoApplication:
      'No maps app or valid external location link is available.',
  VisitListStringKey.mapInvalidLink: 'The location link is invalid.',
  VisitListStringKey.mapOpenFailed: 'The shop location could not be opened.',
  VisitListStringKey.requestIdLabel: 'Request ID',
};

String visitListString(
  VisitListStringKey key, {
  String localeCode = 'ar',
  Map<String, Object> values = const <String, Object>{},
}) {
  final language = localeCode.split(RegExp('[-_]')).first.toLowerCase();
  final selected = language == 'en' ? _en : _ar;
  var text = selected[key] ?? _ar[key]!;
  for (final entry in values.entries) {
    text = text.replaceAll('{${entry.key}}', entry.value.toString());
  }
  return text;
}
