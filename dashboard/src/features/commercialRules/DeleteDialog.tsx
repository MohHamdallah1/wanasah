import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { EditorDialog, editorInputClass } from "./EditorDialog";

export function DeleteDialog({ open, title, message, pending, onClose, onConfirm }: {
  open: boolean; title: string; message: string; pending: boolean; onClose: () => void; onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  useEffect(() => { if (open) setReason(""); }, [open]);
  return (
    <EditorDialog open={open} onClose={onClose} title={title} subtitle="الحذف يخضع لقواعد التاريخ والاعتماد في السيرفر؛ لا يوجد bypass من الواجهة."
      footer={<><button className="commercial-editor-button commercial-editor-button--ghost" onClick={onClose}>إلغاء</button><button className="commercial-editor-button commercial-editor-button--danger" disabled={pending} onClick={() => { const clean = reason.trim(); if (clean.length < 3) { toast.error("سبب الحذف يجب أن يكون 3 أحرف على الأقل."); return; } onConfirm(clean); }}>{pending ? "جاري التنفيذ..." : "تأكيد الحذف"}</button></>}>
      <div className="commercial-editor-warning"><AlertTriangle className="h-5 w-5" /><p>{message}</p></div>
      <label className="commercial-editor-field"><span>سبب الحذف</span><textarea className={`${editorInputClass} min-h-24 resize-y`} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} /></label>
    </EditorDialog>
  );
}
