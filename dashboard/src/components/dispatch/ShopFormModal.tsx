import { MapPin, CircleDollarSign } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { CustomSelect } from "@/components/ui/custom-select";
import type { Zone } from "@/types/dispatch";
import type { ShopFormState, ShopFinanceReadback } from "@/features/dispatch/shopForm/contract";
import { shopFormText } from "@/features/dispatch/shopForm/messages";

interface ShopFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  editingShopId: string | null;
  shopForm: ShopFormState;
  onShopFormChange: (form: ShopFormState) => void;
  zones: Zone[];
  onSave: () => void;
  onVerify: () => void;
  language: string;
  saving: boolean;
  needsVerification: boolean;
  canViewFinances: boolean;
  finance: ShopFinanceReadback | null;
  financeLoading: boolean;
  feedback: string | null;
}

export function ShopFormModal({
  isOpen, onClose, editingShopId, shopForm, onShopFormChange, zones, onSave,
  onVerify, language, saving, needsVerification, canViewFinances, finance,
  financeLoading, feedback,
}: ShopFormModalProps) {
  const edit = editingShopId !== null;
  const t = (key: Parameters<typeof shopFormText>[1]) => shopFormText(language, key);
  const money = (raw: string): string => new Intl.NumberFormat(
    language.toLowerCase().startsWith("ar") ? "ar-QA" : "en-QA",
    { minimumFractionDigits: 3, maximumFractionDigits: 3 },
  ).format(Number(raw));

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={t(edit ? "titleEdit" : "titleCreate")}
      footer={
        <div className="flex w-full gap-2">
          <button type="button" disabled={saving || needsVerification} onClick={onClose}
            className="rounded-xl px-4 py-2 font-bold text-slate-600 hover:bg-slate-100 disabled:opacity-50">
            {t("cancel")}
          </button>
          <button type="submit" form="shop-form" disabled={saving}
            className="flex-1 rounded-xl bg-[#1e87bb] px-4 py-2 font-bold text-white hover:bg-[#0f766e] disabled:opacity-50">
            {saving ? t("saving") : needsVerification ? t("refresh") : t("save")}
          </button>
        </div>
      }>
      <form id="shop-form" onSubmit={event => {
        event.preventDefault();
        if (needsVerification) onVerify(); else onSave();
      }} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <fieldset disabled={saving || needsVerification} className="contents">
        <label className="space-y-1">
          <span className="text-xs font-bold text-slate-500">{t("name")}</span>
          <input type="text" required minLength={2} maxLength={150} value={shopForm.name}
            onChange={event => onShopFormChange({ ...shopForm, name: event.target.value })}
            className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"/>
        </label>
        <label className="space-y-1">
          <span className="text-xs font-bold text-slate-500">{t("owner")}</span>
          <input type="text" maxLength={100} value={shopForm.owner}
            onChange={event => onShopFormChange({ ...shopForm, owner: event.target.value })}
            className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"/>
        </label>
        <label className="space-y-1">
          <span className="text-xs font-bold text-slate-500">{t("phone")}</span>
          <input type="tel" maxLength={20} value={shopForm.phone} dir="ltr"
            onChange={event => onShopFormChange({ ...shopForm, phone: event.target.value.replace(/[^\d+]/g, "") })}
            className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"/>
        </label>
        <div className="space-y-1">
          <span className="text-xs font-bold text-slate-500">{t("zone")}</span>
          <CustomSelect label={t("zone")} options={zones.map(z => ({ id: z.id, label: z.name }))}
            value={shopForm.zoneId} onChange={id => onShopFormChange({ ...shopForm, zoneId: id })}/>
        </div>
        <label className="space-y-1 sm:col-span-2">
          <span className="text-xs font-bold text-slate-500">{t("map")}</span>
          <span className="relative block">
            <MapPin className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"/>
            <input type="text" maxLength={500} value={shopForm.mapLink}
              onChange={event => onShopFormChange({ ...shopForm, mapLink: event.target.value })}
              className="w-full rounded-xl border border-slate-200 py-2.5 ps-9 pe-4 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"/>
          </span>
        </label>
        {edit ? (
          <section className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3 sm:col-span-2"
            aria-label={t("financeReadOnly")}>
            <p className="text-xs text-slate-600">{t("financeReadOnly")}</p>
            {canViewFinances ? financeLoading ? (
              <p role="status" className="text-xs text-slate-500">{t("financeLoading")}</p>
            ) : finance ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div><span className="block text-xs font-medium text-slate-500">{t("currentDebt")}</span>
                  <output data-testid="shop-current-debt" className="font-bold" dir="auto">{money(finance.initialDebt)}</output>
                </div>
                <div><span className="block text-xs font-medium text-slate-500">{t("maxDebt")}</span>
                  <output data-testid="shop-current-cap" className="font-bold" dir="auto">{money(finance.maxDebtLimit)}</output>
                </div>
              </div>
            ) : (
              <p role="status" className="text-xs text-slate-500">{t("financeRefreshFailed")}</p>
            ) : (
              <p className="text-xs text-slate-500">{t("financeUnavailable")}</p>
            )}
          </section>
        ) : (
          <>
            <label className="space-y-1">
              <span className="text-xs font-bold text-slate-500">{t("maxDebt")}</span>
              <span className="relative block">
                <CircleDollarSign className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"/>
                <input type="text" inputMode="decimal" required value={shopForm.maxDebtLimit}
                  onChange={event => onShopFormChange({ ...shopForm, maxDebtLimit: event.target.value })}
                  className="w-full rounded-xl border border-slate-200 py-2.5 ps-9 pe-4 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"/>
              </span>
            </label>
            <label className="space-y-1">
              <span className="text-xs font-bold text-slate-500">{t("openingDebt")}</span>
              <input type="text" inputMode="decimal" required value={shopForm.initialDebt}
                onChange={event => onShopFormChange({ ...shopForm, initialDebt: event.target.value })}
                className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"/>
            </label>
          </>
        )}
        </fieldset>
        {feedback && <p role="alert" className="text-sm font-semibold text-amber-700 sm:col-span-2">{feedback}</p>}
      </form>
    </Modal>
  );
}
