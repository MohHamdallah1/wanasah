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
    <section className="group border-b border-slate-100 px-4 py-4 last:border-b-0 sm:px-5 sm:py-5">
      <div className="grid grid-cols-[36px_minmax(0,1fr)] gap-3 sm:grid-cols-[40px_minmax(0,1fr)] sm:gap-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-500 transition-colors group-hover:border-amber-200 group-hover:bg-amber-50 group-hover:text-amber-700 sm:h-10 sm:w-10">
          <Icon
            aria-hidden="true"
            className="h-4 w-4"
          />
        </div>

        <div className="min-w-0 pt-0.5">
          <div className="flex items-center gap-3">
            <h3 className="shrink-0 text-[10px] font-black uppercase tracking-[0.1em] text-slate-500">
              {title}
            </h3>
            <span
              aria-hidden="true"
              className="h-px min-w-5 flex-1 bg-slate-100"
            />
          </div>

          <div className="mt-3.5">
            {children}
          </div>
        </div>
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
    <div className="relative min-w-0 border-s border-slate-200 ps-3">
      <dt className="text-[9px] font-black uppercase tracking-[0.06em] text-slate-400">
        {label}
      </dt>
      <dd
        className={`mt-1 break-words text-[13px] font-black leading-5 text-slate-800 ${
          mono
            ? "font-mono tracking-tight"
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
