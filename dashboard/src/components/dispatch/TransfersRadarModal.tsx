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

    return (
        <Modal isOpen={isOpen} onClose={onClose} title={`📡 رادار المصافحات (المندوب: ${route?.driverName || ''})`}>
            <div className="space-y-4">
                <p className="text-sm text-slate-500 font-bold mb-4">
                    هذه الشاشة تعرض حالة البضاعة التي أرسلتها للمندوب أثناء عمله في الشارع.
                </p>

                {isLoading ? (
                    <p className="text-center text-slate-500 py-4">جاري قراءة الرادار...</p>
                ) : transfers.length === 0 ? (
                    <div className="text-center py-8 bg-slate-50 rounded-xl border border-slate-200">
                        <Radar className="w-12 h-12 text-slate-300 mx-auto mb-2" />
                        <p className="text-slate-500 font-bold">لا يوجد حوالات أُرسلت لهذا المندوب في هذه الجلسة.</p>
                    </div>
                ) : (
                    <div className="max-h-[50vh] overflow-y-auto space-y-3 pr-2">
                        {transfers.map((t) => (
                            <div key={t.transfer_id} className="flex items-center justify-between p-3 bg-white border border-slate-200 rounded-xl shadow-sm">
                                <div className="flex items-center gap-3">
                                    <div className={`p-2 rounded-lg ${t.delta_cartons > 0 ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'}`}>
                                        <Package className="w-5 h-5" />
                                    </div>
                                    <div>
                                        <p className="font-bold text-slate-800 text-sm">{t.product_name}</p>
                                        <p className="text-xs text-slate-400 mt-0.5" dir="ltr">{t.created_at}</p>
                                    </div>
                                </div>

                                <div className="flex flex-col items-end gap-2">
                                    <div className={`font-bold text-sm dir-ltr ${t.delta_cartons > 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                                        {t.delta_cartons > 0 ? `+${t.delta_cartons}` : t.delta_cartons} كرتونة
                                    </div>
                                    {getStatusBadge(t.status)}
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