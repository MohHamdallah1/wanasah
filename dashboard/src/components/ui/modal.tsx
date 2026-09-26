import { useId } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useDialogFocusTrap } from "@/hooks/useDialogFocusTrap";

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  maxWidth?: string;
  bodyClassName?: string;
}

export function Modal({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  footer,
  maxWidth = "max-w-2xl",
  bodyClassName = "p-4 sm:p-6",
}: ModalProps) {
  const { t, i18n } = useTranslation();
  const titleId = useId();
  const dialogRef =
    useDialogFocusTrap<HTMLDivElement>(
      isOpen,
      onClose,
    );
  return (
    <AnimatePresence>
      {isOpen && (
        <div
          className="app-modal fixed inset-0 z-50 flex items-end justify-center p-2 sm:items-center sm:p-6"
          dir={i18n.dir()}
        >
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="app-modal-backdrop absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
          />
          <motion.div
            ref={dialogRef}
            tabIndex={-1}
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className={`app-modal-panel relative flex max-h-[calc(100dvh-1rem)] w-full flex-col overflow-hidden rounded-2xl bg-white shadow-2xl sm:max-h-[90vh] sm:rounded-3xl ${maxWidth}`}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
          >
            <div className="app-modal-header sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-slate-100 bg-white px-4 py-3 sm:px-6 sm:py-4">
              <div className="min-w-0">
                <h3 id={titleId} className="break-words text-base font-bold text-slate-800 sm:text-lg">{title}</h3>
                {subtitle ? (
                  <div className="mt-1 max-w-3xl text-[11px] font-semibold leading-5 text-slate-500 sm:text-xs">
                    {subtitle}
                  </div>
                ) : null}
              </div>
              <button
                onClick={onClose}
                className="shrink-0 rounded-xl p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
                aria-label={t("common.close")}
              >
                <X className="w-5 h-5" strokeWidth={2} />
              </button>
            </div>
            <div className={`app-modal-body min-h-0 flex-1 overflow-y-auto ${bodyClassName}`}>
              {children}
            </div>
            {footer && (
              <div className="app-modal-footer flex flex-col-reverse gap-2 border-t border-slate-100 bg-slate-50/50 px-4 py-3 sm:flex-row sm:justify-end sm:gap-3 sm:px-6 sm:py-4 [&>button]:w-full sm:[&>button]:w-auto">
                {footer}
              </div>
            )}
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
