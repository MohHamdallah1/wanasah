from __future__ import annotations

from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parent

MAIN = ROOT / "dashboard" / "src" / "pages" / "inventory" / "MainInventory.tsx"
TAB = ROOT / "dashboard" / "src" / "pages" / "inventory" / "Tab3Stocktake.tsx"
UTILS = ROOT / "dashboard" / "src" / "pages" / "inventory" / "inventoryUtils.ts"

BASELINE_BLOB_SHAS = {
    MAIN: "52b99eb079a51ffb58644d580528448bdd75ed30",
    TAB: "6063946e2aa405bc556a21784bfb98e12c2d8973",
    UTILS: "251575b697bbb94085b1f71ffcf9f7cabe7fe085",
}


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def normalize_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"UNCHANGED={label}")
        return text
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected exactly 1 match, found {count}")
    print(f"PATCHED={label}")
    return text.replace(old, new, 1)


# 0) Verify exact dev-mainInv3 baseline before writing ANY file.
for path, expected in BASELINE_BLOB_SHAS.items():
    if not path.exists():
        fail(f"Missing baseline file: {path.relative_to(ROOT)}")
    actual = git_blob_sha(normalize_bytes(path))
    if actual != expected:
        fail(
            f"Baseline mismatch for {path.relative_to(ROOT)}: "
            f"expected {expected}, got {actual}. No files changed."
        )

main = read(MAIN)
tab = read(TAB)
utils = read(UTILS)


# 1) inventoryUtils: stock_status is part of legal stocktake line identity.
utils = replace_once(
    utils,
    '''export interface StocktakeRow {
  row_key: string;
  product_variant_id: number;
  batch_id: number | null;
  product_name: string;''',
    '''export type StocktakeStockStatus = "AVAILABLE" | "DAMAGED";

export interface StocktakeRow {
  row_key: string;
  product_variant_id: number;
  batch_id: number | null;
  stock_status: StocktakeStockStatus;
  product_name: string;''',
    "stocktake_row_stock_status",
)


# 2) MainInventory: pass company identity only for UI persistence scoping.
main = replace_once(
    main,
    '''          <Tab3Stocktake
            locationId={selectedLocationId} // +++ سحق ملاحظة P1: تمرير الموقع للمحرك המوحد +++
            isAuditLocked={isAuditLocked}''',
    '''          <Tab3Stocktake
            locationId={selectedLocationId} // +++ سحق ملاحظة P1: تمرير الموقع للمحرك המوحد +++
            companyId={companyId}
            isAuditLocked={isAuditLocked}''',
    "stocktake_company_ui_scope_prop",
)


# 3) Tab3 imports / types / transport boundary.
tab = replace_once(
    tab,
    '''import type { StocktakeRow } from "./inventoryUtils";''',
    '''import type {
  StocktakeRow,
  StocktakeStockStatus,
} from "./inventoryUtils";''',
    "stocktake_status_type_import",
)

tab = replace_once(
    tab,
    '''interface Props {
  locationId: number;
  isAuditLocked: boolean;
  authenticatedFetch: (url: string, opts?: RequestInit) => Promise<any>;
  onLockChange: (locked: boolean) => void;
}''',
    '''interface Props {
  locationId: number;
  companyId: string;
  isAuditLocked: boolean;
  authenticatedFetch: (url: string, opts?: RequestInit) => Promise<unknown>;
  onLockChange: (locked: boolean) => void;
}''',
    "stocktake_strict_transport_prop",
)

tab = replace_once(
    tab,
    '''interface CountSheetItem {
  product_variant_id: number;
  batch_id: number | null;
  product_name: string;''',
    '''interface CountSheetItem {
  product_variant_id: number;
  batch_id: number | null;
  stock_status: StocktakeStockStatus;
  product_name: string;''',
    "count_sheet_stock_status_contract",
)

tab = replace_once(
    tab,
    '''interface ReviewLine {
  attempt_line_id: number;
  product_variant_id: number;
  batch_id: number | null;
  product_name: string;''',
    '''interface ReviewLine {
  attempt_line_id: number;
  product_variant_id: number;
  batch_id: number | null;
  stock_status: StocktakeStockStatus;
  line_origin: "SNAPSHOT" | "DISCOVERED";
  product_name: string;''',
    "review_line_status_origin_contract",
)

helper_anchor = '''const rowKey = (productVariantId: number, batchId: number | null) =>
  `${productVariantId}:${batchId ?? "NO_BATCH"}`;
'''

