import { X } from "lucide-react";
import type { ReactNode } from "react";

export function EditorDialog({
  open,
  title,
  subtitle,
  children,
  onClose,
  footer,
}: {
  open: boolean;
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  footer?: ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="commercial-editor-overlay" dir="rtl">
      <button type="button" className="commercial-editor-backdrop" onClick={onClose} aria-label="إغلاق" />
      <section className="commercial-editor-dialog" role="dialog" aria-modal="true" aria-label={title}>
        <header className="commercial-editor-header">
          <div><h2>{title}</h2>{subtitle ? <p>{subtitle}</p> : null}</div>
          <button type="button" className="commercial-editor-close" onClick={onClose} aria-label="إغلاق النافذة"><X className="h-4 w-4" /></button>
        </header>
        <div className="commercial-editor-body custom-scrollbar">{children}</div>
        {footer ? <footer className="commercial-editor-footer">{footer}</footer> : null}
      </section>
    </div>
  );
}

export function EditorField({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <label className="commercial-editor-field"><span>{label}</span>{children}{hint ? <small>{hint}</small> : null}</label>;
}

export const editorInputClass = "commercial-editor-input";
export const editorSelectClass = "commercial-editor-input commercial-editor-select";
