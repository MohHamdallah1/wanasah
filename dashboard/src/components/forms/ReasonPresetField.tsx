import { useEffect, useState, type KeyboardEvent } from "react";

type Props = {
  label: string;
  chooseLabel: string;
  otherLabel: string;
  customPlaceholder: string;
  presets: string[];
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  maxLength: number;
  multiline?: boolean;
  autoFocus?: boolean;
  canSubmit?: boolean;
  onSubmit?: () => void;
  onCancel?: () => void;
};

const OTHER = "__OTHER__";

export function ReasonPresetField({
  label,
  chooseLabel,
  otherLabel,
  customPlaceholder,
  presets,
  value,
  onChange,
  disabled = false,
  maxLength,
  multiline = false,
  autoFocus = false,
  canSubmit = false,
  onSubmit,
  onCancel,
}: Props) {
  const valueIsPreset = presets.includes(value);
  const [otherSelected, setOtherSelected] = useState(
    () => Boolean(value) && !valueIsPreset,
  );

  useEffect(() => {
    if (valueIsPreset) {
      setOtherSelected(false);
      return;
    }
    if (value) {
      setOtherSelected(true);
    }
  }, [value, valueIsPreset]);

  const selected = valueIsPreset
    ? value
    : otherSelected
      ? OTHER
      : "";

  const handleKeyDown = (
    event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>,
  ) => {
    if (event.key === "Escape" && onCancel) {
      event.preventDefault();
      onCancel();
      return;
    }
    if (
      event.key === "Enter" &&
      (!multiline || !event.shiftKey) &&
      canSubmit &&
      onSubmit
    ) {
      event.preventDefault();
      onSubmit();
    }
  };

  const custom = selected === OTHER;

  return (
    <label className="block text-[10px] font-black text-slate-600">
      {label}
      <select
        value={selected}
        disabled={disabled}
        autoFocus={autoFocus}
        onKeyDown={handleKeyDown}
        onChange={(event) => {
          const next = event.target.value;
          if (next === OTHER) {
            setOtherSelected(true);
            if (valueIsPreset) onChange("");
            return;
          }
          setOtherSelected(false);
          onChange(next);
        }}
        className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100 disabled:opacity-50"
      >
        <option value="" disabled>
          {chooseLabel}
        </option>
        {presets.map((preset) => (
          <option key={preset} value={preset}>
            {preset}
          </option>
        ))}
        <option value={OTHER}>{otherLabel}</option>
      </select>

      {custom ? (
        multiline ? (
          <textarea
            autoFocus
            value={value}
            maxLength={maxLength}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={customPlaceholder}
            className="mt-2 min-h-20 w-full resize-y rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100 disabled:opacity-50"
          />
        ) : (
          <input
            autoFocus
            value={value}
            maxLength={maxLength}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={customPlaceholder}
            className="mt-2 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100 disabled:opacity-50"
          />
        )
      ) : null}
    </label>
  );
}