helper_block = '''const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

const positiveInt = (value: unknown, field: string): number => {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value <= 0
  ) {
    throw new Error(`حقل ${field} غير صالح.`);
  }
  return value;
};

const nonNegativeInt = (value: unknown, field: string): number => {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 0
  ) {
    throw new Error(`حقل ${field} غير صالح.`);
  }
  return value;
};

const requiredString = (value: unknown, field: string): string => {
  if (typeof value !== "string" || !value) {
    throw new Error(`حقل ${field} غير صالح.`);
  }
  return value;
};

const optionalString = (value: unknown): string | null =>
  typeof value === "string" ? value : null;

const parseStockStatus = (value: unknown): StocktakeStockStatus => {
  if (value !== "AVAILABLE" && value !== "DAMAGED") {
    throw new Error("حالة مخزون سطر الجرد غير صالحة.");
  }
  return value;
};

const getErrorMessage = (error: unknown, fallback: string): string =>
  error instanceof Error && error.message ? error.message : fallback;

const parseCountSheet = (raw: unknown): CountSheetItem[] => {
  if (!Array.isArray(raw)) {
    throw new Error("استجابة ورقة الجرد غير صالحة.");
  }

  return raw.map((item, index) => {
    if (!isRecord(item)) {
      throw new Error(`سطر ورقة الجرد #${index + 1} غير صالح.`);
    }

    const batchId =
      item.batch_id === null
        ? null
        : positiveInt(item.batch_id, "batch_id");

    return {
      product_variant_id: positiveInt(
        item.product_variant_id,
        "product_variant_id"
      ),
      batch_id: batchId,
      stock_status: parseStockStatus(item.stock_status),
      product_name: requiredString(item.product_name, "product_name"),
      packs_per_carton: positiveInt(
        item.packs_per_carton,
        "packs_per_carton"
      ),
      batch_number: optionalString(item.batch_number),
      expiry_date: optionalString(item.expiry_date),
    };
  });
};

const parseReviewAttempt = (raw: unknown): ReviewAttempt => {
  if (!isRecord(raw)) {
    throw new Error("بيانات محاولة الجرد غير صالحة.");
  }

  return {
    id: positiveInt(raw.id, "attempt.id"),
    attempt_number: positiveInt(
      raw.attempt_number,
      "attempt.attempt_number"
    ),
    counted_by: positiveInt(raw.counted_by, "attempt.counted_by"),
    counted_by_name: requiredString(
      raw.counted_by_name,
      "attempt.counted_by_name"
    ),
    authorized_by:
      raw.authorized_by === null
        ? null
        : positiveInt(raw.authorized_by, "attempt.authorized_by"),
    authorized_by_name: optionalString(raw.authorized_by_name),
    recount_of_attempt_id:
      raw.recount_of_attempt_id === null ||
      raw.recount_of_attempt_id === undefined
        ? null
        : positiveInt(
            raw.recount_of_attempt_id,
            "attempt.recount_of_attempt_id"
          ),
    recount_reason: optionalString(raw.recount_reason),
    requires_independent_recount:
      raw.requires_independent_recount === true,
    submitted_at: optionalString(raw.submitted_at),
  };
};

const parseReviewLine = (raw: unknown): ReviewLine => {
  if (!isRecord(raw)) {
    throw new Error("سطر مراجعة الجرد غير صالح.");
  }

  const lineOrigin = raw.line_origin;
  if (lineOrigin !== "SNAPSHOT" && lineOrigin !== "DISCOVERED") {
    throw new Error("مصدر سطر الجرد غير صالح.");
  }

  const variance = raw.variance_quantity;
  if (typeof variance !== "number" || !Number.isInteger(variance)) {
    throw new Error("حقل variance_quantity غير صالح.");
  }

  return {
    attempt_line_id: positiveInt(
      raw.attempt_line_id,
      "attempt_line_id"
    ),
    product_variant_id: positiveInt(
      raw.product_variant_id,
      "product_variant_id"
    ),
    batch_id:
      raw.batch_id === null
        ? null
        : positiveInt(raw.batch_id, "batch_id"),
    stock_status: parseStockStatus(raw.stock_status),
    line_origin: lineOrigin,
    product_name: requiredString(raw.product_name, "product_name"),
    packs_per_carton: positiveInt(
      raw.packs_per_carton,
      "packs_per_carton"
    ),
    batch_number: optionalString(raw.batch_number),
    expiry_date: optionalString(raw.expiry_date),
    expected_quantity: nonNegativeInt(
      raw.expected_quantity,
      "expected_quantity"
    ),
    actual_quantity: nonNegativeInt(
      raw.actual_quantity,
      "actual_quantity"
    ),
    variance_quantity: variance,
    notes: optionalString(raw.notes),
  };
};

const parseStocktakeReview = (raw: unknown): StocktakeReview => {
  if (
    !isRecord(raw) ||
    !Array.isArray(raw.attempt_history) ||
    !Array.isArray(raw.lines)
  ) {
    throw new Error("استجابة مراجعة الجرد غير صالحة.");
  }

  const stocktakeType = raw.stocktake_type;
  if (
    stocktakeType !== "FULL_COUNT" &&
    stocktakeType !== "CYCLE_COUNT" &&
    stocktakeType !== "VEHICLE_RECON"
  ) {
    throw new Error("نوع جلسة الجرد غير صالح.");
  }

  return {
    session_id: positiveInt(raw.session_id, "session_id"),
    reference_number: requiredString(
      raw.reference_number,
      "reference_number"
    ),
    stocktake_type: stocktakeType,
    status: requiredString(raw.status, "status"),
    location_id: positiveInt(raw.location_id, "location_id"),
    independent_recount_satisfied:
      raw.independent_recount_satisfied === true,
    latest_attempt: parseReviewAttempt(raw.latest_attempt),
    attempt_history: raw.attempt_history.map(parseReviewAttempt),
    lines: raw.lines.map(parseReviewLine),
  };
};

const parseStartSessionId = (raw: unknown): number => {
  if (!isRecord(raw)) {
    throw new Error("استجابة بدء الجرد غير صالحة.");
  }
  return positiveInt(raw.session_id, "session_id");
};

const readMessage = (raw: unknown): string | null =>
  isRecord(raw) && typeof raw.message === "string"
    ? raw.message
    : null;

const parseRecountRequiresIndependent = (raw: unknown): boolean => {
  if (
    !isRecord(raw) ||
    typeof raw.requires_independent_counter !== "boolean"
  ) {
    throw new Error("استجابة تفويض إعادة العد غير صالحة.");
  }
  return raw.requires_independent_counter;
};

const rowKey = (
  productVariantId: number,
  batchId: number | null,
  stockStatus: StocktakeStockStatus
) => `${productVariantId}:${batchId ?? "NO_BATCH"}:${stockStatus}`;
'''

