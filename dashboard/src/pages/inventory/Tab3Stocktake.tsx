import { useState, useMemo, useEffect, useCallback } from "react";
import { Lock, AlertTriangle, Check, Scan, ShieldCheck, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/modal";
import { QuantityInput } from "@/components/ui/quantity-input";
import type { WarehouseProduct, StocktakeRow } from "./inventoryUtils";
import { toTotalPacks, formatQty } from "./inventoryUtils";

interface Props {
  products: WarehouseProduct[];
  locationId: number;
  isAuditLocked: boolean;
  authenticatedFetch: (url: string, opts?: RequestInit) => Promise<any>;
  onLockChange: (locked: boolean) => void;
}

type StocktakePhase = "COUNTING" | "REVIEW" | "WAITING_INDEPENDENT";

interface CountSheetItem {
  product_variant_id: number;
  batch_id: number | null;
  product_name: string;
  packs_per_carton: number;
  batch_number: string | null;
  expiry_date: string | null;
}

interface ReviewLine {
  attempt_line_id: number;
  product_variant_id: number;
  batch_id: number | null;
  product_name: string;
  packs_per_carton: number;
  batch_number: string | null;
  expiry_date: string | null;
  expected_quantity: number;
  actual_quantity: number;
  variance_quantity: number;
  notes?: string | null;
}

interface ReviewAttempt {
  id: number;
  attempt_number: number;
  counted_by: number;
  counted_by_name: string;
  authorized_by: number | null;
  authorized_by_name: string | null;
  recount_of_attempt_id?: number | null;
  recount_reason: string | null;
  requires_independent_recount: boolean;
  submitted_at: string | null;
}

interface StocktakeReview {
  session_id: number;
  reference_number: string;
  stocktake_type: string;
  status: string;
  location_id: number;
  independent_recount_satisfied: boolean;
  latest_attempt: ReviewAttempt;
  attempt_history: ReviewAttempt[];
  lines: ReviewLine[];
}

const rowKey = (productVariantId: number, batchId: number | null) =>
  `${productVariantId}:${batchId ?? "NO_BATCH"}`;

export function Tab3Stocktake({
  products: _products,
  locationId,
  isAuditLocked,
  authenticatedFetch,
  onLockChange,
}: Props) {
  // products يبقى في Props للتوافق مع MainInventory، لكن الجرد لا يستخدمه حتى لا يتسرب الرصيد المتوقع للعدّاد.
  void _products;

  const [showLockModal, setShowLockModal] = useState(false);
  const [showSubmitModal, setShowSubmitModal] = useState(false);
  const [showVarianceModal, setShowVarianceModal] = useState(false);
  const [showApproveModal, setShowApproveModal] = useState(false);
  const [showRecountModal, setShowRecountModal] = useState(false);
  const [showCancelModal, setShowCancelModal] = useState(false);

  const [phase, setPhase] = useState<StocktakePhase>("COUNTING");
  const [rows, setRows] = useState<StocktakeRow[]>([]);
  const [review, setReview] = useState<StocktakeReview | null>(null);
  const [notes, setNotes] = useState("");

  const [approvePassword, setApprovePassword] = useState("");
  const [approveNotes, setApproveNotes] = useState("");
  const [recountReason, setRecountReason] = useState("");
  const [authorizerUsername, setAuthorizerUsername] = useState("");
  const [authorizerPassword, setAuthorizerPassword] = useState("");
  const [cancelReason, setCancelReason] = useState("");
  const [cancelPassword, setCancelPassword] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [locking, setLocking] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);

  const sessionKey = `unified_stocktake_session_${locationId}`;
  const phaseKey = `unified_stocktake_phase_${locationId}`;
  const [sessionId, setSessionId] = useState<string | null>(null);
  const draftKey = sessionId
    ? `wanasah_audit_draft_${locationId}_${sessionId}`
    : null;

  // تحميل ورقة العد العمياء من السيرفر؛ لا تحتوي أي expected_quantity.
  const loadCountSheet = useCallback(async (sid: string) => {
    const data = await authenticatedFetch(
      `/warehouse/unified/stocktake/${sid}/count-sheet`
    ) as CountSheetItem[];

    if (!Array.isArray(data)) {
      throw new Error("استجابة ورقة الجرد غير صالحة.");
    }

    const baseRows: StocktakeRow[] = data.map((item) => ({
      row_key: rowKey(item.product_variant_id, item.batch_id),
      product_variant_id: item.product_variant_id,
      batch_id: item.batch_id,
      product_name: item.product_name,
      batch_number: item.batch_number,
      expiry_date: item.expiry_date,
      packs_per_carton: item.packs_per_carton || 1,
      actual_cartons: 0,
      actual_loose_packs: 0,
      counted: false,
    }));

    const key = `wanasah_audit_draft_${locationId}_${sid}`;
    const saved = localStorage.getItem(key);

    if (saved) {
      try {
        const parsed = JSON.parse(saved) as StocktakeRow[];
        const savedMap = new Map(
          parsed
            .filter((row) => typeof row?.row_key === "string")
            .map((row) => [row.row_key, row])
        );

        for (const row of baseRows) {
          const old = savedMap.get(row.row_key);
          if (!old) continue;

          row.actual_cartons = Math.max(0, Number(old.actual_cartons) || 0);
          row.actual_loose_packs = Math.max(0, Number(old.actual_loose_packs) || 0);
          row.counted = old.counted === true;
        }
      } catch {
        localStorage.removeItem(key);
      }
    }

    setSessionId(sid);
    setRows(baseRows);
    setReview(null);
    setPhase("COUNTING");
    localStorage.setItem(phaseKey, "COUNTING");
  }, [authenticatedFetch, locationId, phaseKey]);

  // تحميل المراجعة بعد تثبيت محاولة العد؛ هنا فقط يسمح السيرفر بإظهار المتوقع والفروقات.
  const loadReview = useCallback(async (sid: string) => {
    const data = await authenticatedFetch(
      `/warehouse/unified/stocktake/${sid}/review`
    ) as StocktakeReview;

    setSessionId(sid);
    setReview(data);
    setRows([]);
    setPhase("REVIEW");
    localStorage.setItem(phaseKey, "REVIEW");
  }, [authenticatedFetch, phaseKey]);

  // استعادة حالة جلسة الجرد بعد تحديث الصفحة دون كشف المتوقع أثناء مرحلة العد.
  useEffect(() => {
    if (!isAuditLocked) {
      setRows([]);
      setReview(null);
      setSessionId(null);
      setPhase("COUNTING");
      return;
    }

    const sid = localStorage.getItem(sessionKey);
    if (!sid) {
      toast.error("جلسة الجرد النشطة غير موجودة محلياً. أعد تحميل الصفحة أو راجع المسؤول.");
      return;
    }

    setSessionId(sid);

    let cancelled = false;

    const recover = async () => {
      try {
        const data = await authenticatedFetch(
          `/warehouse/unified/stocktake/${sid}/review`
        ) as StocktakeReview;

        if (cancelled) return;
        setReview(data);
        setRows([]);
        setPhase("REVIEW");
        localStorage.setItem(phaseKey, "REVIEW");
        return;
      } catch {
        // طبيعي أثناء COUNTING أو RECOUNT_REQUIRED؛ ننتقل لمحاولة جلب ورقة العد.
      }

      try {
        if (cancelled) return;
        await loadCountSheet(sid);
      } catch (e: any) {
        if (cancelled) return;

        if (localStorage.getItem(phaseKey) === "WAITING_INDEPENDENT") {
          setPhase("WAITING_INDEPENDENT");
          return;
        }

        toast.error(e?.message || "تعذر استعادة جلسة الجرد الحالية.");
      }
    };

    void recover();

    return () => {
      cancelled = true;
    };
  }, [isAuditLocked, sessionKey, phaseKey, authenticatedFetch, loadCountSheet]);

  // حفظ مسودة العد العمياء فقط؛ لا تحتوي الرصيد المتوقع ولا الفروقات.
  useEffect(() => {
    if (
      isAuditLocked &&
      phase === "COUNTING" &&
      draftKey &&
      rows.length > 0
    ) {
      const timeoutId = setTimeout(() => {
        localStorage.setItem(draftKey, JSON.stringify(rows));
      }, 800);

      return () => clearTimeout(timeoutId);
    }
  }, [rows, isAuditLocked, phase, draftKey]);

  // بدء جرد شامل للمستودع المحدد فقط وأخذ Snapshot على السيرفر.
  const startStocktake = async () => {
    setLocking(true);

    try {
      const data = await authenticatedFetch(
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

      const sid = String(data.session_id);
      localStorage.setItem(sessionKey, sid);
      localStorage.setItem(phaseKey, "COUNTING");
      setSessionId(sid);
      await loadCountSheet(sid);
      onLockChange(true);
      toast.success("تم قفل المستودع وبدء عد أعمى. الرصيد المتوقع مخفي حتى تثبيت العد.");
      setShowLockModal(false);
    } catch (e: any) {
      toast.error(e?.message || "فشل بدء جلسة الجرد.");
    } finally {
      setLocking(false);
    }
  };

  // تحديث كمية فعلية داخل المسودة؛ أول تفاعل صريح مع الحقل يثبت أن السطر تم عده.
  const updateRow = useCallback((
    key: string,
    field: "actual_cartons" | "actual_loose_packs",
    val: number
  ) => {
    setRows((prev) => prev.map((row) => {
      if (row.row_key !== key) return row;

      const updated = {
        ...row,
        [field]: val,
        counted: true,
      };

      const ppc = updated.packs_per_carton || 1;

      if (updated.actual_loose_packs >= ppc) {
        updated.actual_cartons += Math.floor(updated.actual_loose_packs / ppc);
        updated.actual_loose_packs %= ppc;
      } else if (updated.actual_loose_packs < 0) {
        if (updated.actual_cartons > 0) {
          updated.actual_cartons -= 1;
          updated.actual_loose_packs = ppc - 1;
        } else {
          updated.actual_loose_packs = 0;
        }
      }

      return updated;
    }));
  }, []);

  // تأكيد أن الصنف/الدفعة عُد فعلياً وكانت النتيجة صفر، بدلاً من اعتبار عدم الإدخال صفراً.
  const confirmZeroCount = useCallback((key: string) => {
    setRows((prev) => prev.map((row) => (
      row.row_key === key
        ? { ...row, actual_cartons: 0, actual_loose_packs: 0, counted: true }
        : row
    )));
  }, []);

  const countProgress = useMemo(() => {
    const counted = rows.filter((row) => row.counted).length;
    return {
      total: rows.length,
      counted,
      remaining: rows.length - counted,
    };
  }, [rows]);

  // تثبيت محاولة العد الحالية؛ بعدها لا يسمح بتعديل أرقامها ويكشف السيرفر المتوقع للمراجعة فقط.
  const handleSubmit = async () => {
    if (!sessionId) {
      toast.error("خطأ حرج: جلسة الجرد غير موجودة.");
      return;
    }

    const uncounted = rows.filter((row) => !row.counted);
    if (uncounted.length > 0) {
      toast.error(`لا يمكن إنهاء الجرد: بقي ${uncounted.length} سطر لم يتم عده فعلياً.`);
      return;
    }

    const items = rows.map((row) => ({
      product_variant_id: row.product_variant_id,
      batch_id: row.batch_id,
      actual_quantity: toTotalPacks(
        row.actual_cartons,
        row.actual_loose_packs,
        row.packs_per_carton
      ),
    }));

    setSubmitting(true);

    try {
      await authenticatedFetch(
        `/warehouse/unified/stocktake/${sessionId}/count`,
        {
          method: "POST",
          body: JSON.stringify({ items, notes }),
        }
      );

      if (draftKey) localStorage.removeItem(draftKey);
      setShowSubmitModal(false);
      setNotes("");
      await loadReview(sessionId);
      toast.success("تم تثبيت محاولة العد. الأرقام أصبحت غير قابلة للتعديل وظهرت المقارنة للمراجعة.");
    } catch (e: any) {
      toast.error(e?.message || "فشل تثبيت محاولة الجرد.");
    } finally {
      setSubmitting(false);
    }
  };

  const reviewTotals = useMemo(() => {
    if (!review) {
      return { total: 0, matched: 0, shortage: 0, overage: 0, varianceItems: 0 };
    }

    return review.lines.reduce((acc, line) => {
      acc.total += 1;
      if (line.variance_quantity === 0) acc.matched += 1;
      if (line.variance_quantity < 0) acc.shortage += Math.abs(line.variance_quantity);
      if (line.variance_quantity > 0) acc.overage += line.variance_quantity;
      if (line.variance_quantity !== 0) acc.varianceItems += 1;
      return acc;
    }, { total: 0, matched: 0, shortage: 0, overage: 0, varianceItems: 0 });
  }, [review]);

  // اعتماد آخر محاولة مثبتة بعد إعادة تحقق كلمة مرور المشرف الحالي.
  const handleApprove = async () => {
    if (!sessionId) return;
    if (!approvePassword) {
      toast.error("أدخل كلمة مرور المشرف للاعتماد النهائي.");
      return;
    }

    setActionBusy(true);

    try {
      const data = await authenticatedFetch(
        `/warehouse/unified/stocktake/${sessionId}/approve`,
        {
          method: "POST",
          body: JSON.stringify({
            password: approvePassword,
            notes: approveNotes || null,
          }),
        }
      );

      if (draftKey) localStorage.removeItem(draftKey);
      localStorage.removeItem(sessionKey);
      localStorage.removeItem(phaseKey);
      setApprovePassword("");
      setApproveNotes("");
      setReview(null);
      setRows([]);
      setSessionId(null);
      setShowApproveModal(false);
      onLockChange(false);
      toast.success(data?.message || "تم اعتماد الجرد وترحيل الفروقات بنجاح.");
    } catch (e: any) {
      toast.error(e?.message || "فشل اعتماد الجرد.");
    } finally {
      setActionBusy(false);
    }
  };

  // تفويض محاولة Recount جديدة بسبب موثق؛ المحاولة السابقة تبقى محفوظة بالكامل.
  const handleRecount = async () => {
    if (!sessionId) return;

    if (recountReason.trim().length < 5) {
      toast.error("اكتب سبباً واضحاً لإعادة الجرد.");
      return;
    }

    if (!authorizerUsername.trim() || !authorizerPassword) {
      toast.error("أدخل بيانات المستخدم المخول لتفويض إعادة الجرد.");
      return;
    }

    setActionBusy(true);

    try {
      const data = await authenticatedFetch(
        `/warehouse/unified/stocktake/${sessionId}/recount`,
        {
          method: "POST",
          body: JSON.stringify({
            reason: recountReason.trim(),
            authorizer_username: authorizerUsername.trim(),
            authorizer_password: authorizerPassword,
          }),
        }
      );

      if (draftKey) localStorage.removeItem(draftKey);
      setRecountReason("");
      setAuthorizerUsername("");
      setAuthorizerPassword("");
      setReview(null);
      setShowRecountModal(false);

      if (data?.requires_independent_counter) {
        setRows([]);
        setPhase("WAITING_INDEPENDENT");
        localStorage.setItem(phaseKey, "WAITING_INDEPENDENT");
        toast.success("تم تفويض إعادة عد مستقلة. يجب أن ينفذ المحاولة التالية مستخدم مخول آخر.");
      } else {
        await loadCountSheet(sessionId);
        toast.success("تم تفويض Recount جديد. المحاولة السابقة محفوظة بالكامل.");
      }
    } catch (e: any) {
      toast.error(e?.message || "فشل تفويض إعادة الجرد.");
    } finally {
      setActionBusy(false);
    }
  };

  // إلغاء جلسة الجرد بسبب موثق وبعد إعادة تحقق المشرف؛ تاريخ المحاولات لا يُحذف.
  const handleCancel = async () => {
    if (!sessionId) return;

    if (cancelReason.trim().length < 5) {
      toast.error("اكتب سبباً واضحاً لإلغاء الجرد.");
      return;
    }

    if (!cancelPassword) {
      toast.error("أدخل كلمة مرور المشرف لتأكيد الإلغاء.");
      return;
    }

    setActionBusy(true);

    try {
      const data = await authenticatedFetch(
        `/warehouse/unified/stocktake/${sessionId}/cancel`,
        {
          method: "POST",
          body: JSON.stringify({
            password: cancelPassword,
            reason: cancelReason.trim(),
          }),
        }
      );

      if (draftKey) localStorage.removeItem(draftKey);
      localStorage.removeItem(sessionKey);
      localStorage.removeItem(phaseKey);
      setCancelReason("");
      setCancelPassword("");
      setReview(null);
      setRows([]);
      setSessionId(null);
      setShowCancelModal(false);
      onLockChange(false);
      toast.success(data?.message || "تم إلغاء جلسة الجرد وفك الأقفال.");
    } catch (e: any) {
      toast.error(e?.message || "فشل إلغاء جلسة الجرد.");
    } finally {
      setActionBusy(false);
    }
  };

  const approvalBlocked = Boolean(
    review?.latest_attempt.requires_independent_recount &&
    !review?.independent_recount_satisfied
  );

  return (
    <div className="flex flex-col gap-4 h-full flex-1 min-h-0 pt-1">
      {!isAuditLocked && (
        <div className="flex-1 flex flex-col items-center justify-center bg-slate-50/50 rounded-3xl border border-slate-200/50 overflow-hidden relative">
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-64 h-64 bg-amber-400/10 blur-[80px] rounded-full pointer-events-none" />

          <div className="text-center mb-10 z-10">
            <h2 className="text-3xl font-black text-slate-800 tracking-tight">نظام تسوية المخزون</h2>
            <p className="text-slate-500 font-bold mt-2">الجرد الشامل يبدأ بعد قفل المستودع المحدد وأخذ Snapshot ثابت</p>
          </div>

          <div
            className="relative w-80 h-48 rounded-xl overflow-hidden shadow-[0_0_30px_rgba(245,158,11,0.2)] group cursor-pointer p-[3px] bg-slate-800"
            dir="ltr"
            onClick={() => setShowLockModal(true)}
          >
            <div
              className="absolute inset-[-150%] opacity-80 animate-spin pointer-events-none"
              style={{
                backgroundImage: "conic-gradient(from 0deg, transparent 75%, rgba(245,158,11,0.8) 100%)",
                animationDuration: "3s",
              }}
            />
            <div
              className="absolute inset-[-150%] opacity-80 animate-spin pointer-events-none"
              style={{
                backgroundImage: "conic-gradient(from 180deg, transparent 75%, rgba(245,158,11,0.8) 100%)",
                animationDuration: "3s",
              }}
            />

            <div className="relative w-full h-full bg-slate-900 rounded-[9px] overflow-hidden">
              <div className="absolute inset-0 flex items-center justify-center bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-amber-900/40 via-slate-900 to-slate-900">
                <div className="flex flex-col items-center gap-3 scale-90 opacity-0 group-hover:scale-100 group-hover:opacity-100 transition-all duration-500 delay-100">
                  <div className="w-16 h-16 rounded-full bg-amber-500/20 flex items-center justify-center border border-amber-500/30 animate-pulse">
                    <Lock className="w-8 h-8 text-amber-500" />
                  </div>
                  <span className="text-white font-black text-lg tracking-wide drop-shadow-md">إغلاق المستودع وبدء الجرد</span>
                </div>
              </div>

              <div className="absolute top-0 left-0 w-1/2 h-full bg-slate-200 border-r-2 border-slate-300 origin-left transition-transform duration-700 ease-out group-hover:-translate-x-full z-10">
                <div className="absolute top-4 left-3 w-1.5 h-1.5 rounded-full bg-slate-400 shadow-sm" />
                <div className="absolute bottom-4 left-3 w-1.5 h-1.5 rounded-full bg-slate-400 shadow-sm" />
                <div className="absolute left-0 w-full h-px bg-slate-300 top-1/3" />
                <div className="absolute left-0 w-full h-px bg-slate-300 top-2/3" />
                <div className="absolute top-1/2 -translate-y-1/2 right-3 w-2 h-14 bg-slate-400 rounded-full shadow-inner border border-slate-300" />
              </div>

              <div className="absolute top-0 right-0 w-1/2 h-full bg-slate-200 border-l-2 border-slate-300 origin-right transition-transform duration-700 ease-out group-hover:translate-x-full z-10">
                <div className="absolute top-4 right-3 w-1.5 h-1.5 rounded-full bg-slate-400 shadow-sm" />
                <div className="absolute bottom-4 right-3 w-1.5 h-1.5 rounded-full bg-slate-400 shadow-sm" />
                <div className="absolute left-0 w-full h-px bg-slate-300 top-1/3" />
                <div className="absolute left-0 w-full h-px bg-slate-300 top-2/3" />
                <div className="absolute top-1/2 -translate-y-1/2 left-3 w-2 h-14 bg-slate-400 rounded-full shadow-inner border border-slate-300" />
              </div>
            </div>
          </div>

          <p className="mt-8 text-xs text-slate-400 font-bold flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5" /> العد الأول أعمى، ولا يظهر الرصيد المتوقع إلا بعد تثبيت المحاولة
          </p>
        </div>
      )}

      {isAuditLocked && phase === "WAITING_INDEPENDENT" && (
        <div className="glass-card flex-1 flex items-center justify-center border border-slate-200 shadow-sm p-8">
          <div className="max-w-xl text-center space-y-4">
            <div className="mx-auto w-16 h-16 rounded-2xl bg-red-50 border border-red-100 flex items-center justify-center">
              <ShieldCheck className="w-8 h-8 text-red-500" />
            </div>
            <h3 className="text-xl font-black text-slate-800">إعادة عد مستقلة مطلوبة</h3>
            <p className="text-sm text-slate-600 leading-7 font-bold">
              تم تثبيت العجز وتفويض Recount جديد. منفذ المحاولة السابقة ممنوع رقابياً من تنفيذ المحاولة التالية.
              سجّل الدخول بحساب مستخدم مخول آخر، وستظهر له ورقة عد عمياء جديدة تلقائياً.
            </p>
            <button
              onClick={() => setShowCancelModal(true)}
              className="px-5 h-10 bg-slate-100 hover:bg-red-50 text-slate-600 hover:text-red-600 font-bold rounded-xl transition-colors"
            >
              إلغاء جلسة الجرد
            </button>
          </div>
        </div>
      )}

      {isAuditLocked && phase === "COUNTING" && (
        <div className="glass-card flex flex-col border border-slate-200 shadow-sm flex-1 min-h-0 pt-0 overflow-hidden">
          <div className="px-5 py-3 bg-slate-900 text-white flex items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <Scan className="w-4 h-4 text-amber-400" />
              <span className="text-sm font-black">عد أعمى نشط</span>
            </div>
            <span className="text-xs text-slate-300 font-bold">
              المتوقع والفروقات مخفية حتى تثبيت المحاولة
            </span>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto overflow-x-auto custom-scrollbar">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-100 text-right sticky top-0 z-10 shadow-sm">
                <tr>
                  <th className="px-4 py-3.5 text-xs font-bold text-slate-500">المنتج</th>
                  <th className="px-4 py-3.5 text-xs font-bold text-slate-500">الدفعة / الصلاحية</th>
                  <th className="px-4 py-3.5 text-xs font-bold text-[#1e87bb] text-center">الجرد الفعلي (كرتونة / حبة)</th>
                  <th className="px-4 py-3.5 text-xs font-bold text-slate-500 text-center">حالة العد</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50 bg-white">
                {rows.map((row) => (
                  <tr key={row.row_key} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3 font-bold text-slate-800">{row.product_name}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-col gap-0.5">
                        <span className="text-xs font-bold text-slate-700">
                          {row.batch_number || "بدون دفعة"}
                        </span>
                        <span className="text-[11px] text-slate-400">
                          {row.expiry_date || "-"}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-center gap-4">
                        <div className="flex items-center gap-1.5">
                          <QuantityInput
                            value={row.actual_cartons}
                            onChange={(value) => updateRow(row.row_key, "actual_cartons", value)}
                            min={0}
                          />
                          <span className="text-xs font-bold text-slate-500">ك</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <QuantityInput
                            value={row.actual_loose_packs}
                            onChange={(value) => updateRow(row.row_key, "actual_loose_packs", value)}
                            min={-1}
                          />
                          <span className="text-xs font-bold text-slate-500">ح</span>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-center">
                      {row.counted ? (
                        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-emerald-50 text-emerald-700 border border-emerald-100 rounded-lg text-xs font-black">
                          <Check className="w-3.5 h-3.5" /> تم العد
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => confirmZeroCount(row.row_key)}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 hover:bg-amber-50 text-slate-500 hover:text-amber-700 border border-slate-200 hover:border-amber-200 rounded-lg text-xs font-black transition-colors"
                          title="استخدم هذا الزر فقط إذا تم العد فعلياً وكانت الكمية صفر"
                        >
                          تأكيد صفر
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="bg-slate-900 text-white rounded-b-2xl overflow-hidden border-t border-slate-700">
            <div className="px-5 py-4 flex flex-wrap items-center justify-between gap-6">
              <div className="flex items-center gap-6">
                <div className="flex flex-col">
                  <span className="text-[10px] text-slate-400 font-bold uppercase">الإجمالي</span>
                  <span className="text-sm font-extrabold">{countProgress.total} سطر</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-[10px] text-slate-400 font-bold uppercase">تم عده</span>
                  <span className="text-sm font-extrabold text-emerald-400">{countProgress.counted}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-[10px] text-slate-400 font-bold uppercase">متبقي</span>
                  <span className={`text-sm font-extrabold ${countProgress.remaining > 0 ? "text-amber-400" : "text-emerald-400"}`}>
                    {countProgress.remaining}
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-2 min-w-[300px]">
                <button
                  onClick={() => setShowCancelModal(true)}
                  className="flex-1 px-4 h-9 bg-slate-800 hover:bg-red-500/20 text-slate-400 hover:text-red-400 border border-transparent hover:border-red-500/30 text-xs font-bold rounded-xl transition-all"
                >
                  إلغاء الجرد
                </button>
                <button
                  onClick={() => setShowSubmitModal(true)}
                  className="flex-[2.5] px-4 h-9 bg-amber-500 hover:bg-amber-600 text-slate-900 text-sm font-black rounded-xl shadow-lg transition-all flex items-center justify-center gap-2"
                >
                  <Check className="w-5 h-5" /> إنهاء العد وتثبيت المحاولة
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {isAuditLocked && phase === "REVIEW" && review && (
        <div className="glass-card flex flex-col border border-slate-200 shadow-sm flex-1 min-h-0 pt-0 overflow-hidden">
          <div className="px-5 py-3 bg-slate-900 text-white flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              <span className="text-sm font-black">
                مراجعة محاولة #{review.latest_attempt.attempt_number}
              </span>
              <span className="text-xs text-slate-400">
                بواسطة {review.latest_attempt.counted_by_name}
              </span>
            </div>
            <div className="text-xs text-slate-300 font-bold">
              {review.attempt_history.length} محاولة محفوظة تاريخياً
            </div>
          </div>

          {approvalBlocked && (
            <div className="mx-4 mt-4 p-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-xs font-bold flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              هذا العجز مصنف مادياً، ولذلك الاعتماد النهائي محظور حتى ينفذ مستخدم مخول آخر Recount مستقلاً.
            </div>
          )}

          <div className="flex-1 min-h-0 overflow-y-auto overflow-x-auto custom-scrollbar">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-100 text-right sticky top-0 z-10 shadow-sm">
                <tr>
                  <th className="px-4 py-3.5 text-xs font-bold text-slate-500">المنتج</th>
                  <th className="px-4 py-3.5 text-xs font-bold text-slate-500">الدفعة</th>
                  <th className="px-4 py-3.5 text-xs font-bold text-slate-500 text-center">المتوقع</th>
                  <th className="px-4 py-3.5 text-xs font-bold text-[#1e87bb] text-center">الفعلي المثبت</th>
                  <th className="px-4 py-3.5 text-xs font-bold text-slate-500 text-center">الفرق</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50 bg-white">
                {review.lines.map((line) => (
                  <tr key={line.attempt_line_id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3 font-bold text-slate-800">{line.product_name}</td>
                    <td className="px-4 py-3 text-xs text-slate-500 font-bold">{line.batch_number || "بدون دفعة"}</td>
                    <td className="px-4 py-3 text-center font-black text-slate-700">
                      {formatQty(line.expected_quantity, line.packs_per_carton)}
                    </td>
                    <td className="px-4 py-3 text-center font-black text-blue-700">
                      {formatQty(line.actual_quantity, line.packs_per_carton)}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {line.variance_quantity === 0 ? (
                        <span className="text-slate-400 font-bold">مطابق</span>
                      ) : (
                        <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-black ${line.variance_quantity > 0 ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}`} dir="ltr">
                          {line.variance_quantity > 0 ? "+ " : "- "}
                          {formatQty(Math.abs(line.variance_quantity), line.packs_per_carton)}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="bg-slate-900 text-white rounded-b-2xl overflow-hidden border-t border-slate-700">
            <div className="px-5 py-4 flex flex-wrap items-center justify-between gap-5">
              <div className="flex items-center gap-5">
                <div className="flex flex-col">
                  <span className="text-[10px] text-slate-400 font-bold">مطابق</span>
                  <span className="text-sm font-extrabold text-emerald-400">{reviewTotals.matched}/{reviewTotals.total}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-[10px] text-slate-400 font-bold">أسطر بفروقات</span>
                  <span className={`text-sm font-extrabold ${reviewTotals.varianceItems ? "text-red-400" : "text-slate-300"}`}>
                    {reviewTotals.varianceItems}
                  </span>
                </div>
                {reviewTotals.varianceItems > 0 && (
                  <button
                    onClick={() => setShowVarianceModal(true)}
                    className="text-xs font-bold bg-red-500/20 text-red-400 hover:bg-red-500/30 px-4 py-2 rounded-xl border border-red-500/30 flex items-center gap-2"
                  >
                    <AlertTriangle className="w-4 h-4" /> تفاصيل الفروقات
                  </button>
                )}
              </div>

              <div className="flex items-center gap-2 min-w-[430px]">
                <button
                  onClick={() => setShowCancelModal(true)}
                  className="flex-1 px-4 h-9 bg-slate-800 hover:bg-red-500/20 text-slate-400 hover:text-red-400 text-xs font-bold rounded-xl transition-all"
                >
                  إلغاء
                </button>
                <button
                  onClick={() => setShowRecountModal(true)}
                  className="flex-1 px-4 h-9 bg-blue-500/15 hover:bg-blue-500/25 text-blue-300 border border-blue-500/20 text-xs font-black rounded-xl transition-all flex items-center justify-center gap-1.5"
                >
                  <RotateCcw className="w-4 h-4" /> Recount جديد
                </button>
                <button
                  onClick={() => setShowApproveModal(true)}
                  disabled={approvalBlocked}
                  className="flex-[1.5] px-4 h-9 bg-emerald-500 hover:bg-emerald-600 disabled:bg-slate-700 disabled:text-slate-400 disabled:cursor-not-allowed text-white text-sm font-black rounded-xl transition-all flex items-center justify-center gap-2"
                >
                  <ShieldCheck className="w-4 h-4" /> اعتماد نهائي
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <Modal
        isOpen={showLockModal}
        onClose={() => setShowLockModal(false)}
        title="إجراء أمني: بدء جرد شامل"
        maxWidth="max-w-md"
        footer={
          <div className="flex gap-3 w-full">
            <button onClick={() => setShowLockModal(false)} className="flex-1 px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-bold hover:bg-slate-50">إلغاء</button>
            <button onClick={startStocktake} disabled={locking} className="flex-1 px-5 py-2 bg-amber-500 hover:bg-amber-600 text-white font-bold rounded-xl shadow-md">
              {locking ? "جارٍ البدء..." : "ابدأ الجرد الأعمى"}
            </button>
          </div>
        }
      >
        <div className="flex flex-col gap-4">
          <div className="bg-amber-50 border-r-4 border-amber-500 p-4 rounded-l-lg">
            <p className="text-sm text-amber-800 font-bold">
              سيُقفل هذا المستودع فقط، وتؤخذ Snapshot ثابتة. العدّاد لن يرى الرصيد المتوقع أو الفرق أثناء العد.
            </p>
          </div>
        </div>
      </Modal>

      <Modal
        isOpen={showSubmitModal}
        onClose={() => setShowSubmitModal(false)}
        title="تثبيت محاولة العد"
        maxWidth="max-w-md"
        footer={
          <div className="flex gap-3 w-full">
            <button onClick={() => setShowSubmitModal(false)} className="flex-1 px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-bold hover:bg-slate-50">تراجع</button>
            <button onClick={handleSubmit} disabled={submitting} className="flex-[1.5] px-5 py-2 bg-amber-500 hover:bg-amber-600 text-slate-900 font-black rounded-xl shadow-md">
              {submitting ? "جاري التثبيت..." : "تثبيت وإنهاء العد"}
            </button>
          </div>
        }
      >
        <div className="flex flex-col gap-4">
          <div className="bg-red-50 border-r-4 border-red-500 p-4 rounded-l-lg">
            <p className="text-sm text-red-800 font-bold">
              بعد التثبيت لن تستطيع تعديل هذه الأرقام. أي تصحيح لاحق سيكون Recount جديداً محفوظاً كنسخة مستقلة.
            </p>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-bold text-slate-700">ملاحظات العد (اختياري)</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="أي ملاحظات عن العد الفعلي..."
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-800 focus:ring-2 focus:ring-amber-500 outline-none resize-none h-24"
            />
          </div>
        </div>
      </Modal>

      <Modal
        isOpen={showApproveModal}
        onClose={() => setShowApproveModal(false)}
        title="اعتماد الجرد نهائياً"
        maxWidth="max-w-md"
        footer={
          <div className="flex gap-3 w-full">
            <button onClick={() => setShowApproveModal(false)} className="flex-1 px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-bold hover:bg-slate-50">تراجع</button>
            <button onClick={handleApprove} disabled={actionBusy || approvalBlocked} className="flex-[1.5] px-5 py-2 bg-emerald-500 hover:bg-emerald-600 disabled:bg-slate-300 text-white font-black rounded-xl shadow-md">
              {actionBusy ? "جاري الاعتماد..." : "اعتماد وترحيل الفروقات"}
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <p className="text-sm text-slate-600 font-bold">
            سيتم ترحيل فروقات محاولة العد الحالية إلى الرصيد الفعلي وفك أقفال المستودع.
          </p>
          <div className="space-y-2">
            <label className="text-sm font-bold text-slate-700">كلمة مرور المشرف الحالي</label>
            <input
              type="password"
              autoComplete="current-password"
              value={approvePassword}
              onChange={(e) => setApprovePassword(e.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-bold text-slate-700">ملاحظة الاعتماد (اختياري)</label>
            <textarea
              value={approveNotes}
              onChange={(e) => setApproveNotes(e.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none resize-none h-20"
            />
          </div>
        </div>
      </Modal>

      <Modal
        isOpen={showRecountModal}
        onClose={() => setShowRecountModal(false)}
        title="تفويض Recount جديد"
        maxWidth="max-w-md"
        footer={
          <div className="flex gap-3 w-full">
            <button onClick={() => setShowRecountModal(false)} className="flex-1 px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-bold hover:bg-slate-50">تراجع</button>
            <button onClick={handleRecount} disabled={actionBusy} className="flex-[1.5] px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white font-black rounded-xl shadow-md">
              {actionBusy ? "جاري التفويض..." : "تفويض إعادة العد"}
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <div className="bg-blue-50 border-r-4 border-blue-500 p-4 rounded-l-lg">
            <p className="text-sm text-blue-800 font-bold">
              المحاولة الحالية لن تُعدل أو تُحذف. سيُنشئ النظام محاولة عد جديدة مستقلة بسبب موثق.
            </p>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-bold text-slate-700">سبب إعادة الجرد *</label>
            <textarea
              value={recountReason}
              onChange={(e) => setRecountReason(e.target.value)}
              placeholder="مثال: فرق غير مبرر ويحتاج عد مستقل..."
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none resize-none h-20"
            />
          </div>
          <div className="grid grid-cols-1 gap-3">
            <div className="space-y-2">
              <label className="text-sm font-bold text-slate-700">اسم المستخدم المخول *</label>
              <input
                type="text"
                autoComplete="username"
                value={authorizerUsername}
                onChange={(e) => setAuthorizerUsername(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-bold text-slate-700">كلمة مرور المستخدم المخول *</label>
              <input
                type="password"
                autoComplete="new-password"
                value={authorizerPassword}
                onChange={(e) => setAuthorizerPassword(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
        </div>
      </Modal>

      <Modal
        isOpen={showCancelModal}
        onClose={() => setShowCancelModal(false)}
        title="إلغاء جلسة الجرد"
        maxWidth="max-w-md"
        footer={
          <div className="flex gap-3 w-full">
            <button onClick={() => setShowCancelModal(false)} className="flex-1 px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-bold hover:bg-slate-50">تراجع</button>
            <button onClick={handleCancel} disabled={actionBusy} className="flex-[1.5] px-5 py-2 bg-red-500 hover:bg-red-600 text-white font-black rounded-xl shadow-md">
              {actionBusy ? "جاري الإلغاء..." : "تأكيد الإلغاء"}
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <div className="bg-red-50 border-r-4 border-red-500 p-4 rounded-l-lg">
            <p className="text-sm text-red-800 font-bold">
              إلغاء الجلسة يفك الأقفال، لكنه لا يمسح أي محاولة عد مثبتة أو سجل رقابي سابق.
            </p>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-bold text-slate-700">سبب الإلغاء *</label>
            <textarea
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none resize-none h-20"
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-bold text-slate-700">كلمة مرور المشرف الحالي *</label>
            <input
              type="password"
              autoComplete="current-password"
              value={cancelPassword}
              onChange={(e) => setCancelPassword(e.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-red-500"
            />
          </div>
        </div>
      </Modal>

      <Modal
        isOpen={showVarianceModal}
        onClose={() => setShowVarianceModal(false)}
        title="تفاصيل الفروقات المثبتة"
        maxWidth="max-w-lg"
        footer={
          <button onClick={() => setShowVarianceModal(false)} className="w-full px-4 py-2 bg-slate-100 text-slate-700 font-bold rounded-xl hover:bg-slate-200 transition-colors">إغلاق</button>
        }
      >
        <div className="max-h-[60vh] overflow-y-auto custom-scrollbar pr-2 space-y-2">
          {review?.lines.filter((line) => line.variance_quantity !== 0).map((line) => (
            <div key={line.attempt_line_id} className="flex items-center justify-between p-3 bg-slate-50 border border-slate-100 rounded-xl">
              <div className="flex flex-col">
                <span className="font-bold text-slate-800 text-sm">{line.product_name}</span>
                <span className="text-[11px] text-slate-400">{line.batch_number || "بدون دفعة"}</span>
              </div>
              <span className={`font-black text-sm px-3 py-1 rounded-lg ${line.variance_quantity > 0 ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}`} dir="ltr">
                {line.variance_quantity > 0 ? "+ " : "- "}
                {formatQty(Math.abs(line.variance_quantity), line.packs_per_carton)}
              </span>
            </div>
          ))}
        </div>
      </Modal>
    </div>
  );
}
