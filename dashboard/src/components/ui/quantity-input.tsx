import { useState, useEffect } from "react";
import { Plus, Minus } from "lucide-react";

interface QuantityInputProps {
  value: number;
  onChange: (n: number) => void;
  min?: number;
}

export function QuantityInput({
  value,
  onChange,
  min = 0,
}: QuantityInputProps) {
  const [inputStr, setInputStr] = useState(String(value));
  
  const syncFromProp = () => {
    const n = Math.max(min, Number(inputStr) || 0);
    setInputStr(String(n));
    onChange(n);
  };

  useEffect(() => {
    setInputStr(String(value));
  }, [value]);

  const handleBlur = () => syncFromProp();
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") syncFromProp();
  };

  const inc = () => {
    const n = Math.max(min, (Number(inputStr) || 0) + 1);
    setInputStr(String(n));
    onChange(n);
  };

  const dec = () => {
    const n = Math.max(min, (Number(inputStr) || 0) - 1);
    setInputStr(String(n));
    onChange(n);
  };

  return (
    <div className="flex items-center rounded-lg border border-slate-300 bg-white overflow-hidden w-fit">
      <button
        type="button"
        onClick={dec}
        className="p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-50 transition-colors"
        aria-label="نقص"
      >
        <Minus className="w-4 h-4" strokeWidth={1.5} />
      </button>
      <input
        type="text"
        inputMode="numeric"
        value={inputStr}
        onChange={(e) => setInputStr(e.target.value.replace(/[^0-9]/g, ""))}
        onBlur={handleBlur}
        onKeyDown={handleKeyDown}
        onFocus={(e) => e.target.select()}
        className="w-16 text-center py-1.5 text-sm font-medium tabular-nums text-slate-800 bg-transparent border-0 focus:outline-none focus:ring-0"
      />
      <button
        type="button"
        onClick={inc}
        className="p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-50 transition-colors"
        aria-label="زيادة"
      >
        <Plus className="w-4 h-4" strokeWidth={1.5} />
      </button>
    </div>
  );
}
