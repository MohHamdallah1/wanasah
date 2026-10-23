enum RecoveryStringKey {
  pendingBanner,
  blockedBanner,
  combinedBanner,
  detailsHint,
  panelTitle,
  panelDescription,
  pendingSection,
  blockedSection,
  pendingState,
  blockedState,
  operationLabel,
  commandIdLabel,
  localRecordLabel,
  attemptsLabel,
  errorCodeLabel,
  requestIdLabel,
  createdAtLabel,
  visitLabel,
  transferLabel,
  referenceLabel,
  reasonLabel,
  missingValue,
  noRecoveryItems,
  readUnavailable,
  syncInProgress,
  syncSuccess,
  syncIncomplete,
  syncRecoveryRequired,
  syncConnectivityUnresolved,
  syncTimedOut,
  syncUnresolved,
  submitSale,
  transferResponse,
  legacyBreak,
  corrupt,
  unknownOperation,
  readOnlyNotice,
}

const Map<RecoveryStringKey, String> _ar = {
  RecoveryStringKey.pendingBanner: 'عمليات بانتظار المزامنة: {count}',
  RecoveryStringKey.blockedBanner: 'عمليات تحتاج استرداداً: {count}',
  RecoveryStringKey.combinedBanner:
      'بانتظار المزامنة: {pending} • تحتاج استرداداً: {blocked}',
  RecoveryStringKey.detailsHint: 'اضغط لعرض التفاصيل.',
  RecoveryStringKey.panelTitle: 'حالة المزامنة والاسترداد',
  RecoveryStringKey.panelDescription:
      'السجلات المعلقة والمحجوبة دليل محفوظ. لا تُحذف لمجرد إخفاء الخطأ.',
  RecoveryStringKey.pendingSection: 'بانتظار المزامنة',
  RecoveryStringKey.blockedSection: 'تحتاج استرداداً',
  RecoveryStringKey.pendingState: 'معلّقة',
  RecoveryStringKey.blockedState: 'محجوبة',
  RecoveryStringKey.operationLabel: 'العملية',
  RecoveryStringKey.commandIdLabel: 'معرّف الأمر',
  RecoveryStringKey.localRecordLabel: 'السجل المحلي',
  RecoveryStringKey.attemptsLabel: 'عدد المحاولات',
  RecoveryStringKey.errorCodeLabel: 'رمز الخطأ',
  RecoveryStringKey.requestIdLabel: 'رقم التتبع',
  RecoveryStringKey.createdAtLabel: 'التاريخ',
  RecoveryStringKey.visitLabel: 'الزيارة',
  RecoveryStringKey.transferLabel: 'الحوالة',
  RecoveryStringKey.referenceLabel: 'مرجع',
  RecoveryStringKey.reasonLabel: 'التفصيل',
  RecoveryStringKey.missingValue: 'غير متوفر',
  RecoveryStringKey.noRecoveryItems: 'لا توجد عمليات معلقة أو محجوبة.',
  RecoveryStringKey.readUnavailable:
      'تعذر قراءة حالة المزامنة المحلية. لم يتم افتراض أنها فارغة.',
  RecoveryStringKey.syncInProgress: 'جاري مزامنة العمليات المحفوظة…',
  RecoveryStringKey.syncSuccess: 'تمت المزامنة بالكامل.',
  RecoveryStringKey.syncIncomplete:
      'المزامنة غير مكتملة؛ ما زالت هناك عمليات معلقة.',
  RecoveryStringKey.syncRecoveryRequired:
      'توجد عمليات محجوبة تحتاج استرداداً قبل اعتبار المزامنة مكتملة.',
  RecoveryStringKey.syncConnectivityUnresolved:
      'تعذر الاتصال أثناء المزامنة. السجلات المحلية ما زالت محفوظة.',
  RecoveryStringKey.syncTimedOut:
      'انتهت مهلة المزامنة قبل تأكيد النتيجة. السجلات المحلية ما زالت محفوظة.',
  RecoveryStringKey.syncUnresolved:
      'تعذر تأكيد نتيجة المزامنة. حالة السجلات المحلية ما زالت محفوظة.',
  RecoveryStringKey.submitSale: 'زيارة / فاتورة',
  RecoveryStringKey.transferResponse: 'رد حوالة',
  RecoveryStringKey.legacyBreak: 'استراحة قديمة',
  RecoveryStringKey.corrupt: 'سجل غير صالح',
  RecoveryStringKey.unknownOperation: 'عملية غير معروفة',
  RecoveryStringKey.readOnlyNotice:
      'السجلات المحجوبة للقراءة فقط في هذه المرحلة ولا يوجد حذف شامل.',
};

