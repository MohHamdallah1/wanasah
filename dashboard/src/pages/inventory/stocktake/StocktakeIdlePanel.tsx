import { Lock, ShieldCheck } from "lucide-react";

interface StocktakeIdlePanelProps {
  onStart: () => void;
}

export function StocktakeIdlePanel({
  onStart,
}: StocktakeIdlePanelProps) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center bg-slate-50/50 rounded-3xl border border-slate-200/50 overflow-hidden relative">
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-64 h-64 bg-amber-400/10 blur-[80px] rounded-full pointer-events-none" />

      <div className="text-center mb-10 z-10">
        <h2 className="text-3xl font-black text-slate-800 tracking-tight">
          نظام تسوية المخزون
        </h2>
        <p className="text-slate-500 font-bold mt-2">
          الجرد الشامل يبدأ بعد قفل المستودع المحدد وأخذ Snapshot ثابت
        </p>
      </div>

      <button
        type="button"
        className="relative w-80 h-48 rounded-xl overflow-hidden shadow-[0_0_30px_rgba(245,158,11,0.2)] group cursor-pointer p-[3px] bg-slate-800"
        dir="ltr"
        onClick={onStart}
        aria-label="إغلاق المستودع وبدء الجرد الشامل"
      >
        <div
          className="absolute inset-[-150%] opacity-80 animate-spin pointer-events-none"
          style={{
            backgroundImage:
              "conic-gradient(from 0deg, transparent 75%, rgba(245,158,11,0.8) 100%)",
            animationDuration: "3s",
          }}
        />
        <div
          className="absolute inset-[-150%] opacity-80 animate-spin pointer-events-none"
          style={{
            backgroundImage:
              "conic-gradient(from 180deg, transparent 75%, rgba(245,158,11,0.8) 100%)",
            animationDuration: "3s",
          }}
        />

        <div className="relative w-full h-full bg-slate-900 rounded-[9px] overflow-hidden">
          <div className="absolute inset-0 flex items-center justify-center bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-amber-900/40 via-slate-900 to-slate-900">
            <div className="flex flex-col items-center gap-3 scale-90 opacity-0 group-hover:scale-100 group-hover:opacity-100 transition-all duration-500 delay-100">
              <div className="w-16 h-16 rounded-full bg-amber-500/20 flex items-center justify-center border border-amber-500/30 animate-pulse">
                <Lock className="w-8 h-8 text-amber-500" />
              </div>
              <span className="text-white font-black text-lg tracking-wide drop-shadow-md">
                إغلاق المستودع وبدء الجرد
              </span>
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
      </button>

      <p className="mt-8 text-xs text-slate-400 font-bold flex items-center gap-1.5">
        <ShieldCheck className="w-3.5 h-3.5" />
        العد الأول أعمى، ولا يظهر الرصيد المتوقع إلا بعد تثبيت المحاولة
      </p>
    </div>
  );
}
