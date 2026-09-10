import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { Modal } from "@/components/ui/modal";
import {
  Radar,
  CheckCircle,
  XCircle,
  Clock,
  Package,
  RefreshCcw,
  Ban,
  Loader2,
  ShieldAlert,
  type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";
import { PendingRoute, RouteTransfer } from "@/types/dispatch";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorMessage, apiErrorStatus } from "@/lib/apiErrors";

// DASHBOARD_DISPATCH_ROUTE_CONTRACT_V3
type TransferStatus = RouteTransfer["status"];

const STATUS_MAP: Record<
  TransferStatus,
  { bg: string; text: string; label: string; icon: LucideIcon }
> = {
  pending: {
    bg: "bg-amber-100",
    text: "text-amber-700",
    label: "بانتظار المندوب",
    icon: Clock,
  },
  accepted: {
    bg: "bg-emerald-100",
    text: "text-emerald-700",
    label: "تم الاستلام",
    icon: CheckCircle,
  },
  rejected: {
    bg: "bg-red-100",
    text: "text-red-700",
    label: "رفض الاستلام",
    icon: XCircle,
  },
  cancelled: {
    bg: "bg-slate-100",
    text: "text-slate-600",
    label: "ملغاة",
    icon: Ban,
  },
};

interface TransfersRadarModalProps {
  isOpen: boolean;
  onClose: () => void;
  route: PendingRoute | null;
}

