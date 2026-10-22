import { Modal } from "@/components/ui/modal";
import { useTranslation } from "react-i18next";
import type { KeyboardEvent } from "react";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import { absoluteQuantity, compareQuantity, formatQuantity } from "../quantity";
import { useStocktakeCopy } from "./copy";
import { useStocktakeUiCopy } from "./uiCopy";
import type { StocktakeReview } from "./types";

const submitOnInputEnter = (
  event: KeyboardEvent<HTMLElement>,
  submit: () => void | Promise<void>,
  disabled: boolean,
) => {
  const target = event.target as HTMLElement;
  if (event.key !== "Enter" || disabled || target.tagName !== "INPUT") return;
  event.preventDefault();
  void submit();
};

interface StocktakeApproveModalProps {
  open: boolean;
  busy: boolean;
  blocked: boolean;
  password: string;
  notes: string;
  onPasswordChange: (value: string) => void;
  onNotesChange: (value: string) => void;
  onClose: () => void;
  onApprove: () => void | Promise<void>;
}

export function StocktakeApproveModal({
  open,
  busy,
  blocked,
  password,
  notes,
  onPasswordChange,
  onNotesChange,
  onClose,
  onApprove,
}: StocktakeApproveModalProps) {
  const { copy, dir } = useStocktakeCopy();
  const disabled = busy || blocked || !password;
  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title={copy.approveModal.title}
      maxWidth="max-w-md"
      footer={
        <div className="flex gap-3 w-full" dir={dir}>
          <button type="button" onClick={onClose} className="flex-1 px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-bold hover:bg-slate-50">{copy.approveModal.back}</button>
          <button type="button" onClick={() => void onApprove()} disabled={disabled} className="flex-[1.5] px-5 py-2 bg-emerald-500 hover:bg-emerald-600 disabled:bg-slate-300 text-white font-black rounded-xl shadow-md">
            {busy ? copy.approveModal.busy : copy.approveModal.submit}
          </button>
        </div>
      }
    >
      <div dir={dir} className="space-y-4" onKeyDown={(event) => submitOnInputEnter(event, onApprove, disabled)}>
        <p className="text-sm text-slate-600 font-bold">{copy.approveModal.body}</p>
        <div className="space-y-2">
          <label className="text-sm font-bold text-slate-700">{copy.approveModal.password}</label>
          <input
            autoFocus
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => onPasswordChange(event.target.value)}
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-emerald-500"
          />
        </div>
        <div className="space-y-2">
          <label className="text-sm font-bold text-slate-700">{copy.approveModal.notes}</label>
          <textarea value={notes} onChange={(event) => onNotesChange(event.target.value)} maxLength={500} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none resize-none h-20" />
        </div>
      </div>
    </Modal>
  );
}

interface StocktakeRecountModalProps {
  open: boolean;
  busy: boolean;
  reason: string;
  username: string;
  password: string;
  onReasonChange: (value: string) => void;
  onUsernameChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onClose: () => void;
  onRecount: () => void | Promise<void>;
}

export function StocktakeRecountModal({
  open,
  busy,
  reason,
  username,
  password,
  onReasonChange,
  onUsernameChange,
  onPasswordChange,
  onClose,
  onRecount,
}: StocktakeRecountModalProps) {
  const { copy, dir } = useStocktakeCopy();
  const disabled = busy || reason.trim().length < 5 || !username.trim() || !password;
  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title={copy.recountModal.title}
      maxWidth="max-w-md"
      footer={
        <div className="flex gap-3 w-full" dir={dir}>
          <button type="button" onClick={onClose} className="flex-1 px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-bold hover:bg-slate-50">{copy.recountModal.back}</button>
          <button type="button" onClick={() => void onRecount()} disabled={disabled} className="flex-[1.5] px-5 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300 text-white font-black rounded-xl shadow-md">
            {busy ? copy.recountModal.busy : copy.recountModal.submit}
          </button>
        </div>
      }
    >
      <div dir={dir} className="space-y-4" onKeyDown={(event) => submitOnInputEnter(event, onRecount, disabled)}>
        <div className="bg-blue-50 border-s-4 border-blue-500 p-4 rounded-lg"><p className="text-sm text-blue-800 font-bold">{copy.recountModal.body}</p></div>
        <div className="space-y-2">
          <label className="text-sm font-bold text-slate-700">{copy.recountModal.reason}</label>
          <textarea autoFocus value={reason} onChange={(event) => onReasonChange(event.target.value)} maxLength={500} placeholder={copy.recountModal.reasonPlaceholder} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none resize-none h-20" />
        </div>
        <div className="grid grid-cols-1 gap-3">
          <div className="space-y-2">
            <label className="text-sm font-bold text-slate-700">{copy.recountModal.username}</label>
            <input type="text" autoComplete="username" value={username} onChange={(event) => onUsernameChange(event.target.value)} maxLength={80} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-bold text-slate-700">{copy.recountModal.password}</label>
            <input type="password" autoComplete="new-password" value={password} onChange={(event) => onPasswordChange(event.target.value)} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>
      </div>
    </Modal>
  );
}

