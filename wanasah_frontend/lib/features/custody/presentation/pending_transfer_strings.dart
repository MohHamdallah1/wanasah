import 'package:flutter/widgets.dart';

/// Translation keys scoped to the pending-transfer dialog only.
class PendingTransferStrings {
  PendingTransferStrings(String locale)
    : _ar = locale.split(RegExp('[-_]')).first == 'ar';
  factory PendingTransferStrings.of(BuildContext context) =>
      PendingTransferStrings(Localizations.localeOf(context).languageCode);
  final bool _ar;
  String t(String key) => (_ar ? _arabic : _english)[key]!;
  String legacyQuantity(String cartons, String pieces) => t(
    'legacyQuantity',
  ).replaceAll('{cartons}', cartons).replaceAll('{pieces}', pieces);
  static const _arabic = {
    'title': 'تحديث عهدة من الإدارة',
    'instructions':
        'راجع كل حركة وحدد قبولها أو رفضها. الرفض يتطلب سبباً واضحاً.',
    'add': 'إضافة للسيارة',
    'remove': 'سحب من السيارة',
    'legacyQuantity': '{cartons} كرتونة، {pieces} حبة',
    'reject': 'رفض',
    'accept': 'قبول',
    'reason': 'سبب الرفض',
    'reasonHint': 'مثال: الكمية الفعلية لا تطابق التحويل',
    'defer': 'تأجيل (إغلاق)',
    'submit': 'إرسال الرد',
    'allRequired': 'يجب الرد على جميع الحركات بالقبول أو الرفض.',
    'reasonRequired': 'سبب الرفض مطلوب لكل حركة مرفوضة.',
  };
  static const _english = {
    'title': 'Custody update from management',
    'instructions':
        'Accept or reject each movement. Rejection requires a clear reason.',
    'add': 'Addition to vehicle',
    'remove': 'Removal from vehicle',
    'legacyQuantity': '{cartons} cartons, {pieces} pieces',
    'reject': 'Reject',
    'accept': 'Accept',
    'reason': 'Rejection reason',
    'reasonHint': 'For example: received quantity differs from the transfer',
    'defer': 'Defer (close)',
    'submit': 'Send response',
    'allRequired': 'Accept or reject every movement.',
    'reasonRequired': 'Every rejected movement needs a reason.',
  };
}
