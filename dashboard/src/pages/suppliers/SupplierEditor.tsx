import { Building2, Hash, Mail, MapPin, Phone, Save, StickyNote, UserRound } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import { emptySupplier, type SupplierDetails, type Supplier } from "@/features/suppliers/contracts";

const fields = ["name", "code", "contact_person", "phone", "email", "address", "notes"] as const;

export function SupplierEditor({ supplier, storageKey, busy, blocked, error, blockedReason, onRetry, onSave, onClose }: {
  supplier: Supplier | null;
  storageKey: string;
  busy: boolean;
  blocked: boolean;
  onSave: (details: SupplierDetails) => Promise<boolean>;
  onClose: () => void;
  error?: string | null;
  blockedReason?: string;
  onRetry?: () => Promise<boolean>;
}) {
  const { t } = useTranslation();
  const [details, setDetails] = useState<SupplierDetails>(() => {
    const raw = localStorage.getItem(storageKey);
    if (raw) {
      try {
        const saved = JSON.parse(raw);
        if (saved && fields.every(field => saved[field] === null || typeof saved[field] === "string")) return saved;
      } catch { /* Invalid local draft is never business authority. */ }
    }
    return supplier ? Object.fromEntries(fields.map(field => [field, supplier[field]])) as SupplierDetails : emptySupplier;
  });

  const update = (field: keyof SupplierDetails, value: string) => {
    const next = { ...details, [field]: value || null };
    setDetails(next);
    localStorage.setItem(storageKey, JSON.stringify(next));
  };

  const inputClass = "mt-1.5 h-11 w-full rounded-2xl border border-slate-200/80 bg-white/[0.85] px-3.5 text-sm font-semibold text-slate-800 outline-none transition placeholder:text-slate-300 focus:border-cyan-300 focus:ring-4 focus:ring-cyan-100/60 disabled:opacity-60";
  const labelClass = "text-xs font-black text-slate-600";
  const fieldRequirement = (required: boolean) => <span aria-hidden="true" className={`text-[10px] font-bold ${required ? "text-rose-500" : "text-slate-400"}`}>{t(required ? "suppliers.required" : "suppliers.optional")}</span>;

  return <Modal isOpen onClose={() => { if (!busy) onClose(); }} title={t(supplier ? "suppliers.edit" : "suppliers.add")}>
    <form className="space-y-4" onSubmit={async event => {
      event.preventDefault();
      if (busy || blocked) return;
      const clean = Object.fromEntries(fields.map(field => [field, details[field]?.trim() || (field === "name" ? "" : null)])) as SupplierDetails;
      if (!clean.name || !clean.phone || !clean.address) return;
      if (await onSave(clean)) { localStorage.removeItem(storageKey); onClose(); }
    }}>
      {error ? <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{error}</div> : null}
      {blockedReason ? <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-bold text-amber-800">
        <span>{blockedReason}</span>{onRetry ? <button type="button" disabled={busy} onClick={async () => { if (await onRetry()) { localStorage.removeItem(storageKey); onClose(); } }} className="rounded-xl bg-white px-3 py-2 text-xs font-black shadow-sm">{t("common.retry")}</button> : null}
      </div> : null}

      <fieldset disabled={busy || blocked} className="grid gap-3 sm:grid-cols-2">
        <label className={labelClass}>
          <span className="inline-flex items-center gap-1.5"><Building2 className="h-3.5 w-3.5 text-slate-400" />{t("suppliers.fields.name")}{fieldRequirement(true)}</span>
          <input autoFocus required autoComplete="organization" maxLength={300} value={details.name ?? ""} onChange={event => update("name", event.target.value)} className={inputClass} />
        </label>
        <label className={labelClass}>
          <span className="inline-flex items-center gap-1.5"><Hash className="h-3.5 w-3.5 text-slate-400" />{t("suppliers.fields.code")}{fieldRequirement(false)}</span>
          <input autoComplete="off" maxLength={50} value={details.code ?? ""} onChange={event => update("code", event.target.value)} className={inputClass} />
        </label>
        <label className={labelClass}>
          <span className="inline-flex items-center gap-1.5"><UserRound className="h-3.5 w-3.5 text-slate-400" />{t("suppliers.fields.contact_person")}{fieldRequirement(false)}</span>
          <input autoComplete="name" maxLength={150} value={details.contact_person ?? ""} onChange={event => update("contact_person", event.target.value)} className={inputClass} />
        </label>
        <label className={labelClass}>
          <span className="inline-flex items-center gap-1.5"><Phone className="h-3.5 w-3.5 text-slate-400" />{t("suppliers.fields.phone")}{fieldRequirement(true)}</span>
          <input type="tel" required autoComplete="tel" maxLength={50} value={details.phone ?? ""} onChange={event => update("phone", event.target.value)} className={inputClass} dir="ltr" />
        </label>
        <label className="sm:col-span-2 text-xs font-black text-slate-600">
          <span className="inline-flex items-center gap-1.5"><Mail className="h-3.5 w-3.5 text-slate-400" />{t("suppliers.fields.email")}{fieldRequirement(false)}</span>
          <input type="email" autoComplete="email" maxLength={254} value={details.email ?? ""} onChange={event => update("email", event.target.value)} className={inputClass} dir="ltr" />
        </label>
        <label className="sm:col-span-2 text-xs font-black text-slate-600">
          <span className="inline-flex items-center gap-1.5"><MapPin className="h-3.5 w-3.5 text-slate-400" />{t("suppliers.fields.address")}{fieldRequirement(true)}</span>
          <input required autoComplete="street-address" maxLength={1000} value={details.address ?? ""} onChange={event => update("address", event.target.value)} className={inputClass} />
        </label>
        <label className="sm:col-span-2 text-xs font-black text-slate-600">
          <span className="inline-flex items-center gap-1.5"><StickyNote className="h-3.5 w-3.5 text-slate-400" />{t("suppliers.fields.notes")}{fieldRequirement(false)}</span>
          <textarea value={details.notes ?? ""} maxLength={4000} rows={3} onChange={event => update("notes", event.target.value)}
            className="mt-1.5 w-full resize-none rounded-2xl border border-slate-200/80 bg-white/[0.85] px-3.5 py-3 text-sm font-semibold text-slate-800 outline-none transition focus:border-cyan-300 focus:ring-4 focus:ring-cyan-100/60 disabled:opacity-60" />
        </label>
      </fieldset>

      <div className="flex items-center justify-end gap-2 border-t border-slate-200/70 pt-3">
        <button type="button" disabled={busy} onClick={onClose} className="h-10 rounded-xl px-4 text-sm font-black text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 disabled:opacity-50">{t("common.cancel")}</button>
        <button type="submit" disabled={busy || blocked} className="inline-flex h-10 items-center gap-2 rounded-xl bg-slate-900 px-5 text-sm font-black text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"><Save className="h-4 w-4" />{t(busy ? "common.saving" : "common.save")}</button>
      </div>
    </form>
  </Modal>;
}
