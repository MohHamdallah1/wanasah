import type { Shortage } from "@/types/dispatch";

export type GroupLine = {
  zoneId: number;
  shopId: number;
  driverId: number | null;
  productId: number;
  quantity: number;
};
export type GroupDraftLine = {
  productId: string;
  productName: string;
  quantity: number;
};
export type GroupIntent = {
  kind: "DISPATCH_SHORTAGE_GROUP_V1";
  action: "edit" | "delete";
  shortageIds: number[];
  items: GroupLine[];
  /** Presentation only. Never sent to the mutation API. */
  draft: GroupDraftLine[];
};
export type GroupResponse = { requestId: string; shortageIds: number[] };

const positive = (n: number): boolean => Number.isSafeInteger(n) && n > 0;
const numberId = (s: unknown): number | null => {
  const v = typeof s === "number" ? s
    : typeof s === "string" && /^[1-9]\d{0,15}$/.test(s) ? Number(s) : NaN;
  return positive(v) ? v : null;
};
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/** The logout-preserved key is bound to BOTH authoritative identity fields.
 * One unresolved command per actor blocks a new, potentially conflicting intent.
 */
export function shortageGroupScope(): string | null {
  try {
    const company = localStorage.getItem("company_id");
    const principal = localStorage.getItem("principal_id");
    if (numberId(company) === null || numberId(principal) === null) return null;
    return `wanasah:backoffice-identity:shortage-group:v1:${company}:${principal}`;
  } catch { return null; }
}

export function buildGroupIntent(
  ids: readonly string[], items: readonly GroupLine[], draft: readonly GroupDraftLine[] = [],
): GroupIntent {
  const shortageIds = ids.map(numberId);
  if (!shortageIds.length || shortageIds.length > 500 ||
    shortageIds.some(n => n === null) ||
    new Set(shortageIds).size !== shortageIds.length ||
    items.length > 500 || (!items.length && draft.length > 0) ||
    items.some(i => !positive(i.zoneId) || !positive(i.shopId) ||
      (i.driverId !== null && !positive(i.driverId)) ||
      !positive(i.productId) || !positive(i.quantity)) ||
    new Set(items.map(i => `${i.shopId}:${i.productId}`)).size !== items.length ||
    items.some(i => i.zoneId !== items[0]?.zoneId || i.shopId !== items[0]?.shopId) ||
    (items.length && (draft.length !== items.length ||
      draft.some((d, index) => Number(d.productId) !== items[index].productId ||
        d.quantity !== items[index].quantity || !d.productName || d.productName.length > 300)))) {
    throw new Error("INVALID_SHORTAGE_GROUP");
  }
  return {
    kind: "DISPATCH_SHORTAGE_GROUP_V1",
    action: items.length ? "edit" : "delete",
    shortageIds: shortageIds as number[],
    items: items.map(x => ({ ...x })),
    draft: draft.map(x => ({ ...x })),
  };
}

export function isGroupIntent(value: unknown): value is GroupIntent {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const x = value as Partial<GroupIntent>;
  if (x.kind !== "DISPATCH_SHORTAGE_GROUP_V1" ||
    !Array.isArray(x.shortageIds) || !Array.isArray(x.items) ||
    !Array.isArray(x.draft) || !["edit", "delete"].includes(String(x.action))) return false;
  try {
    const expected = buildGroupIntent(
      x.shortageIds.map(String), x.items as GroupLine[], x.draft as GroupDraftLine[],
    );
    const sameFields = (left: Record<string, unknown>, right: Record<string, unknown>): boolean =>
      Object.keys(left).length === Object.keys(right).length &&
      Object.entries(right).every(([key, val]) => left[key] === val);
    return x.action === expected.action &&
      Object.keys(x).length === Object.keys(expected).length &&
      x.shortageIds.every((id, i) => id === expected.shortageIds[i]) &&
      x.items.every((item, i) =>
        item && typeof item === "object" &&
        sameFields(item as unknown as Record<string, unknown>,
          expected.items[i] as unknown as Record<string, unknown>)) &&
      x.draft.every((item, i) =>
        item && typeof item === "object" &&
        sameFields(item as unknown as Record<string, unknown>,
          expected.draft[i] as unknown as Record<string, unknown>));
  } catch { return false; }
}

export function groupMutationBody(requestId: string, intent: GroupIntent) {
  if (!UUID.test(requestId) || !isGroupIntent(intent)) throw new Error("INVALID_SHORTAGE_COMMAND");
  return { request_id: requestId, shortage_ids: intent.shortageIds, items: intent.items };
}

