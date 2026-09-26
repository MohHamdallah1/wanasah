import type {
  LucideIcon,
} from "lucide-react";
import type {
  ReactNode,
} from "react";

type SectionProps = {
  title: string;
  icon: LucideIcon;
  children: ReactNode;
};

export function ProductDetailSection({
  title,
  icon: Icon,
  children,
}: SectionProps) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-3 sm:p-3.5">
      <div className="flex items-center gap-2 border-b border-slate-100 pb-2.5">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-slate-50 text-slate-500 ring-1 ring-inset ring-slate-200">
          <Icon
            aria-hidden="true"
            className="h-3.5 w-3.5"
          />
        </div>
        <h3 className="min-w-0 text-[10px] font-black uppercase tracking-[0.08em] text-slate-600">
          {title}
        </h3>
      </div>

      <div className="mt-3">
        {children}
      </div>
    </section>
  );
}

type FieldProps = {
  label: string;
  children: ReactNode;
  mono?: boolean;
  hint?: string;
};

export function ProductDetailField({
  label,
  children,
  mono = false,
  hint,
}: FieldProps) {
  return (
    <div className="min-w-0 border-b border-slate-100 pb-2 last:border-b-0 last:pb-0">
      <dt className="text-[9px] font-black uppercase tracking-[0.05em] text-slate-400">
        {label}
      </dt>
      <dd
        className={`mt-0.5 break-words text-[12px] font-black leading-5 text-slate-800 ${
          mono
            ? "font-mono tracking-tight"
            : ""
        }`}
      >
        {children}
      </dd>
      {hint ? (
        <p className="mt-1 text-[9px] font-semibold leading-4 text-slate-500">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
