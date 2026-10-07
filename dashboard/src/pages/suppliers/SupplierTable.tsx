import { useTranslation } from "react-i18next";
import type { Supplier } from "@/features/suppliers/contracts";

export function SupplierTable({ items, manage, disabled, onEdit, onState }: {
  items: Supplier[]; manage: boolean; disabled: boolean; onEdit: (row: Supplier) => void; onState: (row: Supplier) => void;
}) {
  const { t } = useTranslation();
  return <div className="overflow-x-auto rounded-xl border bg-card text-card-foreground">
    <table className="w-full min-w-[650px] text-sm">
      <thead><tr>{["name", "contact_person", "phone", "email", "status", "actions"].map(field =>
        <th key={field} scope="col" className="p-3 text-start">{t(`suppliers.fields.${field}`)}</th>)}</tr></thead>
      <tbody>{items.map(row => <tr key={row.id} className="border-t">
        <td className="p-3"><strong>{row.name}</strong>{row.code ? <p className="text-muted-foreground">{row.code}</p> : null}</td>
        <td className="p-3">{row.contact_person ?? "—"}</td><td className="p-3">{row.phone ?? "—"}</td><td className="p-3">{row.email ?? "—"}</td>
        <td className="p-3">{t(row.is_active ? "suppliers.active" : "suppliers.inactive")}</td>
        <td className="p-3">{manage ? <div className="flex gap-3">
          <button type="button" disabled={disabled} onClick={() => onEdit(row)} aria-label={t("suppliers.editNamed", { name: row.name })}>{t("common.edit")}</button>
          <button type="button" disabled={disabled} onClick={() => onState(row)}>{t(row.is_active ? "suppliers.deactivate" : "suppliers.activate")}</button>
        </div> : null}</td>
      </tr>)}</tbody>
    </table>
  </div>;
}
