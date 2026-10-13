import { Eye, EyeOff } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import "./RepresentativePasswordInput.css";

interface RepresentativePasswordInputProps {
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  autoFocus?: boolean;
  className: string;
  placeholder?: string;
  resetSignal?: unknown;
}

export function RepresentativePasswordInput({
  id,
  value,
  onChange,
  disabled = false,
  autoFocus = false,
  className,
  placeholder,
  resetSignal,
}: RepresentativePasswordInputProps) {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    setVisible(false);
  }, [resetSignal]);

  const toggleLabel = t(
    visible
      ? "representativesVehicles.representatives.passwordVisibility.hide"
      : "representativesVehicles.representatives.passwordVisibility.show",
  );

  return (
    <div className="relative">
      <input
        id={id}
        autoFocus={autoFocus}
        type={visible ? "text" : "password"}
        minLength={8}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className={`representative-password-input ${className} pe-11`}
        disabled={disabled}
        autoComplete="new-password"
        required
        aria-required="true"
      />
      {value ? (
        <button
          type="button"
          onClick={() => setVisible((current) => !current)}
          aria-label={toggleLabel}
          title={toggleLabel}
          className="absolute inset-y-0 end-1 my-auto inline-grid h-8 w-8 place-items-center rounded-lg text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
        >
          {visible ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
        </button>
      ) : null}
    </div>
  );
}
