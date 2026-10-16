import { Modal } from "@/components/ui/modal";
import { useStocktakeCopy } from "./copy";

interface StocktakeStartModalProps {
  open: boolean;
  locking: boolean;
  onClose: () => void;
  onStart: () => void | Promise<void>;
}

export function StocktakeStartModal({ open, locking, onClose, onStart }: StocktakeStartModalProps) {
  const { copy, dir } = useStocktakeCopy();
  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title={copy.startModal.title}
      maxWidth="max-w-md"
      footer={
        <div className="flex gap-3 w-full" dir={dir}>
          <button type="button" onClick={onClose} className="flex-1 px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-bold hover:bg-slate-50">
            {copy.startModal.cancel}
          </button>
          <button
            type="button"
            autoFocus
            onClick={() => void onStart()}
            disabled={locking}
            className="flex-1 px-5 py-2 bg-amber-500 hover:bg-amber-600 disabled:bg-slate-300 text-white font-bold rounded-xl shadow-md"
          >
            {locking ? copy.startModal.busy : copy.startModal.submit}
          </button>
        </div>
      }
    >
      <div dir={dir} className="flex flex-col gap-4">
        <div className="bg-amber-50 border-s-4 border-amber-500 p-4 rounded-lg">
          <p className="text-sm text-amber-800 font-bold">{copy.startModal.body}</p>
        </div>
      </div>
    </Modal>
  );
}

interface StocktakeSubmitModalProps {
  open: boolean;
  submitting: boolean;
  notes: string;
  onNotesChange: (value: string) => void;
  onClose: () => void;
  onSubmit: () => void | Promise<void>;
}

export function StocktakeSubmitModal({
  open,
  submitting,
  notes,
  onNotesChange,
  onClose,
  onSubmit,
}: StocktakeSubmitModalProps) {
  const { copy, dir } = useStocktakeCopy();
  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title={copy.submitModal.title}
      maxWidth="max-w-md"
      footer={
        <div className="flex gap-3 w-full" dir={dir}>
          <button type="button" onClick={onClose} className="flex-1 px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-bold hover:bg-slate-50">
            {copy.submitModal.back}
          </button>
          <button type="button" onClick={() => void onSubmit()} disabled={submitting} className="flex-[1.5] px-5 py-2 bg-amber-500 hover:bg-amber-600 disabled:bg-slate-300 text-slate-900 font-black rounded-xl shadow-md">
            {submitting ? copy.submitModal.busy : copy.submitModal.submit}
          </button>
        </div>
      }
    >
      <div dir={dir} className="flex flex-col gap-4">
        <div className="bg-red-50 border-s-4 border-red-500 p-4 rounded-lg">
          <p className="text-sm text-red-800 font-bold">{copy.submitModal.body}</p>
        </div>
        <div className="space-y-2">
          <label className="text-sm font-bold text-slate-700">{copy.submitModal.notes}</label>
          <textarea
            autoFocus
            value={notes}
            onChange={(event) => onNotesChange(event.target.value)}
            maxLength={4000}
            placeholder={copy.submitModal.placeholder}
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-800 focus:ring-2 focus:ring-amber-500 outline-none resize-none h-24"
          />
        </div>
      </div>
    </Modal>
  );
}
