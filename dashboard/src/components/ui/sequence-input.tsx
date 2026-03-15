import { useState, useEffect } from "react";

interface SequenceInputProps {
  value: number;
  onCommit: (n: number) => void;
}

export function SequenceInput({
  value,
  onCommit,
}: SequenceInputProps) {
  const [localValue, setLocalValue] = useState(String(value));
  
  useEffect(() => {
    setLocalValue(String(value));
  }, [value]);

  const handleBlur = () => {
    const n = parseInt(localValue);
    if (!isNaN(n) && n !== value) {
      onCommit(n);
    } else {
      setLocalValue(String(value));
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      const n = parseInt(localValue);
      if (!isNaN(n) && n !== value) {
        onCommit(n);
      }
    }
  };

  return (
    <input
      type="number"
      value={localValue}
      onChange={(e) => setLocalValue(e.target.value)}
      onBlur={handleBlur}
      onKeyDown={handleKeyDown}
      onFocus={(e) => e.target.select()}
      className="w-12 h-8 text-center bg-white border border-slate-200 rounded-lg font-bold text-slate-700 outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
    />
  );
}