export function parseGroupResponse(raw: unknown, requestId: string): GroupResponse | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const r = raw as { request_id?: unknown; shortage_ids?: unknown };
  if (r.request_id !== requestId || !Array.isArray(r.shortage_ids) ||
    r.shortage_ids.length > 500 || !r.shortage_ids.every(n => numberId(n) !== null) ||
    new Set(r.shortage_ids.map(Number)).size !== r.shortage_ids.length) return null;
  return { requestId, shortageIds: r.shortage_ids.map(Number) };
}

/** An authenticated 200 on the ORIGINAL idempotency key is the server's
 * authoritative commit receipt. An authorized fresh list GET provides current
 * state, NOT an immutable snapshot of the original replacement rows: later
 * routing, fulfilment, edit or deletion can legitimately change those rows.
 *
 * Never reconcile from GET alone. Old IDs still visible, malformed list, or
 * mismatched server receipt remain UNKNOWN. A changed readback confirms only
 * the original commit, and must NOT claim its rows are still pending/current.
 */
const isAuthorizedShortageRow = (raw: unknown): raw is Shortage => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return false;
  const row = raw as Partial<Shortage>;
  return numberId(row.id) !== null && numberId(row.productId) !== null &&
    numberId(row.shopId) !== null && numberId(row.zoneId) !== null &&
    Number.isSafeInteger(row.quantity) && Number(row.quantity) > 0 &&
    (row.status === "pending" || row.status === "fulfilled") &&
    typeof row.productName === "string" && typeof row.shopName === "string" &&
    typeof row.zoneName === "string";
};

export function groupReadbackVerdict(
  raw: unknown, intent: GroupIntent, receipt: GroupResponse,
): "exact" | "subsequently-changed" | null {
  if (!Array.isArray(raw) || receipt.shortageIds.length !== intent.items.length ||
    !raw.every(isAuthorizedShortageRow)) return null;
  const all = raw as Shortage[];
  if (new Set(all.map(r => Number(r.id))).size !== all.length ||
      all.some(r => intent.shortageIds.includes(Number(r.id)))) return null;
  if (!intent.items.length) return receipt.shortageIds.length === 0 ? "exact" : null;
  const byId = new Map(all.map(row => [Number(row.id), row]));
  const lines = receipt.shortageIds.map(id => byId.get(id));
  if (lines.some(x => !x || x.status !== "pending")) return "subsequently-changed";
  const expected = new Map(intent.items.map(x => [x.productId, x]));
  const matches = lines.every(row => {
    const x = expected.get(Number(row!.productId));
    return Boolean(x && Number(row!.shopId) === x.shopId &&
      Number(row!.zoneId) === x.zoneId &&
      Number(row!.quantity) === x.quantity &&
      (x.driverId === null || Number(row!.driverId) === x.driverId));
  }) && new Set(lines.map(row => row!.productId)).size === intent.items.length;
  return matches ? "exact" : "subsequently-changed";
}

/** Compatibility for strict current-row readback comparisons in callers/tests.
 * True does NOT prove historical commit without the matching server receipt.
 */
export function verifiedGroupReadback(
  raw: unknown, intent: GroupIntent, receipt: GroupResponse,
): raw is Shortage[] {
  return groupReadbackVerdict(raw, intent, receipt) === "exact";
}

