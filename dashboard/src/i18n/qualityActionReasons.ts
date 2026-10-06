export const qualityActionReasons = {
  ar: {
    title: "لماذا لا يظهر إجراء الآن؟",
    setupRequiredTitle: "يلزم إعداد وجهات المعالجة أولًا",
    setupRequiredHint: "لم تحدد الشركة بعد أين تُجمع الكمية المتأثرة أو تُجهز مرتجعات المورد أو الإتلاف. هذا إعداد تشغيلي مرة واحدة، وبعد تفعيله ستظهر الإجراءات المسموح بها تلقائيًا.",
    configure: "إعداد وجهات المعالجة",
    reasons: {
      NO_CONFIGURED_DESTINATION: "لم يتم إعداد وجهة هذا الإجراء. افتح إدارة المستودعات ثم «وجهات معالجة الجودة والمخزون المقيّد».",
      PERMISSION_REQUIRED: "صلاحياتك الحالية لا تسمح بتنفيذ هذا الإجراء من هذا الموقع أو إلى وجهته.",
      SOURCE_CANNOT_SEND: "هذا الموقع لا يسمح بإرسال الكمية منه حالياً.",
      NO_MOVABLE_QUANTITY: "لا توجد كمية حرة يمكن نقلها؛ الكمية المتاحة محجوزة أو تساوي صفراً.",
      ALREADY_AT_DESTINATION: "الكمية موجودة بالفعل في الوجهة المخصصة لهذا الإجراء.",
      STATE_RESTRICTION: "حالة المنتج أو الدفعة أو الرصيد الحالية لا تسمح بهذا الإجراء.",
    },
  },
  en: {
    title: "Why is no action available?",
    setupRequiredTitle: "Configure handling destinations first",
    setupRequiredHint: "The company has not yet defined where affected stock is collected, supplier returns are staged, or disposal is prepared. Configure this once and the allowed actions will appear automatically.",
    configure: "Configure handling destinations",
    reasons: {
      NO_CONFIGURED_DESTINATION: "No destination is configured for this action. Open Warehouse management, then Quality and restricted-stock destinations.",
      PERMISSION_REQUIRED: "Your current permissions do not allow this action from this source or to its destination.",
      SOURCE_CANNOT_SEND: "This source cannot send stock right now.",
      NO_MOVABLE_QUANTITY: "There is no free quantity to move; the available stock is reserved or zero.",
      ALREADY_AT_DESTINATION: "This quantity is already at the configured destination for this action.",
      STATE_RESTRICTION: "The current product, batch, or stock state does not allow this action.",
    },
  },
} as const;
