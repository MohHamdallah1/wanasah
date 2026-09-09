import { Modal } from "@/components/ui/modal";

interface StocktakeStartModalProps {
  open: boolean;
  locking: boolean;
  onClose: () => void;
  onStart: () => void | Promise<void>;
}

export function StocktakeStartModal({
  open,
  locking,
  onClose,
  onStart,
}: StocktakeStartModalProps) {
  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title="إجراء أمني: بدء جرد شامل"
      maxWidth="max-w-md"
      footer={
        <div className="flex gap-3 w-full">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-bold hover:bg-slate-50"
          >
            إلغاء
          </button>
          <button
            onClick={() => void onStart()}
            disabled={locking}
            className="flex-1 px-5 py-2 bg-amber-500 hover:bg-amber-600 text-white font-bold rounded-xl shadow-md"
          >
            {locking
              ? "جارٍ البدء..."
              : "ابدأ الجرد الأعمى"}
          </button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="bg-amber-50 border-r-4 border-amber-500 p-4 rounded-l-lg">
          <p className="text-sm text-amber-800 font-bold">
            سيُقفل هذا المستودع فقط، وتؤخذ Snapshot ثابتة. العدّاد لن يرى الرصيد المتوقع أو الفرق أثناء العد.
          </p>
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
  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title="تثبيت محاولة العد"
      maxWidth="max-w-md"
      footer={
        <div className="flex gap-3 w-full">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-bold hover:bg-slate-50"
          >
            تراجع
          </button>
          <button
            onClick={() => void onSubmit()}
            disabled={submitting}
            className="flex-[1.5] px-5 py-2 bg-amber-500 hover:bg-amber-600 text-slate-900 font-black rounded-xl shadow-md"
          >
            {submitting
              ? "جاري التثبيت..."
              : "تثبيت وإنهاء العد"}
          </button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="bg-red-50 border-r-4 border-red-500 p-4 rounded-l-lg">
          <p className="text-sm text-red-800 font-bold">
            بعد التثبيت لن تستطيع تعديل هذه الأرقام. أي تصحيح لاحق سيكون Recount جديداً محفوظاً كنسخة مستقلة.
          </p>
        </div>
        <div className="space-y-2">
          <label className="text-sm font-bold text-slate-700">
            ملاحظات العد (اختياري)
          </label>
          <textarea
            value={notes}
            onChange={(event) =>
              onNotesChange(event.target.value)
            }
            maxLength={4000}
            placeholder="أي ملاحظات عن العد الفعلي..."
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-800 focus:ring-2 focus:ring-amber-500 outline-none resize-none h-24"
          />
        </div>
      </div>
    </Modal>
  );
}