const Map<RecoveryStringKey, String> _en = {
  RecoveryStringKey.pendingBanner: 'Waiting to sync: {count}',
  RecoveryStringKey.blockedBanner: 'Recovery required: {count}',
  RecoveryStringKey.combinedBanner:
      'Waiting to sync: {pending} • Recovery required: {blocked}',
  RecoveryStringKey.detailsHint: 'Tap for details.',
  RecoveryStringKey.panelTitle: 'Sync and recovery status',
  RecoveryStringKey.panelDescription:
      'Pending and blocked records are durable evidence. They are not deleted to hide errors.',
  RecoveryStringKey.pendingSection: 'Waiting to sync',
  RecoveryStringKey.blockedSection: 'Recovery required',
  RecoveryStringKey.pendingState: 'Pending',
  RecoveryStringKey.blockedState: 'Blocked',
  RecoveryStringKey.operationLabel: 'Operation',
  RecoveryStringKey.commandIdLabel: 'Command ID',
  RecoveryStringKey.localRecordLabel: 'Local record',
  RecoveryStringKey.attemptsLabel: 'Attempts',
  RecoveryStringKey.errorCodeLabel: 'Error code',
  RecoveryStringKey.requestIdLabel: 'Request ID',
  RecoveryStringKey.createdAtLabel: 'Created',
  RecoveryStringKey.visitLabel: 'Visit',
  RecoveryStringKey.transferLabel: 'Transfer',
  RecoveryStringKey.referenceLabel: 'Reference',
  RecoveryStringKey.reasonLabel: 'Detail',
  RecoveryStringKey.missingValue: 'Unavailable',
  RecoveryStringKey.noRecoveryItems: 'No pending or blocked operations.',
  RecoveryStringKey.readUnavailable:
      'Local sync state could not be read. It was not assumed to be empty.',
  RecoveryStringKey.syncInProgress: 'Syncing durable offline work…',
  RecoveryStringKey.syncSuccess: 'Sync completed.',
  RecoveryStringKey.syncIncomplete:
      'Sync is incomplete; pending operations remain.',
  RecoveryStringKey.syncRecoveryRequired:
      'Blocked operations require recovery before sync can be considered complete.',
  RecoveryStringKey.syncConnectivityUnresolved:
      'Connectivity was lost during sync. Local evidence remains preserved.',
  RecoveryStringKey.syncTimedOut:
      'Sync timed out before the result was confirmed. Local evidence remains preserved.',
  RecoveryStringKey.syncUnresolved:
      'The sync result could not be confirmed. Local evidence remains preserved.',
  RecoveryStringKey.submitSale: 'Visit / invoice',
  RecoveryStringKey.transferResponse: 'Transfer response',
  RecoveryStringKey.legacyBreak: 'Legacy break',
  RecoveryStringKey.corrupt: 'Invalid record',
  RecoveryStringKey.unknownOperation: 'Unknown operation',
  RecoveryStringKey.readOnlyNotice:
      'Blocked records are read-only here and there is no bulk-delete action.',
};

String recoveryString(
  RecoveryStringKey key, {
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
