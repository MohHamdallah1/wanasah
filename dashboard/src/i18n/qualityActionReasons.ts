export const qualityActionReasons = {
  ar: {
    title: "لماذا لا يظهر إجراء الآن؟",
    reasons: {
      NO_CONFIGURED_DESTINATION: "لم يتم إعداد وجهة هذا الإجراء في إعدادات الشركة.",
      PERMISSION_REQUIRED: "صلاحياتك الحالية لا تسمح بتنفيذ هذا الإجراء من هذا الموقع أو إلى وجهته.",
      SOURCE_CANNOT_SEND: "هذا الموقع لا يسمح بإرسال الكمية منه حالياً.",
      NO_MOVABLE_QUANTITY: "لا توجد كمية حرة يمكن نقلها؛ الكمية المتاحة محجوزة أو تساوي صفراً.",
      ALREADY_AT_DESTINATION: "الكمية موجودة بالفعل في الوجهة المخصصة لهذا الإجراء.",
      STATE_RESTRICTION: "حالة المنتج أو الدفعة أو الرصيد الحالية لا تسمح بهذا الإجراء.",
    },
  },
  en: {
    title: "Why is no action available?",
    reasons: {
      NO_CONFIGURED_DESTINATION: "The company has not configured a destination for this action.",
      PERMISSION_REQUIRED: "Your current permissions do not allow this action from this source or to its destination.",
      SOURCE_CANNOT_SEND: "This source cannot send stock right now.",
      NO_MOVABLE_QUANTITY: "There is no free quantity to move; the available stock is reserved or zero.",
      ALREADY_AT_DESTINATION: "This quantity is already at the configured destination for this action.",
      STATE_RESTRICTION: "The current product, batch, or stock state does not allow this action.",
    },
  },
} as const;
