import { useState, useEffect } from "react";
import { Modal } from "@/components/ui/modal";
import { Radar, CheckCircle, XCircle, Clock, Package } from "lucide-react";
import { toast } from "sonner";
import { PendingRoute } from "@/types/dispatch";

const authenticatedFetch = async (endpoint: string, options: RequestInit = {}) => {
    const token = localStorage.getItem("admin_token") || localStorage.getItem("token");
    const res = await fetch(import.meta.env.VITE_API_URL + endpoint, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${token}`,
            ...options.headers
        }
    });
    if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.message || "حدث خطأ غير متوقع");
    }
    return res.json();
};

interface TransferRecord {
    transfer_id: number;
    product_name: string;
    delta_cartons: number;
    status: 'pending' | 'accepted' | 'rejected';
    created_at: string;
    batch_id: string; // +++ الحقل الجديد للدمج +++
}

interface TransfersRadarModalProps {
    isOpen: boolean;
    onClose: () => void;
    route: PendingRoute | null;
}

export function TransfersRadarModal({ isOpen, onClose, route }: TransfersRadarModalProps) {
    const [transfers, setTransfers] = useState<TransferRecord[]>([]);
    const [isLoading, setIsLoading] = useState(false);

    useEffect(() => {
        if (isOpen && route) {
            fetchTransfers();
        }
    }, [isOpen, route]);

    const fetchTransfers = async () => {
        setIsLoading(true);
        try {
            const data = await authenticatedFetch(`/dispatch/route/${route?.id}/transfers`);
            setTransfers(data || []);
        } catch (error: any) {
            toast.error(error.message);
        } finally {
            setIsLoading(false);
        }
    };

    const getStatusBadge = (status: string) => {
        switch (status) {
            case 'pending':
                return <span className="flex items-center gap-1 bg-amber-100 text-amber-700 px-2 py-1 rounded-md text-xs font-bold"><Clock className="w-3 h-3" /> بانتظار المندوب</span>;
            case 'accepted':
                return <span className="flex items-center gap-1 bg-emerald-100 text-emerald-700 px-2 py-1 rounded-md text-xs font-bold"><CheckCircle className="w-3 h-3" /> تم الاستلام</span>;
            case 'rejected':
                return <span className="flex items-center gap-1 bg-red-100 text-red-700 px-2 py-1 rounded-md text-xs font-bold"><XCircle className="w-3 h-3" /> رفض الاستلام</span>;
            default:
                return <span>{status}</span>;
        }
    };

    // +++ خوارزمية التجميع (Batching Logic) لنسف التشتت +++
    const groupedTransfers = Object.values(
        transfers.reduce((acc, t) => {
            const key = t.batch_id || `SINGLE_${t.transfer_id}`;
            if (!acc[key]) {
                acc[key] = {
                    batch_id: key,
                    created_at: t.created_at,
                    status: t.status, // الحوالة المجمعة لها نفس الحالة
                    items: []
                };
            }
            acc[key].items.push(t);
            return acc;
        }, {} as Record<string, { batch_id: string, created_at: string, status: string, items: TransferRecord[] }>)
    );

    return (
        <Modal isOpen={isOpen} onClose={onClose} title={`📡 رادار المصافحات (المندوب: ${route?.driverName || ''})`}>
            <div className="space-y-4">
                <p className="text-sm text-slate-500 font-bold mb-4">
                    يعرض هذا الرادار الدفعات التي أرسلتها للمندوب. يتم تجميع الأصناف المرسلة معاً في بطاقة واحدة.
                </p>

                {isLoading ? (
                    <p className="text-center text-slate-500 py-4">جاري قراءة الرادار...</p>
                ) : transfers.length === 0 ? (
                    <div className="text-center py-8 bg-slate-50 rounded-xl border border-slate-200">
                        <Radar className="w-12 h-12 text-slate-300 mx-auto mb-2" />
                        <p className="text-slate-500 font-bold">لا يوجد حوالات أُرسلت لهذا المندوب في هذه الجلسة.</p>
                    </div>
                ) : (
                    <div className="max-h-[50vh] overflow-y-auto space-y-4 pr-2">
                        {groupedTransfers.map((batch) => (
                            <div key={batch.batch_id} className="border border-slate-200 rounded-xl shadow-sm bg-white overflow-hidden">
                                {/* ترويسة البطاقة (الدفعة) */}
                                <div className="bg-slate-50 border-b border-slate-100 p-3 flex justify-between items-center">
                                    <div className="flex items-center gap-2">
                                        <Clock className="w-4 h-4 text-slate-400" />
                                        <span className="text-xs font-bold text-slate-500" dir="ltr">{batch.created_at}</span>
                                    </div>
                                    {getStatusBadge(batch.status)}
                                </div>

                                {/* قائمة الأصناف داخل هذه الدفعة */}
                                <div className="p-3 divide-y divide-slate-100">
                                    {batch.items.map(t => (
                                        <div key={t.transfer_id} className="flex items-center justify-between py-2 first:pt-0 last:pb-0">
                                            <div className="flex items-center gap-3">
                                                <div className={`p-1.5 rounded-lg ${t.delta_cartons > 0 ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'}`}>
                                                    <Package className="w-4 h-4" />
                                                </div>
                                                <p className="font-bold text-slate-800 text-sm">{t.product_name}</p>
                                            </div>
                                            <div className={`font-bold text-sm dir-ltr ${t.delta_cartons > 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                                                {t.delta_cartons > 0 ? `+${t.delta_cartons}` : t.delta_cartons} كرتونة
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        ))}
                    </div>
                )}

                <div className="flex justify-end pt-4 border-t border-slate-100">
                    <button onClick={fetchTransfers} className="px-4 py-2 text-[#1e87bb] bg-blue-50 rounded-xl font-bold hover:bg-blue-100 transition-colors">
                        تحديث الرادار 🔄
                    </button>
                </div>
            </div>
        </Modal>
    );
}