export function groupText(language: string, key: keyof typeof messages.en): string {
  return messages[language.toLowerCase().startsWith("ar") ? "ar" : "en"][key];
}
const messages = {
  ar: {
    pending: "هناك تعديل أو حذف مجموعة نواقص لم تتأكد نتيجته. سنحتفظ بالطلب الأصلي حتى نتحقق منه.",
    retry: "التحقق وإعادة محاولة نفس الطلب",
    inProgress: "جاري التحقق من نتيجة العملية...",
    blocked: "تعذّر قراءة المحاولة المحفوظة بأمان أو انتهت الصلاحية. لم نرسل أي تعديل جديد.",
    different: "يوجد طلب سابق غير محسوم. لا يمكن بدء عملية مختلفة حتى يُراجع طلب النواقص الأصلي.",
    noLock: "المتصفح لا يدعم منع تكرار العملية بين التبويبات. لم نرسل الطلب.",
    otherTab: "تبويب آخر يعالج النواقص الآن؛ لم نرسل طلباً ثانياً.",
    otherTabResolved: "تم تحديث النواقص من الخادم بعد إغلاق المحاولة في تبويب آخر. لم نرسل طلباً جديداً ولم نفترض نجاحاً هنا.",
    changedAttempt: "توجد محاولة أخرى محفوظة من تبويب مختلف. عرضنا المحاولة الجديدة ولم نرسل طلب التعديل أو الحذف القديم.",
    historicalCommit: "أكد الخادم تنفيذ العملية الأصلية. تحديث القائمة أظهر تغييرات لاحقة؛ عرضنا الحالة الحالية دون إعادة تنفيذ العملية.",
    serverReference: "مرجع طلب الخادم",
    unknown: "نتيجة الحفظ غير مؤكدة. لم نعتبر العملية ناجحة، ويمكن التحقق بنفس الطلب الأصلي.",
    readback: "وصل رد الحفظ، لكن تعذّر التحقق من قائمة النواقص. لم نعلن النجاح.",
    denied: "لا تملك صلاحية متابعة هذه العملية. المحاولة الأصلية محفوظة للمراجعة.",
    conflict: "تعارض الطلب مع تغييرات أحدث. لم نعد إرسال طلب مختلف.",
    stale: "لم يعتمد الخادم هذا الطلب. راجع المجموعة قبل بدء عملية جديدة.",
    successEdit: "تم التحقق من حفظ تعديل مجموعة النواقص.",
    successChanged: "أكد الخادم نجاح العملية الأصلية، لكن النواقص تغيرت لاحقاً. هذه القائمة تعرض الحالة الحالية وليست نتيجة التعديل القديمة.",
    successDelete: "تم التحقق من حذف مجموعة النواقص كاملة.",
    reference: "مرجع المتابعة",
    edit: "تعديل",
    delete: "حذف الكل",
  },
  en: {
    pending: "A shortage group edit or deletion remains unverified. The original request is preserved until reconciliation.",
    retry: "Verify and retry the same original request",
    inProgress: "Verifying the operation...",
    blocked: "Cannot safely read the saved attempt or authority was revoked. No new update was sent.",
    different: "Another unresolved shortage group operation exists. Review it before starting a different action.",
    noLock: "This browser cannot safely prevent duplicate writes across tabs. No request was sent.",
    otherTab: "Another tab is processing shortages. No second request was sent.",
    otherTabResolved: "The server shortage list was refreshed after another tab cleared the attempt. No new write or success claim was made here.",
    changedAttempt: "Another tab saved a different pending operation. Its details are now displayed; the previous Retry did not send anything.",
    historicalCommit: "The server confirmed the original operation. The fresh shortage list reflects subsequent changes; the operation was not executed again.",
    serverReference: "Server request reference",
    unknown: "The save result is uncertain. No success was claimed; recover using the same original request.",
    readback: "The server responded but the shortage list could not be verified. No success was claimed.",
    denied: "You are not authorized to continue. The original attempt is retained for review.",
    conflict: "This request conflicts with newer data. We did not send a different request.",
    stale: "The server rejected the original selection. Review the group before another action.",
    successEdit: "Verified shortage group changes.",
    successChanged: "The server confirmed the original operation; shortages changed afterwards. This list reflects the current state, not the old edit result.",
    successDelete: "Verified deletion of the entire shortage group.",
    reference: "Tracking reference",
    edit: "Edit",
    delete: "Delete all",
  },
} as const;

/** The request's HTTP log reference is separate from the idempotency UUID.
 * It is diagnostic only; never proof of a successful write.
 */
export function saveGroupHttpReference(scope: string, operationId: string, value: string | undefined): void {
  if (!value || !/^[A-Za-z0-9._:-]{1,100}$/.test(value)) return;
  try {
    localStorage.setItem(`${scope}:http-ref`,
      JSON.stringify({ operationId, value }));
  } catch { /* The immutable command remains protected independently. */ }
}

export function readGroupHttpReference(scope: string, operationId: string): string | null {
  try {
    const raw = localStorage.getItem(`${scope}:http-ref`);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    const ref = parsed as { operationId?: unknown; value?: unknown };
    return ref.operationId === operationId && typeof ref.value === "string" &&
      /^[A-Za-z0-9._:-]{1,100}$/.test(ref.value) ? ref.value : null;
  } catch { return null; }
}

export function clearGroupHttpReference(scope: string): void {
  try { localStorage.removeItem(`${scope}:http-ref`); } catch { /* no mutation is implied */ }
}
