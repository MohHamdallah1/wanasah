import { ShieldCheck } from "lucide-react";

interface StocktakeIndependentWaitProps {
  onCancel: () => void;
}

export function StocktakeIndependentWait({
  onCancel,
}: StocktakeIndependentWaitProps) {
  return (
    <div className="glass-card flex-1 flex items-center justify-center border border-slate-200 shadow-sm p-8">
      <div className="max-w-xl text-center space-y-4">
        <div className="mx-auto w-16 h-16 rounded-2xl bg-red-50 border border-red-100 flex items-center justify-center">
          <ShieldCheck className="w-8 h-8 text-red-500" />
        </div>
        <h3 className="text-xl font-black text-slate-800">
          إعادة عد مستقلة مطلوبة
        </h3>
        <p className="text-sm text-slate-600 leading-7 font-bold">
          تم تثبيت العجز وتفويض Recount جديد. منفذ المحاولة السابقة ممنوع رقابياً من تنفيذ المحاولة التالية.
          سجّل الدخول بحساب مستخدم مخول آخر، وستظهر له ورقة عد عمياء جديدة تلقائياً.
        </p>
        <button
          onClick={onCancel}
          className="px-5 h-10 bg-slate-100 hover:bg-red-50 text-slate-600 hover:text-red-600 font-bold rounded-xl transition-colors"
        >
          إلغاء جلسة الجرد
        </button>
      </div>
    </div>
  );
}
