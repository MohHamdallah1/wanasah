import { useState, useEffect, useCallback, useMemo } from "react";
import { Modal } from "@/components/ui/modal";
import { Radar, CheckCircle, XCircle, Clock, Package, RefreshCcw } from "lucide-react";
import { toast } from "sonner";
import { PendingRoute } from "@/types/dispatch";

const STATUS_MAP: Record<string, { bg: string; text: string; label: string; icon: any }> = {
    pending: { bg: "bg-amber-100", text: "text-amber-700", label: "بانتظار المندوب", icon: Clock },
    accepted: { bg: "bg-emerald-100", text: "text-emerald-700", label: "تم الاستلام", icon: CheckCircle },
    rejected: { bg: "bg-red-100", text: "text-red-700", label: "رفض الاستلام", icon: XCircle },
};

interface TransferRecord {
    transfer_id: number;
    product_name: string;
    delta_cartons: number;
    status: 'pending' | 'accepted' | 'rejected';
    created_at: string;
    batch_id: string | null;
}

interface TransfersRadarModalProps {
    isOpen: boolean;
    onClose: () => void;
    route: PendingRoute | null;
    authenticatedFetch: (path: string, opts?: RequestInit) => Promise<any>;
}

export function TransfersRadarModal({ isOpen, onClose, route, authenticatedFetch }: TransfersRadarModalProps) {
    const [transfers, setTransfers] = useState<TransferRecord[]>([]);
    const [isLoading, setIsLoading] = useState(false);

    const fetchTransfers = useCallback(async () => {
        if (!route?.id) return;
        setIsLoading(true);
        try {
            // استلام البيانات مباشرة من הـ Hook המصفح
            const data = await authenticatedFetch(`/dispatch/route/${route.id}/transfers`);
            setTransfers(Array.isArray(data) ? data : []);
        } catch (e: any) {
            toast.error(e.message || "فشل تحديث الرادار");
            setTransfers([]);
        } finally {
            setIsLoading(false);
        }
    }, [route?.id, authenticatedFetch]);

    useEffect(() => {
        if (isOpen && route?.id) {
            setTransfers([]);
            fetchTransfers();
        }
    }, [isOpen, route?.id, fetchTransfers]);

    // +++ خوارزمية التجميع الذكية والمصفحة ضد أخطاء TypeScript +++
    const groupedTransfers = useMemo(() => {
        // 1. تعريف النوع الصارم للماب لمنع خطأ unknown
        const groupedMap = transfers.reduce((acc, t) => {
            const baseKey = t.batch_id ? `BATCH_${t.batch_id}` : `ID_${t.transfer_id}`;
            const key = `${baseKey}_${t.status}`;

            if (!acc[key]) {
                const rawDate = new Date(t.created_at + "Z");
                acc[key] = {
                    batch_id: key,
                    rawTimestamp: rawDate.getTime(),
                    formattedDate: rawDate.toLocaleString("ar-EG", {
                        hour: '2-digit', minute: '2-digit', second: '2-digit'
                    }),
                    status: t.status,
                    items: [] as TransferRecord[]
                };
            }
            acc[key].items.push(t);
            return acc;
        }, {} as Record<string, { batch_id: string, rawTimestamp: number, formattedDate: string, status: string, items: TransferRecord[] }>);

        // 2. الترتيب الرياضي الصارم (الأحدث فوق)
        return Object.values(groupedMap).sort((a, b) => b.rawTimestamp - a.rawTimestamp);
    }, [transfers]);

    // +++ إعادة الـ Return الأساسي الذي تم حذفه بالخطأ +++
    return (
        <Modal isOpen={isOpen} onClose={onClose} title={`📡 رادار المصافحات: ${route?.driverName || '...'}`}>
            <div className="space-y-4">
                <div className="bg-blue-50 border-r-4 border-blue-400 p-3 rounded-lg">
                    <p className="text-xs text-blue-800 font-bold leading-relaxed">
                        تتبع حالة البضاعة المرسلة للمندوب لحظياً. يتم تجميع الأصناف التي أرسلت في "دفعة واحدة" معاً.
                    </p>
                </div>

                {isLoading && transfers.length === 0 ? (
                    <div className="flex flex-col items-center py-12 gap-3">
                        <RefreshCcw className="w-8 h-8 text-blue-400 animate-spin" />
                        <p className="text-sm text-slate-400 font-bold">جاري مسح الرادار...</p>
                    </div>
                ) : transfers.length === 0 ? (
                    <div className="text-center py-10 bg-slate-50 rounded-2xl border-2 border-dashed border-slate-200">
                        <Radar className="w-10 h-10 text-slate-300 mx-auto mb-2" />
                        <p className="text-slate-500 font-bold text-sm">لا يوجد حوالات نشطة لهذا المندوب.</p>
                    </div>
                ) : (
                    <div className={`max-h-[60vh] overflow-y-auto space-y-4 pr-1 custom-scrollbar transition-opacity duration-300 ${isLoading ? "opacity-40 pointer-events-none grayscale-[50%]" : "opacity-100"}`}>
                        {groupedTransfers.map((batch) => {
                            const config = STATUS_MAP[batch.status] || { bg: "bg-slate-100", text: "text-slate-600", label: batch.status, icon: Clock };
                            const StatusIcon = config.icon;

                            return (
                                <div key={batch.batch_id} className="border border-slate-200 rounded-2xl shadow-sm bg-white overflow-hidden transition-all hover:border-blue-200">
                                    <div className={`px-4 py-2.5 flex justify-between items-center border-b border-slate-100 ${config.bg.replace('100', '50')}`}>
                                        <div className="flex items-center gap-2">
                                            <Clock className="w-3.5 h-3.5 text-slate-400" />
                                            <span className="text-[11px] font-black text-slate-500" dir="ltr">{batch.formattedDate}</span>
                                        </div>
                                        <span className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-black ${config.bg} ${config.text}`}>
                                            <StatusIcon className="w-3 h-3" />
                                            {config.label}
                                        </span>
                                    </div>

                                    <div className="p-3 divide-y divide-slate-50">
                                        {batch.items.map(t => (
                                            <div key={t.transfer_id} className="flex items-center justify-between py-2.5 first:pt-0 last:pb-0">
                                                <div className="flex items-center gap-3">
                                                    <div className={`p-2 rounded-xl ${t.delta_cartons > 0 ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'}`}>
                                                        <Package className="w-4 h-4" />
                                                    </div>
                                                    <p className="font-bold text-slate-800 text-sm">{t.product_name}</p>
                                                </div>
                                                <div className={`font-black text-sm tabular-nums ${t.delta_cartons > 0 ? 'text-emerald-600' : 'text-red-600'}`} dir="ltr">
                                                    {t.delta_cartons > 0 ? `+${t.delta_cartons}` : t.delta_cartons}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}

                <div className="flex justify-between items-center pt-4 border-t border-slate-100">
                    <p className="text-[10px] text-slate-400 font-bold italic">ملاحظة: تظهر هنا حوالات الجلسة الحالية فقط.</p>
                    <button
                        onClick={fetchTransfers}
                        disabled={isLoading}
                        className="flex items-center gap-2 px-4 py-2 text-blue-600 bg-blue-50 rounded-xl font-black text-xs hover:bg-blue-100 transition-all disabled:opacity-50 shadow-sm"
                    >
                        <RefreshCcw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
                        تحديث الرادار
                    </button>
                </div>
            </div>
        </Modal>
    );
}