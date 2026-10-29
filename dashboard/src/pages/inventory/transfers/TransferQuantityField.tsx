import { useRef, type KeyboardEventHandler } from "react";
import { X } from "lucide-react";

interface TransferQuantityFieldProps {
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
  clearLabel: string;
  unit: string;
  disabled: boolean;
  onKeyDown: KeyboardEventHandler<HTMLInputElement>;
  inputWidth?: string;
  invalid?: boolean;
}

export function TransferQuantityField({
  value,
  onChange,
  ariaLabel,
  clearLabel,
  unit,
  disabled,
  onKeyDown,
  inputWidth = "w-20",
  invalid,
}: TransferQuantityFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-slate-200 bg-white px-1.5">
      <input
        ref={inputRef}
        type="text"
        inputMode="decimal"
        data-transfer-quantity-input="true"
        aria-label={ariaLabel}
        aria-invalid={invalid}
        value={value}
        disabled={disabled}
        onKeyDown={onKeyDown}
        onChange={(event) => onChange(event.target.value)}
        className={`h-8 min-w-0 ${inputWidth} bg-transparent text-center text-xs font-black outline-none`}
      />
      {value.trim() && !disabled ? (
        <button
          type="button"
          aria-label={`${clearLabel}: ${ariaLabel}`}
          title={clearLabel}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => {
            onChange("");
            inputRef.current?.focus();
          }}
          className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
        >
          <X className="h-3 w-3" aria-hidden="true" />
        </button>
      ) : null}
      <span className="whitespace-nowrap text-[10px] font-bold text-slate-500">{unit}</span>
    </div>
  );
}
