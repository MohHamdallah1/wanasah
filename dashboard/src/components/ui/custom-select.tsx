import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, Search } from "lucide-react";
import { CustomSelectOption } from "@/types/dispatch";

interface CustomSelectProps {
  label: string;
  options: CustomSelectOption[];
  value: string;
  onChange: (id: string) => void;
  className?: string;
  placeholder?: string;
  disabled?: boolean;
}

export function CustomSelect({
  label,
  options,
  value,
  onChange,
  className = "",
  placeholder = "—",
  disabled = false,
}: CustomSelectProps) {
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const fn = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", fn);
    return () => document.removeEventListener("mousedown", fn);
  }, []);

  useEffect(() => {
    if (!open) setSearchQuery("");
  }, [open]);

  const selected = options.find((o) => o.id === value);
  const filtered = options.filter((o) =>
    o.label.toLowerCase().includes(searchQuery.trim().toLowerCase())
  );

  return (
    <div ref={ref} className={`flex flex-col gap-1.5 ${className}`}>
      {label && <span className="text-xs font-semibold text-slate-600">{label}</span>}
      <div className="relative">
        <button
          type="button"
          onClick={() => !disabled && setOpen((p) => !p)}
          className={`w-full min-w-[180px] rounded-xl border px-4 py-2.5 text-sm font-medium transition-colors flex items-center justify-between gap-2 ${
            disabled
              ? "bg-slate-50 border-slate-200 text-slate-400 cursor-not-allowed"
              : "bg-white border-slate-300 text-slate-800 hover:bg-slate-50 hover:border-slate-400"
          }`}
          disabled={disabled}
        >
          <span className="truncate">{selected?.label ?? placeholder}</span>
          {!disabled && (
            <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}>
              <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" strokeWidth={1.5} />
            </motion.span>
          )}
        </button>
        <AnimatePresence>
          {open && !disabled && (
            <motion.div
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.2 }}
              className="absolute top-full start-0 mt-1 z-[60] min-w-[240px] rounded-xl bg-white border border-slate-200 shadow-lg overflow-hidden flex flex-col max-h-[280px]"
            >
              <div className="sticky top-0 z-10 p-2 border-b border-slate-200 bg-white">
                <div className="relative">
                  <Search className="absolute end-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" strokeWidth={1.5} />
                  <input
                    type="search"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="بحث..."
                    className="w-full rounded-lg border border-slate-300 bg-white ps-3 pe-9 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#1e87bb]/20 focus:border-[#1e87bb]"
                  />
                </div>
              </div>
              <div className="overflow-y-auto p-1">
                {filtered.length === 0 ? (
                  <p className="px-3 py-4 text-sm text-slate-500 text-center">لا توجد نتائج</p>
                ) : (
                  filtered.map((opt) => (
                    <button
                      key={opt.id}
                      type="button"
                      onClick={() => {
                        onChange(opt.id);
                        setOpen(false);
                      }}
                      className={`w-full text-start px-4 py-2.5 text-sm font-medium rounded-lg transition-colors flex items-center justify-between gap-2 ${
                        value === opt.id
                          ? "bg-emerald-50 text-[#1e87bb]"
                          : "text-slate-700 hover:bg-slate-50"
                      }`}
                    >
                      <span className="truncate">{opt.label}</span>
                      {opt.scheduleStatus === "overdue" && (
                        <span className="text-[10px] bg-red-100 text-red-700 px-1.5 py-0.5 rounded-md whitespace-nowrap shrink-0">متأخر</span>
                      )}
                      {opt.scheduleStatus === "today" && (
                        <span className="text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded-md whitespace-nowrap shrink-0">مجدول اليوم</span>
                      )}
                    </button>
                  ))
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
