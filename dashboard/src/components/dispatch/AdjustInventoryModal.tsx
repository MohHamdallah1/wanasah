import { useState, useEffect, useMemo } from "react";
import { Modal } from "@/components/ui/modal";
import { Package, Search, Plus, Minus, Save, ArrowRight, Eye } from "lucide-react";
import { toast } from "sonner";
import { PendingRoute } from "@/types/dispatch";

// دالة الجلب المخصصة
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

interface ProductInventory {
    product_id: string;
    product_name: string;
    current_cartons: number;
    current_packs: number;
}

interface AdjustInventoryModalProps {
    isOpen: boolean;
    onClose: () => void;
    route: PendingRoute | null;
    onSuccess: () => void;
}

export function AdjustInventoryModal({ isOpen, onClose, route, onSuccess }: AdjustInventoryModalProps) {
    const [inventory, setInventory] = useState<ProductInventory[]>([]);
    const [deltas, setDeltas] = useState<Record<string, number>>({});
    const [searchQuery, setSearchQuery] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [step, setStep] = useState<"edit" | "review">("edit"); // +++ نظام الخطوتين +++

    useEffect(() => {
        if (isOpen && route) {
            fetchInventory();
            setDeltas({});
            setSearchQuery("");
            setStep("edit");
        }
    }, [isOpen, route]);

    const fetchInventory = async () => {
        setIsLoading(true);
        try {
            const data = await authenticatedFetch(`/dispatch/route/${route?.id}/live_inventory`);
            setInventory(data || []);
        } catch (error: any) {
            toast.error(error.message);
        } finally {
            setIsLoading(false);
        }
    };

    const handleDeltaChange = (productId: string, change: number) => {
        setDeltas(prev => ({ ...prev, [productId]: (prev[productId] || 0) + change }));
    };

    const handleDirectInput = (productId: string, value: string) => {
        const num = parseInt(value);
        setDeltas(prev => ({ ...prev, [productId]: isNaN(num) ? 0 : num }));
    };

    const handleReview = () => {
        const hasChanges = Object.values(deltas).some(d => d !== 0);
        if (!hasChanges) {
            toast.info("لم تقم بإجراء أي تعديلات للمراجعة");
            return;
        }
        setStep("review");
    };

    const handleSave = async () => {
        const payloadDeltas = Object.entries(deltas)
            .filter(([_, delta]) => delta !== 0)
            .map(([id, delta]) => ({ product_id: id, delta_cartons: delta }));

        setIsSaving(true);
        try {
            await authenticatedFetch(`/dispatch/route/${route?.id}/adjust_inventory`, {
                method: "PUT",
                body: JSON.stringify({ deltas: payloadDeltas })
            });
            toast.success("تم توثيق وتعديل الحمولة بنجاح ✅");
            onSuccess();
            onClose();
        } catch (error: any) {
            toast.error(error.message);
        } finally {
            setIsSaving(false);
        }
    };

    const filteredInventory = useMemo(() => {
        return inventory.filter(item => item.product_name.toLowerCase().includes(searchQuery.toLowerCase()));
    }, [inventory, searchQuery]);

    const inVanItems = filteredInventory.filter(item => item.current_cartons > 0 || item.current_packs > 0 || (deltas[item.product_id] && deltas[item.product_id] !== 0));
    const otherItems = filteredInventory.filter(item => item.current_cartons === 0 && item.current_packs === 0 && (!deltas[item.product_id] || deltas[item.product_id] === 0));

    // العناصر التي تم تعديلها فقط (لشاشة المراجعة)
    const modifiedItems = inventory.filter(item => deltas[item.product_id] && deltas[item.product_id] !== 0);

    const renderItemRow = (item: ProductInventory, isReviewMode: boolean = false) => {
        const delta = deltas[item.product_id] || 0;
        const newTotal = item.current_cartons + delta;
        const isNegative = delta < 0;
        const isPositive = delta > 0;

        return (
            <div key={item.product_id} className={`flex items-center justify-between p-3 rounded-xl border ${isReviewMode ? (isPositive ? 'bg-emerald-50 border-emerald-200' : 'bg-red-50 border-red-200') : 'bg-slate-50 border-slate-200'}`}>
                <div className="flex-1">
                    <p className="font-bold text-slate-800 text-sm">{item.product_name}</p>
                    <div className="flex items-center gap-2 mt-1">
                        <span className="text-xs text-slate-500">الجرد اللحظي الحالي:</span>
                        <span className="text-xs font-bold text-slate-700 bg-slate-200 px-2 py-0.5 rounded-md">
                            {item.current_cartons} كرتونة {item.current_packs > 0 ? `و ${item.current_packs} حبة` : ''}
                        </span>
                    </div>
                </div>

                <div className="flex items-center gap-4">
                    {!isReviewMode ? (
                        <div className="flex items-center gap-2 bg-white border border-slate-200 rounded-lg p-1">
                            <button onClick={() => handleDeltaChange(item.product_id, -1)} className="p-1.5 rounded-md text-red-500 hover:bg-red-50"><Minus className="w-4 h-4" /></button>
                            {/* +++ إدخال مباشر من الكيبورد +++ */}
                            <input
                                type="number"
                                value={delta || ""}
                                onChange={(e) => handleDirectInput(item.product_id, e.target.value)}
                                placeholder="0"
                                className="w-12 text-center font-bold text-slate-700 text-sm outline-none bg-transparent"
                                dir="ltr"
                            />
                            <button onClick={() => handleDeltaChange(item.product_id, 1)} className="p-1.5 rounded-md text-emerald-500 hover:bg-emerald-50"><Plus className="w-4 h-4" /></button>
                        </div>
                    ) : (
                        <div className={`font-bold text-lg ${isPositive ? 'text-emerald-600' : 'text-red-600'} dir-ltr`}>
                            {isPositive ? `+${delta}` : delta} ك
                        </div>
                    )}

                    <div className="flex flex-col items-center">
                        <span className="text-[10px] text-slate-400">بعد الحفظ</span>
                        <div className={`w-16 text-center py-1 rounded-lg border text-sm font-bold ${isPositive ? 'bg-emerald-100 border-emerald-300 text-emerald-800' : isNegative ? 'bg-red-100 border-red-300 text-red-800' : 'bg-slate-100 border-slate-200 text-slate-500'}`}>
                            {newTotal}
                        </div>
                    </div>
                </div>
            </div>
        );
    };

    return (
        <Modal isOpen={isOpen} onClose={onClose} title={step === "edit" ? "📦 تعديل الحمولة اللحظي (Mid-Day Restock)" : "👀 مراجعة الإضافات والتأكيد"}>
            <div className="space-y-4">
                {step === "edit" ? (
                    <>
                        <div className="relative">
                            <Search className="absolute right-3 top-2.5 text-slate-400 w-5 h-5" />
                            <input type="text" placeholder="ابحث عن صنف لتعديله..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)} className="w-full pl-4 pr-10 py-2 border border-slate-200 rounded-xl focus:ring-2 focus:ring-[#1e87bb] outline-none transition-all" />
                        </div>

                        <div className="max-h-[50vh] overflow-y-auto space-y-6 pr-2">
                            {isLoading ? (
                                <p className="text-center text-slate-500 py-4">جاري قراءة الجرد اللحظي للمندوب...</p>
                            ) : (
                                <>
                                    {inVanItems.length > 0 && (
                                        <div className="space-y-2">
                                            <h3 className="text-xs font-bold text-slate-500 flex items-center gap-1"><Package className="w-4 h-4" /> في الشاحنة الآن</h3>
                                            {inVanItems.map(item => renderItemRow(item, false))}
                                        </div>
                                    )}
                                    {otherItems.length > 0 && (
                                        <div className="space-y-2 pt-4 border-t border-slate-100">
                                            <h3 className="text-xs font-bold text-slate-500 flex items-center gap-1"><Plus className="w-4 h-4" /> أصناف غير موجودة بالسيارة</h3>
                                            {otherItems.map(item => renderItemRow(item, false))}
                                        </div>
                                    )}
                                </>
                            )}
                        </div>

                        <div className="flex gap-3 pt-4 border-t border-slate-100">
                            <button onClick={onClose} className="flex-1 px-4 py-2 text-slate-500 bg-slate-100 rounded-xl font-bold hover:bg-slate-200">إلغاء</button>
                            <button onClick={handleReview} className="flex-1 px-4 py-2 text-white bg-amber-500 rounded-xl font-bold hover:bg-amber-600 flex items-center justify-center gap-2">
                                مراجعة الإضافات <Eye className="w-4 h-4" />
                            </button>
                        </div>
                    </>
                ) : (
                    <>
                        <div className="bg-amber-50 border border-amber-200 p-3 rounded-xl mb-4">
                            <p className="text-sm text-amber-800 font-bold flex items-center gap-2">
                                <Eye className="w-4 h-4" /> يرجى مراجعة التعديلات التالية قبل اعتمادها نهائياً:
                            </p>
                        </div>

                        <div className="max-h-[50vh] overflow-y-auto space-y-2 pr-2">
                            {modifiedItems.map(item => renderItemRow(item, true))}
                        </div>

                        <div className="flex gap-3 pt-4 border-t border-slate-100">
                            <button onClick={() => setStep("edit")} disabled={isSaving} className="flex-1 px-4 py-2 text-slate-500 bg-slate-100 rounded-xl font-bold hover:bg-slate-200 flex items-center justify-center gap-2">
                                <ArrowRight className="w-4 h-4" /> رجوع للتعديل
                            </button>
                            <button onClick={handleSave} disabled={isSaving} className="flex-[2] px-4 py-2 text-white bg-[#1e87bb] rounded-xl font-bold hover:bg-[#156a94] flex items-center justify-center gap-2">
                                {isSaving ? "جاري التوثيق..." : "اعتماد وتوثيق في الدفتر"} <Save className="w-4 h-4" />
                            </button>
                        </div>
                    </>
                )}
            </div>
        </Modal>
    );
}