const parseTransferTime = (
  value: string | null
): { timestamp: number; formatted: string } => {
  if (!value) {
    return { timestamp: 0, formatted: "وقت غير متاح" };
  }

  const normalized =
    value.endsWith("Z") || value.includes("+") ? value : `${value}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) {
    return { timestamp: 0, formatted: "وقت غير متاح" };
  }

  return {
    timestamp: date.getTime(),
    formatted: date.toLocaleString("ar-EG", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }),
  };
};

const formatSigned = (value: number): string =>
  value > 0 ? `+${value}` : String(value);

const TRANSFER_STATUSES = new Set<TransferStatus>([
  "pending",
  "accepted",
  "rejected",
  "cancelled",
]);

const parseRouteTransfers = (raw: unknown): RouteTransfer[] => {
  if (!Array.isArray(raw)) {
    throw new Error("استجابة رادار المصافحات غير صالحة.");
  }

  return raw.map((item) => {
    if (!item || typeof item !== "object") {
      throw new Error("استجابة رادار المصافحات غير صالحة.");
    }
    const value = item as Record<string, unknown>;
    if (
      !Number.isSafeInteger(value.transfer_id) ||
      Number(value.transfer_id) <= 0 ||
      typeof value.product_name !== "string" ||
      !Number.isInteger(value.delta_cartons) ||
      !Number.isInteger(value.delta_packs) ||
      typeof value.status !== "string" ||
      !TRANSFER_STATUSES.has(value.status as TransferStatus) ||
      (value.created_at !== null && typeof value.created_at !== "string") ||
      typeof value.batch_id !== "string" ||
      typeof value.can_force_cancel !== "boolean"
    ) {
      throw new Error("استجابة رادار المصافحات غير صالحة.");
    }
    return value as unknown as RouteTransfer;
  });
};

const parseForceCancelResponse = (
  raw: unknown,
  expectedTransferId: number
): string => {
  if (!raw || typeof raw !== "object") {
    throw new Error("استجابة إلغاء الحوالة غير صالحة.");
  }
  const value = raw as Record<string, unknown>;
  if (
    value.transfer_id !== expectedTransferId ||
    value.status !== "CANCELLED" ||
    typeof value.message !== "string" ||
    !value.message
  ) {
    throw new Error("استجابة إلغاء الحوالة غير صالحة.");
  }
  return value.message;
};

export function TransfersRadarModal({
  isOpen,
  onClose,
  route,
}: TransfersRadarModalProps) {
  const authenticatedFetch = useAuthFetch();
  const [transfers, setTransfers] = useState<RouteTransfer[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const requestControllerRef = useRef<AbortController | null>(null);
  const [cancelTarget, setCancelTarget] = useState<RouteTransfer | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  const [cancelRequestId, setCancelRequestId] = useState(() =>
    crypto.randomUUID()
  );
  const [isCancelling, setIsCancelling] = useState(false);

  const fetchTransfers = useCallback(async () => {
    if (!route?.id) return;

    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
    setIsLoading(true);

    try {
      const data = await authenticatedFetch(
        `/dispatch/route/${route.id}/transfers`,
        { signal: controller.signal }
      );
      setTransfers(parseRouteTransfers(data));
    } catch (error: unknown) {
      if (error instanceof Error && error.name === "AbortError") return;
      toast.error(error instanceof Error ? error.message : "فشل تحديث الرادار");
      setTransfers([]);
    } finally {
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
        setIsLoading(false);
      }
    }
  }, [route?.id, authenticatedFetch]);

  const openForceCancel = useCallback((transfer: RouteTransfer) => {
    if (transfer.status !== "pending" || !transfer.can_force_cancel) return;
    setCancelTarget(transfer);
    setCancelReason("");
    setCancelRequestId(crypto.randomUUID());
  }, []);

  const closeForceCancel = useCallback(() => {
    if (isCancelling) return;
    setCancelTarget(null);
    setCancelReason("");
  }, [isCancelling]);

  const updateCancelReason = useCallback((value: string) => {
    setCancelReason(value);
    setCancelRequestId(crypto.randomUUID());
  }, []);

  const submitForceCancel = useCallback(async () => {
    if (!cancelTarget || isCancelling) return;
    const reason = cancelReason.trim();
    if (reason.length < 3) {
      toast.error("سبب الإلغاء يجب أن يتكون من 3 أحرف على الأقل.");
      return;
    }
    if (reason.length > 500) {
      toast.error("سبب الإلغاء لا يجوز أن يتجاوز 500 حرف.");
      return;
    }

    setIsCancelling(true);
    try {
      const raw = await authenticatedFetch(
        `/dispatch/transfers/${cancelTarget.transfer_id}/force_cancel`,
        {
          method: "POST",
          body: JSON.stringify({
            request_id: cancelRequestId,
            reason,
          }),
        }
      );
      const message = parseForceCancelResponse(raw, cancelTarget.transfer_id);
      setTransfers((current) =>
        current.map((transfer) =>
          transfer.transfer_id === cancelTarget.transfer_id
            ? { ...transfer, status: "cancelled", can_force_cancel: false }
            : transfer
        )
      );
      setCancelTarget(null);
      setCancelReason("");
      toast.success(message);
      void fetchTransfers();
    } catch (error: unknown) {
      toast.error(apiErrorMessage(error, "تعذر إلغاء الحوالة المعلقة."));
      const status = apiErrorStatus(error);
      if (status === 403 || status === 404 || status === 409) {
        setCancelTarget(null);
        setCancelReason("");
        void fetchTransfers();
      }
    } finally {
      setIsCancelling(false);
    }
  }, [
    authenticatedFetch,
    cancelReason,
    cancelRequestId,
    cancelTarget,
    fetchTransfers,
    isCancelling,
  ]);

  const closeRadar = useCallback(() => {
    if (isCancelling || cancelTarget) return;
    setCancelTarget(null);
    setCancelReason("");
    onClose();
  }, [cancelTarget, isCancelling, onClose]);

  useEffect(() => {
    if (!isOpen || !route?.id) {
      requestControllerRef.current?.abort();
      requestControllerRef.current = null;
      return;
    }

    setTransfers([]);
    fetchTransfers();

    return () => {
      requestControllerRef.current?.abort();
      requestControllerRef.current = null;
    };
  }, [isOpen, route?.id, fetchTransfers]);

  const groupedTransfers = useMemo(() => {
    const groupedMap = transfers.reduce(
      (acc, transfer) => {
        const baseKey = transfer.batch_id
          ? `BATCH_${transfer.batch_id}`
          : `ID_${transfer.transfer_id}`;
        const key = `${baseKey}_${transfer.status}`;
        const time = parseTransferTime(transfer.created_at);

        if (!acc[key]) {
          acc[key] = {
            batch_id: key,
            rawTimestamp: time.timestamp,
            formattedDate: time.formatted,
            status: transfer.status,
            items: [],
          };
        } else if (time.timestamp > acc[key].rawTimestamp) {
          acc[key].rawTimestamp = time.timestamp;
          acc[key].formattedDate = time.formatted;
        }

        acc[key].items.push(transfer);
        return acc;
      },
      {} as Record<
        string,
        {
          batch_id: string;
          rawTimestamp: number;
          formattedDate: string;
          status: TransferStatus;
          items: RouteTransfer[];
        }
      >
    );

    return Object.values(groupedMap).sort(
      (a, b) => b.rawTimestamp - a.rawTimestamp
    );
  }, [transfers]);

  return (
    <>
    <Modal
      isOpen={isOpen}
      onClose={closeRadar}
      title={`📡 رادار المصافحات: ${route?.driverName || "..."}`}
    >
      <div className="space-y-4">
        <div className="bg-blue-50 border-r-4 border-blue-400 p-3 rounded-lg">
          <p className="text-xs text-blue-800 font-bold leading-relaxed">
            تتبع حالة البضاعة المرسلة للمندوب لحظياً. يتم تجميع الأصناف التي
            أرسلت في دفعة واحدة معاً.
          </p>
        </div>

        {isLoading && transfers.length === 0 ? (
          <div className="flex flex-col items-center py-12 gap-3">
            <RefreshCcw className="w-8 h-8 text-blue-400 animate-spin" />
            <p className="text-sm text-slate-400 font-bold">
              جاري مسح الرادار...
            </p>
          </div>
        ) : transfers.length === 0 ? (
          <div className="text-center py-10 bg-slate-50 rounded-2xl border-2 border-dashed border-slate-200">
            <Radar className="w-10 h-10 text-slate-300 mx-auto mb-2" />
            <p className="text-slate-500 font-bold text-sm">
              لا توجد مصافحات لهذه الجلسة.
            </p>
          </div>
        ) : (
          <div
            className={`max-h-[60vh] overflow-y-auto space-y-4 pr-1 custom-scrollbar transition-opacity duration-300 ${
              isLoading
                ? "opacity-40 pointer-events-none grayscale-[50%]"
                : "opacity-100"
            }`}
          >
            {groupedTransfers.map((batch) => {
              const config = STATUS_MAP[batch.status];
              const StatusIcon = config.icon;

              return (
                <div
                  key={batch.batch_id}
                  className="border border-slate-200 rounded-2xl shadow-sm bg-white overflow-hidden transition-all hover:border-blue-200"
                >
                  <div
                    className={`px-4 py-2.5 flex justify-between items-center border-b border-slate-100 ${config.bg.replace(
                      "100",
                      "50"
                    )}`}
                  >
                    <div className="flex items-center gap-2">
                      <Clock className="w-3.5 h-3.5 text-slate-400" />
                      <span
                        className="text-[11px] font-black text-slate-500"
                        dir="ltr"
                      >
                        {batch.formattedDate}
                      </span>
                    </div>
                    <span
                      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-black ${config.bg} ${config.text}`}
                    >
                      <StatusIcon className="w-3 h-3" />
                      {config.label}
                    </span>
                  </div>

                  <div className="p-3 divide-y divide-slate-50">
                    {batch.items.map((transfer) => {
                      const positive =
                        transfer.delta_cartons > 0 ||
                        (transfer.delta_cartons === 0 &&
                          transfer.delta_packs > 0);
                      return (
                        <div
                          key={transfer.transfer_id}
                          className="flex items-center justify-between py-2.5 first:pt-0 last:pb-0"
                        >
                          <div className="flex items-center gap-3">
                            <div
                              className={`p-2 rounded-xl ${
                                positive
                                  ? "bg-emerald-50 text-emerald-600"
                                  : "bg-red-50 text-red-600"
                              }`}
                            >
                              <Package className="w-4 h-4" />
                            </div>
                            <p className="font-bold text-slate-800 text-sm">
                              {transfer.product_name}
                            </p>
                          </div>
                          <div className="flex items-center gap-2">
                            <div
                              className={`font-black text-sm tabular-nums ${
                                positive ? "text-emerald-600" : "text-red-600"
                              }`}
                              dir="ltr"
                            >
                              <span>
                                {formatSigned(transfer.delta_cartons)} ك
                              </span>
                              {transfer.delta_packs !== 0 && (
                                <span className="ms-2">
                                  {formatSigned(transfer.delta_packs)} ح
                                </span>
                              )}
                            </div>
                            {transfer.status === "pending" &&
                              transfer.can_force_cancel && (
                                <button
                                  type="button"
                                  onClick={() => openForceCancel(transfer)}
                                  className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-2.5 py-1.5 text-[11px] font-black text-red-700 hover:bg-red-100 transition-colors"
                                  title="إلغاء الحوالة المعلقة وتحرير الحجز"
                                >
                                  <Ban className="w-3.5 h-3.5" />
                                  إلغاء
                                </button>
                              )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div className="flex justify-between items-center pt-4 border-t border-slate-100">
          <p className="text-[10px] text-slate-400 font-bold italic">
            ملاحظة: تظهر هنا مصافحات الجلسة الحالية فقط.
          </p>
          <button
            onClick={fetchTransfers}
            disabled={isLoading}
            className="flex items-center gap-2 px-4 py-2 text-blue-600 bg-blue-50 rounded-xl font-black text-xs hover:bg-blue-100 transition-all disabled:opacity-50 shadow-sm"
          >
            <RefreshCcw
              className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`}
            />
            تحديث الرادار
          </button>
        </div>
      </div>
    </Modal>

    <Modal
      isOpen={cancelTarget !== null}
      onClose={closeForceCancel}
      title="إلغاء حوالة معلقة"
      maxWidth="max-w-lg"
      footer={
        <>
          <button
            type="button"
            onClick={closeForceCancel}
            disabled={isCancelling}
            className="px-4 py-2.5 rounded-xl border border-slate-200 bg-white text-sm font-bold text-slate-600 disabled:opacity-50"
          >
            تراجع
          </button>
          <button
            type="button"
            onClick={() => void submitForceCancel()}
            disabled={isCancelling || cancelReason.trim().length < 3}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-red-600 text-white text-sm font-black hover:bg-red-700 disabled:bg-red-300 disabled:cursor-not-allowed"
          >
            {isCancelling ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Ban className="w-4 h-4" />
            )}
            {isCancelling ? "جارٍ الإلغاء..." : "تأكيد الإلغاء"}
          </button>
        </>
      }
    >
      <div className="space-y-4" dir="rtl">
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 flex items-start gap-3">
          <ShieldAlert className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-black text-red-800">
              هذا الإجراء مخصص للحوالة المعلقة فقط.
            </p>
            <p className="text-xs font-bold text-red-700/80 mt-1 leading-relaxed">
              سيحرر الخادم حجز الكمية ويحوّل الحوالة إلى ملغاة دون إنشاء حركة مخزون فيزيائية.
            </p>
          </div>
        </div>

        {cancelTarget && (
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <p className="text-sm font-black text-slate-800">
              {cancelTarget.product_name}
            </p>
            <p className="text-xs font-bold text-slate-500 mt-1" dir="ltr">
              #{cancelTarget.transfer_id} · {formatSigned(cancelTarget.delta_cartons)} ك · {formatSigned(cancelTarget.delta_packs)} ح
            </p>
          </div>
        )}

        <div>
          <label className="block text-xs font-black text-slate-700 mb-2">
            سبب الإلغاء <span className="text-red-600">*</span>
          </label>
          <textarea
            value={cancelReason}
            onChange={(event) => updateCancelReason(event.target.value)}
            disabled={isCancelling}
            rows={4}
            maxLength={500}
            placeholder="اكتب سبباً واضحاً وقابلاً للتدقيق..."
            className="w-full rounded-xl border border-slate-200 bg-white p-3 text-sm font-medium text-slate-800 outline-none focus:border-red-400 focus:ring-2 focus:ring-red-100 disabled:opacity-60"
          />
          <p className="text-[10px] font-bold text-slate-400 mt-1 text-left" dir="ltr">
            {cancelReason.length}/500
          </p>
        </div>
      </div>
    </Modal>
    </>
  );
}