interface StocktakeCancelModalProps {
  open: boolean;
  busy: boolean;
  reason: string;
  password: string;
  onReasonChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onClose: () => void;
  onCancel: () => void | Promise<void>;
}

export function StocktakeCancelModal({
  open,
  busy,
  reason,
  password,
  onReasonChange,
  onPasswordChange,
  onClose,
  onCancel,
}: StocktakeCancelModalProps) {
  const { copy, dir } = useStocktakeCopy();
  const disabled = busy || reason.trim().length < 5 || !password;
  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title={copy.cancelModal.title}
      maxWidth="max-w-md"
      footer={
        <div className="flex gap-3 w-full" dir={dir}>
          <button type="button" onClick={onClose} className="flex-1 px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-bold hover:bg-slate-50">{copy.cancelModal.back}</button>
          <button type="button" onClick={() => void onCancel()} disabled={disabled} className="flex-[1.5] px-5 py-2 bg-red-500 hover:bg-red-600 disabled:bg-slate-300 text-white font-black rounded-xl shadow-md">
            {busy ? copy.cancelModal.busy : copy.cancelModal.submit}
          </button>
        </div>
      }
    >
      <div dir={dir} className="space-y-4" onKeyDown={(event) => submitOnInputEnter(event, onCancel, disabled)}>
        <div className="bg-red-50 border-s-4 border-red-500 p-4 rounded-lg"><p className="text-sm text-red-800 font-bold">{copy.cancelModal.body}</p></div>
        <div className="space-y-2">
          <label className="text-sm font-bold text-slate-700">{copy.cancelModal.reason}</label>
          <textarea autoFocus value={reason} onChange={(event) => onReasonChange(event.target.value)} maxLength={500} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none resize-none h-20" />
        </div>
        <div className="space-y-2">
          <label className="text-sm font-bold text-slate-700">{copy.cancelModal.password}</label>
          <input type="password" autoComplete="current-password" value={password} onChange={(event) => onPasswordChange(event.target.value)} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-red-500" />
        </div>
      </div>
    </Modal>
  );
}

interface StocktakeVarianceModalProps {
  open: boolean;
  review: StocktakeReview | null;
  onClose: () => void;
}

export function StocktakeVarianceModal({ open, review, onClose }: StocktakeVarianceModalProps) {
  const { t } = useTranslation();
  const { copy, dir } = useStocktakeCopy();
  const { copy: uiCopy } = useStocktakeUiCopy();
  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title={copy.varianceModal.title}
      maxWidth="max-w-lg"
      footer={<button type="button" autoFocus onClick={onClose} className="w-full px-4 py-2 bg-slate-100 text-slate-700 font-bold rounded-xl hover:bg-slate-200 transition-colors">{copy.varianceModal.close}</button>}
    >
      <div dir={dir} className="max-h-[60vh] overflow-y-auto custom-scrollbar pe-2 space-y-2">
        {review?.lines.filter((line) => compareQuantity(line.variance_quantity, "0") !== 0).map((line) => (
          <div key={line.attempt_line_id} className="flex items-center justify-between gap-3 p-3 bg-slate-50 border border-slate-100 rounded-xl">
            <div className="flex flex-col min-w-0">
              <span className="font-bold text-slate-800 text-sm truncate">{line.product_name}</span>
              <span className="text-[11px] text-slate-400">{formatPublicBatchNumber(line.batch_number, t("inventoryLive.noLotSupplied"))}</span>
              <span className="text-[11px] font-bold text-slate-500">{uiCopy.review.stockStatus}: {uiCopy.stockStatuses[line.stock_status]}</span>
            </div>
            <span className={`font-black text-sm px-3 py-1 rounded-lg ${compareQuantity(line.variance_quantity, "0") > 0 ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}`} dir="ltr">
              {compareQuantity(line.variance_quantity, "0") > 0 ? "+ " : "- "}{formatQuantity(absoluteQuantity(line.variance_quantity), line.base_uom_name)}
            </span>
          </div>
        ))}
      </div>
    </Modal>
  );
}
