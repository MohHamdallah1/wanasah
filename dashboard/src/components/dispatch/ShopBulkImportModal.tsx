import { useState, useRef, useMemo } from "react";
import { Modal } from "@/components/ui/modal";
import { CustomSelect } from "@/components/ui/custom-select";
import { Zone } from "@/types/dispatch";
import { Upload, ClipboardPaste, FileDown, Trash2, AlertCircle, CheckCircle2, ArrowRight, Save } from "lucide-react";
import * as XLSX from "xlsx";
import Papa from "papaparse";
import { toast } from "sonner";

interface ShopBulkImportModalProps {
    isOpen: boolean;
    onClose: () => void;
    zones: Zone[];
    activeShops: any[];
}

// واجهة لتمثيل بيانات المحل داخل الجدول التفاعلي
interface ParsedShop {
    _id: string; // ID وهمي للواجهة فقط
    name: string;
    phone: string;
    mapLink: string;
    owner: string;
    initialDebt: number;
    errors?: string[];
}

export function ShopBulkImportModal({ isOpen, onClose, zones, activeShops }: ShopBulkImportModalProps) {
    const [step, setStep] = useState<1 | 2>(1);
    const [selectedZoneId, setSelectedZoneId] = useState("");
    const [pasteText, setPasteText] = useState("");
    const [gridData, setGridData] = useState<any[]>([]);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // +++ متغيرات المسودة والتعارض +++
    const [hasDraft, setHasDraft] = useState(false);
    const [conflictRow, setConflictRow] = useState<any>(null);

    // فحص وجود مسودة عند فتح النافذة
    useMemo(() => {
        if (isOpen) setHasDraft(!!localStorage.getItem("shop_import_draft"));
    }, [isOpen, step]);

    // حفظ المسودة تلقائياً مع كل حرف
    useMemo(() => {
        if (step === 2 && gridData.length > 0) {
            localStorage.setItem("shop_import_draft", JSON.stringify({ zoneId: selectedZoneId, data: gridData }));
        }
    }, [gridData, step, selectedZoneId]);

    const loadDraft = () => {
        const draft = JSON.parse(localStorage.getItem("shop_import_draft") || "{}");
        if (draft.data && draft.data.length > 0) {
            setSelectedZoneId(draft.zoneId || "");
            setGridData(draft.data);
            setStep(2);
            toast.success("تم استعادة المسودة بنجاح 📝");
        }
    };
    const clearDraft = () => localStorage.removeItem("shop_import_draft");

    // 1. تنزيل النموذج المعتمد
    const handleDownloadTemplate = () => {
        const headers = ["اسم المحل (إجباري)", "رقم الهاتف (إجباري)", "رابط الخريطة", "اسم المالك", "الذمة الافتتاحية"];
        const ws = XLSX.utils.aoa_to_sheet([headers]);
        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, "المحلات");
        XLSX.writeFile(wb, "نموذج_استيراد_المحلات.xlsx");
    };

    // 2. قراءة الملف
    const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        if (!selectedZoneId) {
            if (fileInputRef.current) fileInputRef.current.value = "";
            return toast.error("⚠️ يرجى اختيار المنطقة أولاً");
        }

        const reader = new FileReader();
        reader.onload = (evt) => {
            const bstr = evt.target?.result;
            const wb = XLSX.read(bstr, { type: "binary" });
            const wsname = wb.SheetNames[0];
            const ws = wb.Sheets[wsname];
            const data = XLSX.utils.sheet_to_json(ws, { header: 1 });
            processRawData(data);
        };
        reader.readAsBinaryString(file);
        if (fileInputRef.current) fileInputRef.current.value = "";
    };

    // 3. قراءة اللصق
    const handlePasteSubmit = () => {
        if (!selectedZoneId) return toast.error("⚠️ يرجى اختيار المنطقة أولاً");
        if (!pasteText.trim()) return toast.error("⚠️ يرجى لصق البيانات أولاً");

        Papa.parse(pasteText, {
            delimiter: "\t",
            complete: (results) => processRawData(results.data)
        });
    };

    // 4. معالجة البيانات وتوزيعها في الجدول
    const processRawData = (data: any[]) => {
        // تنظيف الأسطر الفارغة تماماً
        const cleanedData = data.filter(row => row.length > 0 && row.some((cell: any) => cell !== "" && cell != null));
        if (cleanedData.length === 0) return toast.error("الملف أو النص فارغ ولا يحتوي على بيانات");

        // تجاوز السطر الأول إذا كان يحتوي على عناوين (مثل كلمة "اسم")
        const startIndex = (cleanedData[0] && typeof cleanedData[0][0] === 'string' && cleanedData[0][0].includes("اسم")) ? 1 : 0;
        const actualData = cleanedData.slice(startIndex);

        if (actualData.length === 0) return toast.error("لم يتم العثور على بيانات صالحة بعد العناوين");

        const mappedData: ParsedShop[] = actualData.map(row => ({
            _id: Math.random().toString(36).substring(2, 9),
            name: row[0]?.toString().trim() || "",
            phone: row[1]?.toString().trim() || "",
            mapLink: row[2]?.toString().trim() || "",
            owner: row[3]?.toString().trim() || "",
            initialDebt: parseFloat(row[4]) || 0,
        }));

        setGridData(mappedData);
        setStep(2);
    };

    // 5. تحديث خلية معينة في الجدول التفاعلي
    const updateCell = (id: string, field: keyof ParsedShop, value: string | number) => {
        setGridData(prev => prev.map(row => row._id === id ? { ...row, [field]: value } : row));
    };

    // 6. حذف سطر من الجدول
    const removeRow = (id: string) => {
        setGridData(prev => prev.filter(row => row._id !== id));
    };

    // 7. إغلاق النافذة وتصفيرها
    const handleClose = () => {
        if (conflictRow) return; // منع إغلاق النافذة الرئيسية إذا كانت نافذة التعارض مفتوحة
        onClose();
        setTimeout(() => { setStep(1); setPasteText(""); setGridData([]); setSelectedZoneId(""); }, 300);
    };
    const handleBulkImport = async () => {
        if (stats.invalid > 0) return toast.error("يرجى تصحيح الأخطاء الحمراء قبل الرفع");

        const token = localStorage.getItem("admin_token") || localStorage.getItem("token");
        const payload = {
            zoneId: selectedZoneId,
            fileName: fileInputRef.current?.files?.[0]?.name || "لصق سريع",
            shops: gridData.map((row, index) => ({
                name: row.name,
                phone: row.phone,
                mapLink: row.mapLink,
                owner: row.owner,
                initialDebt: row.initialDebt,
                sequence: index + 1 // حفظ الترتيب كما هو بالجدول
            }))
        };

        const toastId = toast.loading("جاري رفع المحلات وحماية قاعدة البيانات...");
        try {
            const res = await fetch(import.meta.env.VITE_API_URL + "/dispatch/shops/bulk_import", {
                method: "POST",
                headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
                body: JSON.stringify(payload)
            });

            const resData = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(resData.message || "حدث خطأ أثناء الرفع");

            toast.success(resData.message || "تم رفع المحلات بنجاح", { id: toastId });
            clearDraft();
            handleClose();
            // إعادة تحميل الصفحة لتحديث كل البيانات بعد الرفع الضخم
            setTimeout(() => window.location.reload(), 1500);
        } catch (err: any) {
            toast.error("خطأ: " + err.message, { id: toastId });
        }
    };

    // 8. الفحص الدولي والذكي وتوليد رسائل الخطأ (Tooltips)
    const stats = useMemo(() => {
        const total = gridData.length;
        let invalidCount = 0;

        // إعادة ضبط الأخطاء لكل سطر
        gridData.forEach((row, i) => {
            row.errors = [];
            const p = row.phone.trim();
            const l = row.mapLink.trim();

            // فحص الاسم
            if (!row.name.trim()) row.errors.push("اسم المحل مفقود");

            // فحص الهاتف (دولي: 7 لـ 15 رقم، يسمح بـ +)
            const phoneRegex = /^\+?\d{7,15}$/;
            if (!p) row.errors.push("رقم الهاتف مفقود");
            else if (!phoneRegex.test(p)) row.errors.push("رقم الهاتف غير صالح (يجب أن يكون بين 7 إلى 15 رقم)");

            // فحص الرابط (يجب أن يحتوي على علامات الروابط)
            const linkRegex = /http|www|joo\.gl|maps/i;
            if (!l) row.errors.push("رابط الخريطة مفقود");
            else if (!linkRegex.test(l)) row.errors.push("الرابط غير صالح (يجب أن يحتوي على http أو joo.gl)");

            // فحص التكرار (2 من 3) داخل الملف نفسه
            for (let j = 0; j < i; j++) {
                const prev = gridData[j];
                let matches = 0;
                if (row.name.trim() && row.name.trim() === prev.name.trim()) matches++;
                if (p && p === prev.phone.trim()) matches++;
                if (l && l === prev.mapLink.trim()) matches++;
                if (matches >= 2) {
                    row.errors.push(`مكرر مع السطر رقم ${j + 1}`);
                    break;
                }
            }

            // +++ فحص التكرار مع قاعدة البيانات وتحديد الأسباب +++
            let dbMatch = null;
            let matchReason = [];
            for (const ext of activeShops) {
                let m = 0;
                let tempReason = [];
                if (row.name.trim() && row.name.trim() === ext.name?.trim()) { m++; tempReason.push("الاسم"); }
                if (p && p === ext.phone?.trim()) { m++; tempReason.push("الهاتف"); }
                if (l && l === ext.mapLink?.trim()) { m++; tempReason.push("الرابط"); }
                if (m >= 2) {
                    dbMatch = ext;
                    matchReason = tempReason;
                    break;
                }
            }
            row.dbMatch = dbMatch;
            row.isConflict = !!dbMatch;
            if (dbMatch) row.errors.push(`موجود بالنظام لتطابق (${matchReason.join(" و ")})`);

            if (row.errors.length > 0) invalidCount++;
        });

        return { total, valid: total - invalidCount, invalid: invalidCount };
    }, [gridData]);

    return (
        <>
            <Modal isOpen={isOpen} onClose={handleClose} title="📥 استيراد المحلات الذكي" maxWidth={step === 1 ? "max-w-4xl" : "max-w-6xl"}>
                {/* ================== الخطوة 1: اختيار المنطقة والملف ================== */}
                {step === 1 && (
                    <div className="space-y-6">
                        {hasDraft && (
                            <div className="bg-amber-50 border border-amber-200 p-4 rounded-xl flex items-center justify-between mb-4">
                                <div>
                                    <h3 className="font-bold text-amber-800 text-sm">يوجد مسودة غير محفوظة!</h3>
                                    <p className="text-xs text-amber-700 mt-1">لديك بيانات سابقة لم تقم برفعها، هل تريد استكمال العمل عليها؟</p>
                                </div>
                                <div className="flex gap-2">
                                    <button onClick={() => { clearDraft(); setHasDraft(false); toast.info("تم إتلاف المسودة"); }} className="px-3 py-2 bg-white text-red-500 font-bold text-sm rounded-lg hover:bg-red-50 shadow-sm transition-colors" title="حذف المسودة">🗑️</button>
                                    <button onClick={loadDraft} className="px-4 py-2 bg-amber-500 text-white font-bold text-sm rounded-lg hover:bg-amber-600 shadow-sm transition-colors">استعادة المسودة 📝</button>
                                </div>
                            </div>
                        )}
                        <div className="bg-slate-50 p-5 rounded-xl border border-slate-200">
                            <CustomSelect
                                label="1. اختر المنطقة التي سيتم إضافة المحلات إليها:"
                                options={zones.map(z => ({ id: z.id, label: z.name }))}
                                value={selectedZoneId}
                                onChange={setSelectedZoneId}
                                placeholder="-- اضغط لاختيار المنطقة --"
                            />
                        </div>

                        <div className="grid grid-cols-2 gap-6">
                            <div className="border border-slate-200 rounded-xl p-6 flex flex-col items-center justify-center gap-4 bg-white hover:border-[#1e87bb] transition-colors">
                                <div className="text-center">
                                    <h3 className="font-bold text-slate-800 text-lg">رفع ملف (Excel / CSV)</h3>
                                    <p className="text-xs text-slate-500 mt-1">النموذج الرسمي المعتمد للإدخال</p>
                                </div>
                                <button onClick={handleDownloadTemplate} className="text-[#1e87bb] text-xs font-bold flex items-center gap-1 hover:underline bg-blue-50 px-3 py-1.5 rounded-lg">
                                    <FileDown className="w-4 h-4" /> تنزيل النموذج المعتمد
                                </button>
                                <input type="file" ref={fileInputRef} onChange={handleFileUpload} className="hidden" accept=".xlsx, .xls, .csv" />
                                <button onClick={() => fileInputRef.current?.click()} className="w-full mt-2 py-3 rounded-xl bg-emerald-50 text-emerald-600 font-bold border border-emerald-200 hover:bg-emerald-100 transition-colors flex items-center justify-center gap-2">
                                    <Upload className="w-5 h-5" /> اختيار ورفع الملف
                                </button>
                            </div>

                            <div className="border border-slate-200 rounded-xl p-6 flex flex-col gap-3 bg-white hover:border-[#1e87bb] transition-colors">
                                <div className="text-center">
                                    <h3 className="font-bold text-slate-800 text-lg">اللصق السريع (Quick Paste)</h3>
                                    <p className="text-xs text-slate-500 mt-1">انسخ الخلايا من إكسل والصقها مباشرة هنا</p>
                                </div>
                                <textarea value={pasteText} onChange={e => setPasteText(e.target.value)} placeholder="الصق البيانات هنا..." className="w-full h-24 rounded-xl border border-slate-200 p-3 text-sm focus:ring-2 focus:ring-[#1e87bb]/20 outline-none resize-none" dir="rtl" />
                                <button onClick={handlePasteSubmit} className="w-full py-2.5 rounded-xl bg-[#1e87bb] text-white font-bold hover:bg-[#156a94] transition-colors flex items-center justify-center gap-2">
                                    <ClipboardPaste className="w-5 h-5" /> قراءة النص المنسوخ
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                {/* ================== الخطوة 2: غرفة العمليات (الجدول التفاعلي) ================== */}
                {step === 2 && (
                    <div className="space-y-4">
                        {/* لوحة المؤشرات العلوية */}
                        <div className="flex items-center justify-between bg-slate-50 p-4 rounded-xl border border-slate-200">
                            <div className="flex gap-4">
                                <div className="flex flex-col"><span className="text-xs text-slate-500">إجمالي المحلات</span><span className="font-bold text-slate-800">{stats.total}</span></div>
                                <div className="w-px h-8 bg-slate-200"></div>
                                <div className="flex flex-col"><span className="text-xs text-slate-500">جاهز للرفع</span><span className="font-bold text-emerald-600 flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5" /> {stats.valid}</span></div>
                                <div className="w-px h-8 bg-slate-200"></div>
                                <div className="flex flex-col"><span className="text-xs text-slate-500">يحتاج تصحيح</span><span className={`font-bold flex items-center gap-1 ${stats.invalid > 0 ? 'text-red-500 animate-pulse' : 'text-slate-400'}`}><AlertCircle className="w-3.5 h-3.5" /> {stats.invalid}</span></div>
                            </div>
                            <div className="flex gap-2">
                                <button onClick={() => setStep(1)} className="px-4 py-2 bg-white border border-slate-200 rounded-lg text-sm font-bold text-slate-600 hover:bg-slate-50">تراجع</button>
                                <button
                                    disabled={stats.invalid > 0 || stats.total === 0}
                                    onClick={handleBulkImport}
                                    className="px-6 py-2 bg-[#1e87bb] text-white rounded-lg text-sm font-bold hover:bg-[#156a94] flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                                >
                                    اعتماد ورفع البيانات <Save className="w-4 h-4" />
                                </button>
                            </div>
                        </div>

                        {/* الجدول التفاعلي القابل للتعديل */}
                        <div className="border border-slate-200 rounded-xl overflow-hidden max-h-[50vh] overflow-y-auto">
                            <table className="w-full text-sm text-right">
                                <thead className="bg-slate-100 sticky top-0 z-10 shadow-sm">
                                    <tr>
                                        <th className="p-3 text-slate-600 font-bold w-12 text-center">#</th>
                                        <th className="p-3 text-slate-600 font-bold w-1/4">اسم المحل <span className="text-red-500">*</span></th>
                                        <th className="p-3 text-slate-600 font-bold w-1/5">رقم الهاتف <span className="text-red-500">*</span></th>
                                        <th className="p-3 text-slate-600 font-bold">رابط الخريطة <span className="text-red-500">*</span></th>
                                        <th className="p-3 text-slate-600 font-bold">اسم المالك</th>
                                        <th className="p-3 text-slate-600 font-bold w-24">الذمة</th>
                                        <th className="p-3 w-12"></th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-100">
                                    {gridData.map((row: any, index) => {
                                        const hasErr = (keyword: string) => row.errors?.some((e: string) => e.includes(keyword));
                                        const isNameInvalid = hasErr("اسم");
                                        const isPhoneInvalid = hasErr("رقم");
                                        const isMapInvalid = hasErr("رابط");
                                        const isDuplicate = hasErr("مكرر");
                                        const isConflict = row.isConflict; // +++ المتغير اللي نساه جمعة
                                        const tooltip = row.errors?.join("\n") || "";

                                        return (
                                            <tr
                                                key={row._id}
                                                onClick={() => isConflict ? setConflictRow(row) : null}
                                                className={`transition-colors ${isConflict ? 'bg-amber-50 cursor-pointer border-y border-amber-200 hover:bg-amber-100' : (row.errors?.length > 0 ? 'bg-red-50/50' : 'hover:bg-slate-50')}`}
                                                title={tooltip}
                                            >
                                                <td className="p-2 text-center text-slate-400 font-bold relative group">
                                                    {index + 1}
                                                    {row.errors?.length > 0 && (
                                                        <>
                                                            <AlertCircle className={`w-3.5 h-3.5 absolute top-1/2 right-1 -translate-y-1/2 cursor-help ${isConflict ? 'text-amber-500 animate-pulse' : 'text-red-500'}`} />
                                                            {/* +++ Tooltip فوري من Tailwind +++ */}
                                                            <div className="absolute right-6 top-1/2 -translate-y-1/2 w-max max-w-xs bg-slate-800 text-white text-xs p-2 rounded-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50 pointer-events-none shadow-xl whitespace-pre-wrap text-start leading-relaxed">
                                                                {tooltip}
                                                            </div>
                                                        </>
                                                    )}
                                                </td>
                                                <td className="p-2">
                                                    <input value={row.name} onChange={e => updateCell(row._id, 'name', e.target.value)} placeholder="مطلوب" className={`w-full px-3 py-2 rounded-lg border text-sm focus:outline-none focus:ring-2 ${isNameInvalid || isDuplicate || isConflict ? 'border-red-300 bg-red-50 focus:ring-red-200' : 'border-slate-200'}`} disabled={isConflict} />
                                                </td>
                                                <td className="p-2">
                                                    <input value={row.phone} onChange={e => updateCell(row._id, 'phone', e.target.value.replace(/[^\d+]/g, ''))} placeholder="7 إلى 15 رقم" className={`w-full px-3 py-2 rounded-lg border text-sm focus:outline-none focus:ring-2 ${isPhoneInvalid || isDuplicate || isConflict ? 'border-red-300 bg-red-50 focus:ring-red-200' : 'border-slate-200'}`} dir="ltr" disabled={isConflict} />
                                                </td>
                                                <td className="p-2">
                                                    <input value={row.mapLink} onChange={e => updateCell(row._id, 'mapLink', e.target.value)} placeholder="رابط صحيح" className={`w-full px-3 py-2 rounded-lg border text-sm focus:outline-none focus:ring-2 ${isMapInvalid || isDuplicate || isConflict ? 'border-red-300 bg-red-50 focus:ring-red-200' : 'border-slate-200'}`} disabled={isConflict} />
                                                </td>
                                                <td className="p-2">
                                                    <input value={row.owner} onChange={e => updateCell(row._id, 'owner', e.target.value)} className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e87bb]/20" disabled={isConflict} />
                                                </td>
                                                <td className="p-2">
                                                    <input type="number" value={row.initialDebt} onChange={e => updateCell(row._id, 'initialDebt', parseFloat(e.target.value) || 0)} className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm text-center focus:outline-none focus:ring-2 focus:ring-[#1e87bb]/20" disabled={isConflict} />
                                                </td>
                                                <td className="p-2 text-center">
                                                    <button onClick={(e) => { e.stopPropagation(); removeRow(row._id); }} className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"><Trash2 className="w-4 h-4" /></button>
                                                </td>
                                            </tr>
                                        )
                                    })}
                                </tbody>
                            </table>
                            {gridData.length === 0 && <div className="p-8 text-center text-slate-400">لا توجد بيانات للعرض</div>}
                        </div>
                    </div>
                )}
            </Modal>
            {conflictRow && (
                <Modal isOpen={!!conflictRow} onClose={() => setConflictRow(null)} title="⚠️ حل التعارض مع قاعدة البيانات">
                    <div className="space-y-4">
                        <div className="grid grid-cols-2 gap-4">
                            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm relative overflow-hidden">
                                <div className="absolute top-0 right-0 w-1 h-full bg-[#1e87bb]"></div>
                                <h4 className="font-bold text-slate-400 text-xs mb-3 flex items-center gap-1">المحل الموجود بالنظام</h4>
                                <p className="font-bold text-lg text-slate-800">{conflictRow.dbMatch?.name}</p>
                                <p className="text-sm text-slate-600 mt-1">المالك: <span className="font-bold">{conflictRow.dbMatch?.owner || "غير مسجل"}</span></p>
                                <p className="text-xs font-bold text-[#1e87bb] mt-2 bg-blue-50 w-fit px-2 py-1 rounded-md">
                                    المنطقة: {zones.find(z => z.id === conflictRow.dbMatch?.zoneId)?.name || "غير محدد"}
                                </p>
                                <p className="text-sm mt-3 text-slate-500 font-medium" dir="ltr">{conflictRow.dbMatch?.phone}</p>
                            </div>
                            <div className="bg-white p-5 rounded-2xl border border-amber-200 shadow-sm relative overflow-hidden">
                                <div className="absolute top-0 right-0 w-1 h-full bg-amber-400"></div>
                                <h4 className="font-bold text-amber-500 text-xs mb-3 flex items-center gap-1">البيانات الجديدة (في الملف)</h4>
                                <p className="font-bold text-lg text-slate-800">{conflictRow.name}</p>
                                <p className="text-sm text-slate-600 mt-1">المالك: <span className="font-bold">{conflictRow.owner || "غير مسجل"}</span></p>
                                <p className="text-xs font-bold text-amber-600 mt-2 bg-amber-50 w-fit px-2 py-1 rounded-md">
                                    المنطقة المستهدفة: {zones.find(z => z.id === selectedZoneId)?.name || ""}
                                </p>
                                <p className="text-sm mt-3 text-slate-500 font-medium" dir="ltr">{conflictRow.phone}</p>
                            </div>
                        </div>
                        <div className="bg-red-50 border border-red-200 rounded-xl p-3 mt-4">
                            <p className="text-xs text-red-700 font-bold flex items-center gap-1 mb-1">
                                🛑 يمنع النظام إضافة هذا المحل لتجنب تداخل الذمم المالية!
                            </p>
                            <p className="text-[10px] text-red-600 leading-relaxed">
                                إذا كان هذا المحل عبارة عن "فرع جديد" لنفس المالك، يجب عليك تغيير <strong>اسم المحل</strong> (مثال: إضافة "فرع 2") مع تغيير <strong>رقم الهاتف</strong> لتجاوز هذا المنع.
                            </p>
                        </div>
                        <div className="w-full mt-4">
                            <button onClick={() => { removeRow(conflictRow._id); setConflictRow(null); }} className="w-full bg-slate-100 text-slate-700 py-3 rounded-xl font-bold hover:bg-slate-200 transition-colors border border-slate-300">
                                تجاهل المحل وحذفه من الملف المرفوع 🗑️
                            </button>
                        </div>
                    </div>
                </Modal>
            )}
        </>
    );
}