tab = replace_once(
    tab,
    helper_anchor,
    helper_block,
    "stocktake_runtime_parsers_and_row_identity",
)

tab = replace_once(
    tab,
    '''export function Tab3Stocktake({
  locationId,
  isAuditLocked,''',
    '''export function Tab3Stocktake({
  locationId,
  companyId,
  isAuditLocked,''',
    "stocktake_company_prop_destructure",
)

tab = replace_once(
    tab,
    '''  const sessionKey = `unified_stocktake_session_${locationId}`;
  const phaseKey = `unified_stocktake_phase_${locationId}`;
  const [sessionId, setSessionId] = useState<string | null>(null);
  const draftKey = sessionId
    ? `wanasah_audit_draft_${locationId}_${sessionId}`
    : null;''',
    '''  const companyScope = companyId || "anonymous";
  const sessionKey =
    `unified_stocktake_session:${companyScope}:${locationId}`;
  const phaseKey =
    `unified_stocktake_phase:${companyScope}:${locationId}`;
  const [sessionId, setSessionId] = useState<string | null>(null);
  const draftKey = sessionId
    ? `wanasah_audit_draft:${companyScope}:${locationId}:${sessionId}`
    : null;''',
    "tenant_scoped_stocktake_storage_keys",
)


# 4) Count sheet: parse stock_status and use (product,batch,status) identity.
tab = replace_once(
    tab,
    '''    const data = await authenticatedFetch(
      `/warehouse/unified/stocktake/${sid}/count-sheet`
    ) as CountSheetItem[];

    if (!Array.isArray(data)) {
      throw new Error("استجابة ورقة الجرد غير صالحة.");
    }

    const baseRows: StocktakeRow[] = data.map((item) => ({
      row_key: rowKey(item.product_variant_id, item.batch_id),
      product_variant_id: item.product_variant_id,
      batch_id: item.batch_id,
      product_name: item.product_name,''',
    '''    const raw = await authenticatedFetch(
      `/warehouse/unified/stocktake/${sid}/count-sheet`
    );
    const data = parseCountSheet(raw);

    const baseRows: StocktakeRow[] = data.map((item) => ({
      row_key: rowKey(
        item.product_variant_id,
        item.batch_id,
        item.stock_status
      ),
      product_variant_id: item.product_variant_id,
      batch_id: item.batch_id,
      stock_status: item.stock_status,
      product_name: item.product_name,''',
    "count_sheet_runtime_parse_and_status_identity",
)

