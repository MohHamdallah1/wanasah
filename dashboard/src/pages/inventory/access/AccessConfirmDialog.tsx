import { useEffect, useRef } from 'react';
import type { InventoryAccessCopy } from './copy';

interface AccessConfirmDialogProps {
  open: boolean;
  copy: InventoryAccessCopy;
  busy: boolean;
  returnFocusTo: HTMLElement | null;
  onCancel: () => void;
  onConfirm: () => void;
}

export function AccessConfirmDialog({
  open,
  copy,
  busy,
  returnFocusTo,
  onCancel,
  onConfirm,
}: AccessConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (returnFocusTo) returnFocusRef.current = returnFocusTo;
    if (open) {
      cancelRef.current?.focus();
      return;
    }
    returnFocusRef.current?.focus();
  }, [open, returnFocusTo]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/30 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="inventory-access-revoke-title"
        className="glass-card w-full max-w-md rounded-2xl p-5 space-y-4"
        onKeyDown={event => {
          if (event.key === 'Escape' && !busy) {
            event.preventDefault();
            onCancel();
            return;
          }
          if (event.key !== 'Tab') return;
          const focusables = dialogRef.current?.querySelectorAll<HTMLElement>(
            'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
          );
          if (!focusables?.length) return;
          const first = focusables[0];
          const last = focusables[focusables.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }}
      >
        <div>
          <h3 id="inventory-access-revoke-title" className="font-black text-lg text-slate-900">
            {copy.confirmRevokeTitle}
          </h3>
          <p className="mt-2 text-sm leading-6 text-slate-600">{copy.confirmRevokeBody}</p>
        </div>
        <div className="inventory-action-row">
          <button ref={cancelRef} type="button" disabled={busy} onClick={onCancel} className="inventory-secondary-action">
            {copy.cancel}
          </button>
          <button type="button" disabled={busy} onClick={onConfirm} className="inventory-primary-action">
            {copy.confirmRevoke}
          </button>
        </div>
      </div>
    </div>
  );
}
