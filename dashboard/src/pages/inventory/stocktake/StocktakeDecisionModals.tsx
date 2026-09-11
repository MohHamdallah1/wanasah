import { Modal } from "@/components/ui/modal";
import { absoluteQuantity, compareQuantity, formatQuantity } from "../quantity";
import type { StocktakeReview } from "./types";

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
  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title="اعتماد الجرد نهائياً"
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
            onClick={() => void onApprove()}
            disabled={busy || blocked}
            className="flex-[1.5] px-5 py-2 bg-emerald-500 hover:bg-emerald-600 disabled:bg-slate-300 text-white font-black rounded-xl shadow-md"
          >
            {busy
              ? "جاري الاعتماد..."
              : "اعتماد وترحيل الفروقات"}
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-slate-600 font-bold">
          سيتم ترحيل فروقات محاولة العد الحالية إلى الرصيد الفعلي وفك أقفال المستودع.
        </p>
        <div className="space-y-2">
          <label className="text-sm font-bold text-slate-700">
            كلمة مرور المشرف الحالي
          </label>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) =>
              onPasswordChange(event.target.value)
            }
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-emerald-500"
          />
        </div>
        <div className="space-y-2">
          <label className="text-sm font-bold text-slate-700">
            ملاحظة الاعتماد (اختياري)
          </label>
          <textarea
            value={notes}
            onChange={(event) =>
              onNotesChange(event.target.value)
            }
            maxLength={500}
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none resize-none h-20"
          />
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
  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title="تفويض Recount جديد"
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
            onClick={() => void onRecount()}
            disabled={busy}
            className="flex-[1.5] px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white font-black rounded-xl shadow-md"
          >
            {busy
              ? "جاري التفويض..."
              : "تفويض إعادة العد"}
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="bg-blue-50 border-r-4 border-blue-500 p-4 rounded-l-lg">
          <p className="text-sm text-blue-800 font-bold">
            المحاولة الحالية لن تُعدل أو تُحذف. سيُنشئ النظام محاولة عد جديدة مستقلة بسبب موثق.
          </p>
        </div>
        <div className="space-y-2">
          <label className="text-sm font-bold text-slate-700">
            سبب إعادة الجرد *
          </label>
          <textarea
            value={reason}
            onChange={(event) =>
              onReasonChange(event.target.value)
            }
            maxLength={500}
            placeholder="مثال: فرق غير مبرر ويحتاج عد مستقل..."
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none resize-none h-20"
          />
        </div>
        <div className="grid grid-cols-1 gap-3">
          <div className="space-y-2">
            <label className="text-sm font-bold text-slate-700">
              اسم المستخدم المخول *
            </label>
            <input
              type="text"
              autoComplete="username"
              value={username}
              onChange={(event) =>
                onUsernameChange(event.target.value)
              }
              maxLength={80}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-bold text-slate-700">
              كلمة مرور المستخدم المخول *
            </label>
            <input
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) =>
                onPasswordChange(event.target.value)
              }
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500"
            />
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
  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title="إلغاء جلسة الجرد"
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
            onClick={() => void onCancel()}
            disabled={busy}
            className="flex-[1.5] px-5 py-2 bg-red-500 hover:bg-red-600 text-white font-black rounded-xl shadow-md"
          >
            {busy
              ? "جاري الإلغاء..."
              : "تأكيد الإلغاء"}
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="bg-red-50 border-r-4 border-red-500 p-4 rounded-l-lg">
          <p className="text-sm text-red-800 font-bold">
            إلغاء الجلسة يفك الأقفال، لكنه لا يمسح أي محاولة عد مثبتة أو سجل رقابي سابق.
          </p>
        </div>
        <div className="space-y-2">
          <label className="text-sm font-bold text-slate-700">
            سبب الإلغاء *
          </label>
          <textarea
            value={reason}
            onChange={(event) =>
              onReasonChange(event.target.value)
            }
            maxLength={500}
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none resize-none h-20"
          />
        </div>
        <div className="space-y-2">
          <label className="text-sm font-bold text-slate-700">
            كلمة مرور المشرف الحالي *
          </label>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) =>
              onPasswordChange(event.target.value)
            }
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-red-500"
          />
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

export function StocktakeVarianceModal({
  open,
  review,
  onClose,
}: StocktakeVarianceModalProps) {
  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title="تفاصيل الفروقات المثبتة"
      maxWidth="max-w-lg"
      footer={
        <button
          onClick={onClose}
          className="w-full px-4 py-2 bg-slate-100 text-slate-700 font-bold rounded-xl hover:bg-slate-200 transition-colors"
        >
          إغلاق
        </button>
      }
    >
      <div className="max-h-[60vh] overflow-y-auto custom-scrollbar pr-2 space-y-2">
        {review?.lines
          .filter(
            (line) =>
              compareQuantity(line.variance_quantity, "0") !== 0
          )
          .map((line) => (
            <div
              key={line.attempt_line_id}
              className="flex items-center justify-between p-3 bg-slate-50 border border-slate-100 rounded-xl"
            >
              <div className="flex flex-col">
                <span className="font-bold text-slate-800 text-sm">
                  {line.product_name}
                </span>
                <span className="text-[11px] text-slate-400">
                  {line.batch_number || "بدون دفعة"}
                </span>
              </div>
              <span
                className={`font-black text-sm px-3 py-1 rounded-lg ${
                  compareQuantity(line.variance_quantity, "0") > 0
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-red-100 text-red-700"
                }`}
                dir="ltr"
              >
                {compareQuantity(line.variance_quantity, "0") > 0
                  ? "+ "
                  : "- "}
                {formatQuantity(absoluteQuantity(line.variance_quantity), line.base_uom_name)}
              </span>
            </div>
          ))}
      </div>
    </Modal>
  );
}
