import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

/// Feature-owned locale resources; canonical codes never depend on these labels.
class VisitFieldStrings {
  VisitFieldStrings(this.locale);
  final Locale locale;
  static VisitFieldStrings of(BuildContext context) =>
      VisitFieldStrings(Localizations.localeOf(context));
  String t(String key) => (locale.languageCode == 'ar' ? _ar : _en)[key] ??
      _en[key]!;
  String quantitySummary(int soldCartons, int soldPacks, int returnCartons, int returnPacks) {
    final number = NumberFormat.decimalPattern(locale.toLanguageTag());
    return '${t('quantities')}: ${number.format(soldCartons)} / ${number.format(soldPacks)}'
      ' · ${t('returns')}: ${number.format(returnCartons)} / ${number.format(returnPacks)}';
  }
  static const _en = {
    'cancel': 'Cancel', 'continue': 'Continue', 'close': 'Close',
    'confirmSale': 'Confirm sale', 'preview': 'Backend invoice preview — not committed',
    'committed': 'Committed invoice — frozen evidence',
    'pending': 'Saved on this device. Submission is unresolved; this is not a committed invoice.',
    'confirmed': 'Visit confirmed by Backend.',
    'noInvoice': 'No sale invoice is available for this visit.',
    'readFailed': 'Visit saved. Invoice evidence could not be read. Do not submit the visit again.',
    'readInvoice': 'Read committed invoice', 'retryRead': 'Read invoice again',
    'estimate': 'Cached estimate only', 'currency': 'Currency',
    'rounding': 'Rounding', 'halfUp': 'Half up', 'halfEven': 'Half even',
    'precision': 'Decimal places', 'calculated': 'Calculated at', 'revision': 'Revision',
    'gross': 'Gross', 'discount': 'Discount', 'postOffer': 'After offers',
    'taxable': 'Taxable', 'tax': 'Tax', 'lineTotal': 'Line total',
    'adjustment': 'Rounding adjustment', 'payable': 'Final payable',
    'connectivity': 'Connection unavailable or result unresolved. Your draft is preserved.',
    'authorization': 'Access is unavailable. Check your session or contact Backoffice.',
    'business': 'Backend rejected this action. Your draft is preserved.',
    'contract': 'The response or evidence is invalid. Submission is blocked.',
    'persistence': 'The operation could not be completed. Check pending work before trying again.',
    'unresolvedCommand': 'This visit already has unresolved work. Resolve it through Sync / Recovery before creating a correction.',
    'invalidMoney': 'Enter a valid nonnegative cash / debt amount.',
    'sampleReason': 'Enter a reason for each sample.',
    'quantityUnavailable': 'The requested quantity exceeds cached vehicle stock.',
    'outsideRoute': 'The shop is outside the assigned route area.',
    'cashRequired': 'Enter cash received for this sale, including zero for credit.',
    'commercial': 'Sale requires Backoffice completion',
    'setJurisdiction': 'Ask Backoffice to complete the shop tax setup, then check again.',
    'contactBackoffice': 'Contact Backoffice to complete the required setup before selling.',
    'ambiguity': 'Which evidence is printed on the returned goods?',
    'lot_number': 'Lot / production identifier', 'production_date': 'Production date',
    'expiry_date': 'Expiry date', 'delivery_date': 'Delivery date',
    'dateHint': 'YYYY-MM-DD', 'damaged': 'Damaged', 'expired': 'Expired',
    'factoryDefect': 'Factory defect', 'cartons': 'Cartons', 'packs': 'Base packs',
    'emptyOutcome': 'Finish without products', 'chooseOutcome': 'Choose the visit outcome.',
    'noSale': 'No sale', 'postponed': 'Postponed — shop closed',
    'noSaleNote': 'No goods required', 'postponedNote': 'Postponed — shop closed',
    'returns': 'Returns / replacement', 'quantities': 'Sale / return quantities',
    'cash': 'Cash received', 'debt': 'Prior debt collected', 'notes': 'Notes',
    'finish': 'Finish visit', 'correct': 'Confirm correction',
  };
  static const _ar = {
    'cancel': 'إلغاء', 'continue': 'متابعة', 'close': 'إغلاق',
    'confirmSale': 'تأكيد البيع', 'preview': 'معاينة فاتورة الخادم — غير معتمدة',
    'committed': 'فاتورة معتمدة — بيانات مالية مجمّدة',
    'pending': 'حُفظت على الجهاز. الإرسال لم يُحسم بعد؛ هذه ليست فاتورة معتمدة.',
    'confirmed': 'تم تأكيد الزيارة من الخادم.',
    'noInvoice': 'لا توجد فاتورة بيع لهذه الزيارة.',
    'readFailed': 'حُفظت الزيارة وتعذرت قراءة الفاتورة. لا تُرسل الزيارة مرة أخرى.',
    'readInvoice': 'عرض الفاتورة المعتمدة', 'retryRead': 'إعادة قراءة الفاتورة',
    'estimate': 'تقدير محلي فقط', 'currency': 'العملة',
    'rounding': 'التقريب', 'halfUp': 'تقريب النصف للأعلى', 'halfEven': 'تقريب النصف للعدد الزوجي',
    'precision': 'المنازل العشرية', 'calculated': 'وقت الحساب', 'revision': 'نسخة الفاتورة',
    'gross': 'الإجمالي', 'discount': 'الخصم', 'postOffer': 'بعد العروض',
    'taxable': 'الخاضع للضريبة', 'tax': 'الضريبة', 'lineTotal': 'إجمالي البنود',
    'adjustment': 'فرق التقريب', 'payable': 'المبلغ النهائي المستحق',
    'connectivity': 'الاتصال غير متاح أو النتيجة لم تُحسم. مسودتك محفوظة.',
    'authorization': 'الوصول غير متاح. تحقق من الجلسة أو تواصل مع الإدارة.',
    'business': 'رفض الخادم العملية. مسودتك محفوظة.',
    'contract': 'الاستجابة أو الأدلة غير صالحة. تم إيقاف الإرسال.',
    'persistence': 'تعذر إكمال العملية. تحقق من العمليات المعلقة قبل المحاولة مجددًا.',
    'unresolvedCommand': 'لهذه الزيارة عملية غير محسومة. عالجها من المزامنة / الاسترداد قبل إنشاء تصحيح.',
    'invalidMoney': 'أدخل مبلغ كاش / تحصيل ذمة صحيحًا وغير سالب.',
    'sampleReason': 'أدخل سببًا لكل عينة.',
    'quantityUnavailable': 'الكمية المطلوبة تتجاوز رصيد السيارة المحلي.',
    'outsideRoute': 'المحل خارج المنطقة المخصصة للمسار.',
    'cashRequired': 'أدخل الكاش المستلم لهذا البيع، بما فيه صفر للبيع الآجل.',
    'commercial': 'البيع يحتاج إكمال بيانات من الإدارة',
    'setJurisdiction': 'اطلب من الإدارة إكمال إعداد الضريبة للمحل ثم تحقق مجددًا.',
    'contactBackoffice': 'تواصل مع الإدارة لإكمال الإعداد المطلوب قبل البيع.',
    'ambiguity': 'ما الدليل المطبوع على البضاعة المرتجعة؟',
    'lot_number': 'رقم التشغيلة / الإنتاج', 'production_date': 'تاريخ الإنتاج',
    'expiry_date': 'تاريخ الانتهاء', 'delivery_date': 'تاريخ التسليم',
    'dateHint': 'YYYY-MM-DD', 'damaged': 'تالف', 'expired': 'منتهي الصلاحية',
    'factoryDefect': 'عيب مصنع', 'cartons': 'كراتين', 'packs': 'عبوات أساسية',
    'emptyOutcome': 'إنهاء بدون منتجات', 'chooseOutcome': 'اختر نتيجة الزيارة.',
    'noSale': 'لا يحتاج بضاعة', 'postponed': 'تأجيل — المحل مغلق',
    'noSaleNote': 'لا يحتاج بضاعة حاليًا', 'postponedNote': 'تأجيل — المحل مغلق',
    'returns': 'مرتجعات / استبدال', 'quantities': 'كميات البيع / المرتجعات',
    'cash': 'الكاش المستلم', 'debt': 'تحصيل ذمة سابقة', 'notes': 'ملاحظات',
    'finish': 'إنهاء الزيارة', 'correct': 'تأكيد التصحيح',
  };
}
