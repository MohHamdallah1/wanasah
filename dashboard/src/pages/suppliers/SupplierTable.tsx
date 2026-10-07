import { useEffect, useState } from "react";
import { CheckCircle2, CircleOff, Mail, Pencil, Phone, UserRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Supplier } from "@/features/suppliers/contracts";

function supplierInitial(name: string) {
  return name.trim().charAt(0).toUpperCase() || "•";
}

function useDesktopSupplierLayout() {
  const query = "(min-width: 768px)";
  const read = () => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return true;
    return window.matchMedia(query).matches;
  };
  const [desktop, setDesktop] = useState(read);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    const sync = () => setDesktop(media.matches);
    media.addEventListener?.("change", sync);
    return () => media.removeEventListener?.("change", sync);
  }, []);

  return desktop;
}

export function SupplierTable({ items, manage, disabled, onEdit, onState }: {
  items: Supplier[];
  manage: boolean;
  disabled: boolean;
  onEdit: (row: Supplier) => void;
  onState: (row: Supplier) => void;
}) {
  const { t } = useTranslation();
  const desktop = useDesktopSupplierLayout();

  if (desktop) {
    return <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-sm">
        <thead className="sticky top-0 z-10 bg-slate-50/[0.94] text-[11px] font-black text-slate-500 backdrop-blur-xl">
          <tr>
            {["name", "contact_person", "phone", "email", "status", "actions"].map(field =>
              <th key={field} scope="col" className="px-4 py-3 text-start tracking-wide">{t(`suppliers.fields.${field}`)}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200/[0.65]">
          {items.map(row => <tr key={row.id} className="group transition hover:bg-white/80">
            <td className="px-4 py-3.5">
              <div className="flex min-w-0 items-center gap-3">
                <div className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl border border-white bg-gradient-to-br from-cyan-50 to-slate-100 text-sm font-black text-slate-700 shadow-sm">{supplierInitial(row.name)}</div>
                <div className="min-w-0">
                  <strong className="block truncate font-black text-slate-900">{row.name}</strong>
                  <span className="mt-0.5 block truncate text-[11px] font-bold text-slate-400">{row.code || "—"}</span>
                </div>
              </div>
            </td>
            <td className="px-4 py-3.5 font-semibold text-slate-600">{row.contact_person ?? "—"}</td>
            <td className="px-4 py-3.5"><span className="inline-flex items-center gap-1.5 font-semibold text-slate-600"><Phone className="h-3.5 w-3.5 text-slate-400" />{row.phone ?? "—"}</span></td>
            <td className="px-4 py-3.5"><span className="inline-flex max-w-[240px] items-center gap-1.5 truncate font-semibold text-slate-600"><Mail className="h-3.5 w-3.5 shrink-0 text-slate-400" /><span className="truncate">{row.email ?? "—"}</span></span></td>
            <td className="px-4 py-3.5">
              <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-black ${row.is_active ? "border-emerald-200/80 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-slate-100 text-slate-500"}`}>
                <span className={`h-1.5 w-1.5 rounded-full ${row.is_active ? "bg-emerald-500" : "bg-slate-400"}`} />
                {t(row.is_active ? "suppliers.active" : "suppliers.inactive")}
              </span>
            </td>
            <td className="px-4 py-3.5">
              {manage ? <div className="flex items-center gap-1.5 opacity-80 transition group-hover:opacity-100">
                <button type="button" disabled={disabled} onClick={() => onEdit(row)} aria-label={t("suppliers.editNamed", { name: row.name })} title={t("common.edit")}
                  className="grid h-9 w-9 place-items-center rounded-xl border border-slate-200/80 bg-white text-slate-500 shadow-sm transition hover:border-cyan-200 hover:bg-cyan-50 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-40"><Pencil className="h-3.5 w-3.5" /></button>
                <button type="button" disabled={disabled} onClick={() => onState(row)} title={t(row.is_active ? "suppliers.deactivate" : "suppliers.activate")}
                  aria-label={t(row.is_active ? "suppliers.deactivate" : "suppliers.activate")}
                  className={`grid h-9 w-9 place-items-center rounded-xl border bg-white shadow-sm transition disabled:cursor-not-allowed disabled:opacity-40 ${row.is_active ? "border-slate-200/80 text-slate-400 hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600" : "border-emerald-200 text-emerald-600 hover:bg-emerald-50"}`}>
                  {row.is_active ? <CircleOff className="h-3.5 w-3.5" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                </button>
              </div> : null}
            </td>
          </tr>)}
        </tbody>
      </table>
    </div>;
  }

  return <div className="grid gap-2 p-2">
    {items.map(row => <article key={row.id} className="rounded-[20px] border border-white bg-white/[0.76] p-3.5 shadow-sm">
      <div className="flex items-start gap-3">
        <div className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-cyan-50 to-slate-100 font-black text-slate-700 shadow-sm">{supplierInitial(row.name)}</div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0"><h3 className="truncate font-black text-slate-900">{row.name}</h3><p className="text-[11px] font-bold text-slate-400">{row.code || "—"}</p></div>
            <span className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-black ${row.is_active ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{t(row.is_active ? "suppliers.active" : "suppliers.inactive")}</span>
          </div>
          <div className="mt-3 grid gap-1.5 text-xs font-semibold text-slate-500">
            <span className="inline-flex items-center gap-2"><UserRound className="h-3.5 w-3.5 text-slate-400" />{row.contact_person ?? "—"}</span>
            <span className="inline-flex items-center gap-2"><Phone className="h-3.5 w-3.5 text-slate-400" />{row.phone ?? "—"}</span>
            <span className="inline-flex min-w-0 items-center gap-2"><Mail className="h-3.5 w-3.5 shrink-0 text-slate-400" /><span className="truncate">{row.email ?? "—"}</span></span>
          </div>
        </div>
      </div>
      {manage ? <div className="mt-3 flex gap-2 border-t border-slate-100 pt-3">
        <button type="button" disabled={disabled} onClick={() => onEdit(row)} className="inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-xl bg-slate-100 text-xs font-black text-slate-700 disabled:opacity-40"><Pencil className="h-3.5 w-3.5" />{t("common.edit")}</button>
        <button type="button" disabled={disabled} onClick={() => onState(row)} className={`inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-xl text-xs font-black disabled:opacity-40 ${row.is_active ? "bg-rose-50 text-rose-600" : "bg-emerald-50 text-emerald-700"}`}>{row.is_active ? <CircleOff className="h-3.5 w-3.5" /> : <CheckCircle2 className="h-3.5 w-3.5" />}{t(row.is_active ? "suppliers.deactivate" : "suppliers.activate")}</button>
      </div> : null}
    </article>)}
  </div>;
}
