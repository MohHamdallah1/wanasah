import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import { emptySupplier, type SupplierDetails, type Supplier } from "@/features/suppliers/contracts";

const fields = ["name", "code", "contact_person", "phone", "email", "address", "notes"] as const;
export function SupplierEditor({ supplier, storageKey, busy, blocked, error, blockedReason, onRetry, onSave, onClose }: {
  supplier: Supplier | null; storageKey: string; busy: boolean; blocked: boolean;
  onSave: (details: SupplierDetails) => Promise<boolean>; onClose: () => void;
  error?: string | null; blockedReason?: string; onRetry?: () => Promise<boolean>;
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
    setDetails(next); localStorage.setItem(storageKey, JSON.stringify(next));
  };
  return <Modal isOpen onClose={() => { if (!busy) onClose(); }} title={t(supplier ? "suppliers.edit" : "suppliers.add")}>
    <form className="space-y-3" onSubmit={async event => {
      event.preventDefault();
      if (busy || blocked) return;
      const clean = Object.fromEntries(fields.map(field => [field, details[field]?.trim() || (field === "name" ? "" : null)])) as SupplierDetails;
      if (await onSave(clean)) { localStorage.removeItem(storageKey); onClose(); }
    }}>
      {error ? <p role="alert" className="text-destructive">{error}</p> : null}
      {blockedReason ? <div role="status"><p>{blockedReason}</p>{onRetry ? <button type="button" disabled={busy} onClick={async () => {
        if (await onRetry()) { localStorage.removeItem(storageKey); onClose(); }
      }}>{t("common.retry")}</button> : null}</div> : null}
      <fieldset disabled={busy || blocked} className="grid gap-3 sm:grid-cols-2">
        {fields.map(field => <label key={field} className={field === "notes" || field === "address" ? "sm:col-span-2" : ""}>
          <span className="block text-sm font-medium">{t(`suppliers.fields.${field}`)}</span>
          {field === "notes" ? <textarea value={details[field] ?? ""} maxLength={4000} onChange={event => update(field, event.target.value)} className="mt-1 w-full rounded-lg border bg-background p-2 text-foreground" />
            : <input autoFocus={field === "name"} required={field === "name"} type={field === "email" ? "email" : field === "phone" ? "tel" : "text"}
              maxLength={{ name: 300, code: 50, contact_person: 150, phone: 50, email: 254, address: 1000 }[field]}
              value={details[field] ?? ""} onChange={event => update(field, event.target.value)} className="mt-1 w-full rounded-lg border bg-background p-2 text-foreground focus-visible:ring-2 focus-visible:ring-ring" />}
        </label>)}
      </fieldset>
      <div className="flex justify-end gap-3">
        <button type="button" disabled={busy} onClick={onClose}>{t("common.cancel")}</button>
        <button type="submit" disabled={busy || blocked} className="rounded-lg bg-primary px-4 py-2 text-primary-foreground">{t(busy ? "common.saving" : "common.save")}</button>
      </div>
    </form>
  </Modal>;
}