tab = replace_once(
    tab,
    '''    const key = `wanasah_audit_draft_${locationId}_${sid}`;''',
    '''    const key =
      `wanasah_audit_draft:${companyScope}:${locationId}:${sid}`;''',
    "tenant_scoped_count_draft_key",
)


# 5) Review reads: fail closed instead of unsafe assertions.
tab = replace_once(
    tab,
    '''    const data = await authenticatedFetch(
      `/warehouse/unified/stocktake/${sid}/review`
    ) as StocktakeReview;

    setSessionId(sid);
    setReview(data);''',
    '''    const raw = await authenticatedFetch(
      `/warehouse/unified/stocktake/${sid}/review`
    );
    const data = parseStocktakeReview(raw);

    if (data.location_id !== locationId) {
      throw new Error(
        "مرفوض: جلسة الجرد لا تطابق المستودع المحدد حالياً."
      );
    }

    setSessionId(sid);
    setReview(data);''',
    "review_runtime_parse_location_scope",
)

tab = replace_once(
    tab,
    '''        const data = await authenticatedFetch(
          `/warehouse/unified/stocktake/${sid}/review`
        ) as StocktakeReview;

        if (cancelled) return;
        setReview(data);''',
    '''        const raw = await authenticatedFetch(
          `/warehouse/unified/stocktake/${sid}/review`
        );
        const data = parseStocktakeReview(raw);

        if (data.location_id !== locationId) {
          throw new Error(
            "مرفوض: جلسة الجرد المستعادة لا تطابق المستودع المحدد."
          );
        }

        if (cancelled) return;
        setReview(data);''',
    "recovery_review_runtime_parse_location_scope",
)


# 6) Remove explicit any catches.
for old, new, label in [
    (
        '''      } catch (e: any) {
        if (cancelled) return;''',
        '''      } catch (error: unknown) {
        if (cancelled) return;''',
        "recovery_unknown_error",
    ),
    (
        '''        toast.error(e?.message || "تعذر استعادة جلسة الجرد الحالية.");''',
        '''        toast.error(
          getErrorMessage(
            error,
            "تعذر استعادة جلسة الجرد الحالية."
          )
        );''',
        "recovery_error_message",
    ),
    (
        '''    } catch (e: any) {
      toast.error(e?.message || "فشل بدء جلسة الجرد.");''',
        '''    } catch (error: unknown) {
      toast.error(
        getErrorMessage(error, "فشل بدء جلسة الجرد.")
      );''',
        "start_unknown_error",
    ),
    (
        '''    } catch (e: any) {
      toast.error(e?.message || "فشل تثبيت محاولة الجرد.");''',
        '''    } catch (error: unknown) {
      toast.error(
        getErrorMessage(error, "فشل تثبيت محاولة الجرد.")
      );''',
        "submit_unknown_error",
    ),
    (
        '''    } catch (e: any) {
      toast.error(e?.message || "فشل اعتماد الجرد.");''',
        '''    } catch (error: unknown) {
      toast.error(
        getErrorMessage(error, "فشل اعتماد الجرد.")
      );''',
        "approve_unknown_error",
    ),
    (
        '''    } catch (e: any) {
      toast.error(e?.message || "فشل تفويض إعادة الجرد.");''',
        '''    } catch (error: unknown) {
      toast.error(
        getErrorMessage(error, "فشل تفويض إعادة الجرد.")
      );''',
        "recount_unknown_error",
    ),
    (
        '''    } catch (e: any) {
      toast.error(e?.message || "فشل إلغاء جلسة الجرد.");''',
        '''    } catch (error: unknown) {
      toast.error(
        getErrorMessage(error, "فشل إلغاء جلسة الجرد.")
      );''',
        "cancel_unknown_error",
    ),
]:
    tab = replace_once(tab, old, new, label)


