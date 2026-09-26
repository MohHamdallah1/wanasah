import type {
  ReactNode,
} from "react";

type SectionProps = {
  title: string;
  children: ReactNode;
};

export function ProductDetailSection({
  title,
  children,
}: SectionProps) {
  return (
    <section className="border-b border-slate-100 px-4 py-4 last:border-b-0 sm:px-5">
      <h3 className="text-[11px] font-black uppercase tracking-[0.08em] text-slate-400">
        {title}
      </h3>
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
    <div className="min-w-0">
      <dt className="text-[10px] font-black text-slate-400">
        {label}
      </dt>
      <dd
        className={`mt-1 break-words text-[13px] font-black leading-5 text-slate-800 ${
          mono
            ? "font-mono"
            : ""
        }`}
      >
        {children}
      </dd>
      {hint ? (
        <p className="mt-1 text-[10px] font-semibold leading-4 text-slate-500">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