# 7) Start response: no implicit any.
tab = replace_once(
    tab,
    '''      const data = await authenticatedFetch(
        "/warehouse/unified/stocktake/start",
        {
          method: "POST",
          body: JSON.stringify({
            location_id: locationId,
            stocktake_type: "FULL_COUNT",
            notes: "بدء جرد مركزي",
          }),
        }
      );

      const sid = String(data.session_id);''',
    '''      const raw = await authenticatedFetch(
        "/warehouse/unified/stocktake/start",
        {
          method: "POST",
          body: JSON.stringify({
            location_id: locationId,
            stocktake_type: "FULL_COUNT",
            notes: "بدء جرد مركزي",
          }),
        }
      );

      const sid = String(parseStartSessionId(raw));''',
    "start_response_runtime_parse",
)


# 8) Count payload MUST carry stock_status.
tab = replace_once(
    tab,
    '''    const items = rows.map((row) => ({
      product_variant_id: row.product_variant_id,
      batch_id: row.batch_id,
      actual_quantity: toTotalPacks(''',
    '''    const items = rows.map((row) => ({
      product_variant_id: row.product_variant_id,
      batch_id: row.batch_id,
      stock_status: row.stock_status,
      actual_quantity: toTotalPacks(''',
    "submit_count_stock_status_contract",
)


# 9) Approval optimistic concurrency count_attempt_id.
tab = replace_once(
    tab,
    '''  const handleApprove = async () => {
    if (!sessionId) return;
    if (!approvePassword) {''',
    '''  const handleApprove = async () => {
    if (!sessionId) return;
    if (!review) {
      toast.error("مراجعة الجرد الحالية غير موجودة.");
      return;
    }
    if (!approvePassword) {''',
    "approve_requires_current_review",
)

tab = replace_once(
    tab,
    '''          body: JSON.stringify({
            password: approvePassword,
            notes: approveNotes || null,
          }),''',
    '''          body: JSON.stringify({
            count_attempt_id: review.latest_attempt.id,
            password: approvePassword,
            notes: approveNotes || null,
          }),''',
    "approve_count_attempt_id_contract",
)

tab = replace_once(
    tab,
    '''      const data = await authenticatedFetch(
        `/warehouse/unified/stocktake/${sessionId}/approve`,''',
    '''      const raw = await authenticatedFetch(
        `/warehouse/unified/stocktake/${sessionId}/approve`,''',
    "approve_unknown_response",
)
tab = replace_once(
    tab,
    '''      toast.success(data?.message || "تم اعتماد الجرد وترحيل الفروقات بنجاح.");''',
    '''      toast.success(
        readMessage(raw) ||
          "تم اعتماد الجرد وترحيل الفروقات بنجاح."
      );''',
    "approve_response_message_parse",
)


# 10) Recount optimistic concurrency count_attempt_id.
tab = replace_once(
    tab,
    '''  const handleRecount = async () => {
    if (!sessionId) return;

    if (recountReason.trim().length < 5) {''',
    '''  const handleRecount = async () => {
    if (!sessionId) return;
    if (!review) {
      toast.error("مراجعة الجرد الحالية غير موجودة.");
      return;
    }

    if (recountReason.trim().length < 5) {''',
    "recount_requires_current_review",
)

tab = replace_once(
    tab,
    '''      const data = await authenticatedFetch(
        `/warehouse/unified/stocktake/${sessionId}/recount`,
        {
          method: "POST",
          body: JSON.stringify({
            reason: recountReason.trim(),''',
    '''      const raw = await authenticatedFetch(
        `/warehouse/unified/stocktake/${sessionId}/recount`,
        {
          method: "POST",
          body: JSON.stringify({
            count_attempt_id: review.latest_attempt.id,
            reason: recountReason.trim(),''',
    "recount_count_attempt_id_contract",
)

tab = replace_once(
    tab,
    '''      if (data?.requires_independent_counter) {''',
    '''      if (parseRecountRequiresIndependent(raw)) {''',
    "recount_response_runtime_parse",
)


# 11) Cancel response no implicit any.
tab = replace_once(
    tab,
    '''      const data = await authenticatedFetch(
        `/warehouse/unified/stocktake/${sessionId}/cancel`,''',
    '''      const raw = await authenticatedFetch(
        `/warehouse/unified/stocktake/${sessionId}/cancel`,''',
    "cancel_unknown_response",
)
tab = replace_once(
    tab,
    '''      toast.success(data?.message || "تم إلغاء جلسة الجرد وفك الأقفال.");''',
    '''      toast.success(
        readMessage(raw) ||
          "تم إلغاء جلسة الجرد وفك الأقفال."
      );''',
    "cancel_response_message_parse",
)


# 12) Match text limits from schemas.
tab = replace_once(
    tab,
    '''              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="أي ملاحظات عن العد الفعلي..."''',
    '''              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              maxLength={4000}
              placeholder="أي ملاحظات عن العد الفعلي..."''',
    "count_notes_max_length",
)

tab = replace_once(
    tab,
    '''              value={approveNotes}
              onChange={(e) => setApproveNotes(e.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none resize-none h-20"''',
    '''              value={approveNotes}
              onChange={(e) => setApproveNotes(e.target.value)}
              maxLength={500}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none resize-none h-20"''',
    "approve_notes_max_length",
)

tab = replace_once(
    tab,
    '''              value={recountReason}
              onChange={(e) => setRecountReason(e.target.value)}
              placeholder="مثال: فرق غير مبرر ويحتاج عد مستقل..."''',
    '''              value={recountReason}
              onChange={(e) => setRecountReason(e.target.value)}
              maxLength={500}
              placeholder="مثال: فرق غير مبرر ويحتاج عد مستقل..."''',
    "recount_reason_max_length",
)

tab = replace_once(
    tab,
    '''                value={authorizerUsername}
                onChange={(e) => setAuthorizerUsername(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500"''',
    '''                value={authorizerUsername}
                onChange={(e) => setAuthorizerUsername(e.target.value)}
                maxLength={80}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500"''',
    "recount_username_max_length",
)

tab = replace_once(
    tab,
    '''              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none resize-none h-20"''',
    '''              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
              maxLength={500}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none resize-none h-20"''',
    "cancel_reason_max_length",
)


# 13) Final static behavior gates BEFORE writes.
checks = {
    "NO_EXPLICIT_ANY": ": any" not in tab and "Promise<any>" not in tab,
    "COUNT_STATUS_FIELD": "stock_status: row.stock_status" in tab,
    "ROW_IDENTITY_INCLUDES_STATUS": "stockStatus: StocktakeStockStatus" in tab,
    "APPROVE_ATTEMPT_ID": "count_attempt_id: review.latest_attempt.id" in tab,
    "RECOUNT_ATTEMPT_ID": tab.count("count_attempt_id: review.latest_attempt.id") == 2,
    "TENANT_SESSION_KEY": "unified_stocktake_session:${companyScope}:${locationId}" in tab,
    "TENANT_PHASE_KEY": "unified_stocktake_phase:${companyScope}:${locationId}" in tab,
    "TENANT_DRAFT_KEY": "wanasah_audit_draft:${companyScope}:${locationId}:${sessionId}" in tab,
    "REVIEW_LOCATION_FAIL_CLOSED": (
        "جلسة الجرد لا تطابق المستودع المحدد حالياً" in tab
        and "جلسة الجرد المستعادة لا تطابق المستودع المحدد" in tab
    ),
    "MAIN_PASSES_COMPANY": "companyId={companyId}" in main,
    "UTILS_STOCK_STATUS": "stock_status: StocktakeStockStatus;" in utils,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail("Static verification failed before writes: " + ", ".join(failed))


# 14) Write only after all checks pass.
UTILS.write_text(utils, encoding="utf-8")
MAIN.write_text(main, encoding="utf-8")
TAB.write_text(tab, encoding="utf-8")

print("STOCKTAKE_COUNT_STOCK_STATUS=OK")
print("STOCKTAKE_ROW_IDENTITY_STATUS_SAFE=OK")
print("STOCKTAKE_APPROVAL_ATTEMPT_CONCURRENCY=OK")
print("STOCKTAKE_RECOUNT_ATTEMPT_CONCURRENCY=OK")
print("STOCKTAKE_TENANT_UI_STORAGE_SCOPE=OK")
print("STOCKTAKE_REVIEW_LOCATION_FAIL_CLOSED=OK")
print("STOCKTAKE_EXPLICIT_ANY_REMOVED=OK")
print("STOCKTAKE_SCHEMA_TEXT_LIMITS=OK")
print("MAIN_INVENTORY_STAGE4A1_STOCKTAKE_CONTRACT_REPAIR=OK")
