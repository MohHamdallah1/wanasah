import { useRef } from "react";
import type { TFunction } from "i18next";
import { TriangleAlert } from "lucide-react";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { apiErrorMessage } from "@/lib/apiErrors";
import type { LedgerAdjustmentController } from "./useLedgerAdjustment";
import { ledgerText } from "./ledgerI18n";

interface Props {
  t: TFunction;
  language: string;
  controller: LedgerAdjustmentController;
  onChanged: () => void | Promise<void>;
}

export function LedgerAdjustmentModal({ t, language, controller, onChanged }: Props) {
  const quantityRef = useRef<HTMLInputElement>(null);
  const text = (key: Parameters<typeof ledgerText>[2]) => ledgerText(t, language, key);

  const submit = async () => {
    try {
      const result = await controller.submit();
      toast.success(result.recovered ? text("adjustmentRecovered") : text("confirm"));
      controller.close();
      await onChanged();
    } catch (failure) {
      toast.error(apiErrorMessage(failure, text("adjustmentFailed")));
    }
  };

  return (
    <Modal
      isOpen={controller.entry !== null}
      onClose={controller.close}
      title={text("adjustmentTitle")}
      maxWidth="max-w-lg"
      initialFocusRef={quantityRef}
      footer={
        <>
          <button type="button" onClick={controller.close} className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-black text-slate-600 outline-none focus-visible:ring-2 focus-visible:ring-slate-300">
            {text("cancel")}
          </button>
          <button
            type="submit"
            form="ledger-adjustment-form"
            disabled={controller.loading || controller.submitting || !controller.password || controller.delta === null}
            className="rounded-xl bg-purple-700 px-4 py-2 text-xs font-black text-white outline-none disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-purple-300"
            data-cp13-action-priority="exceptional"
          >
            {controller.submitting ? text("saving") : text("confirm")}
          </button>
        </>
      }
    >
      {controller.loading ? (
        <p role="status" className="py-8 text-center text-sm font-bold text-slate-400">{text("adjustmentLoading")}</p>
      ) : controller.error && controller.state === null ? (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs font-bold text-red-800">
          <p>{text("adjustmentStateFailed")}</p>
          <button type="button" onClick={controller.retryState} className="mt-2 rounded-lg border border-red-200 bg-white px-3 py-1.5 outline-none focus-visible:ring-2 focus-visible:ring-red-300">{text("retry")}</button>
        </div>
      ) : controller.entry && controller.state ? (
        <form
          id="ledger-adjustment-form"
          className="space-y-4"
          data-cp13-ledger-correction="append-only"
          onSubmit={(event) => {
            event.preventDefault();
            if (!controller.submitting && controller.password && controller.delta !== null) void submit();
          }}
        >
          <div className="rounded-xl border border-purple-100 bg-purple-50 p-3 text-xs leading-6 text-purple-950">
            <div><span className="font-black">{text("product")}:</span> {controller.entry.product_name}</div>
            <div><span className="font-black">{text("originalReference")}:</span> {controller.state.reference}</div>
            <div><span className="font-black">{text("baseUom")}:</span> {controller.state.base_uom_code}</div>
          </div>

          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-xl bg-slate-50 p-3">
              <div className="font-bold text-slate-400">{text("currentTotal")}</div>
              <div className="mt-1 font-black text-slate-900">{controller.state.current_total_quantity} {controller.state.base_uom_code}</div>
            </div>
            <div className="rounded-xl bg-slate-50 p-3">
              <div className="font-bold text-slate-400">{text("resultingDelta")}</div>
              <div className="mt-1 font-black text-slate-900">{controller.delta ?? "—"} {controller.state.base_uom_code}</div>
            </div>
          </div>

          <label className="block text-xs font-black text-slate-700">
            {text("requestedTotal")}
            <input
              ref={quantityRef}
              inputMode="decimal"
              value={controller.newTotal}
              onChange={(event) => controller.setNewTotal(event.target.value.replace(/[^0-9.]/g, ""))}
              aria-label={text("requestedTotal")}
              className="mt-1 h-11 w-full rounded-xl border-2 border-slate-200 px-3 text-center font-black outline-none focus:border-purple-400 focus:ring-2 focus:ring-purple-100"
            />
          </label>

          <label className="block text-xs font-black text-slate-700">
            {text("password")}
            <input
              type="password"
              value={controller.password}
              onChange={(event) => controller.setPassword(event.target.value)}
              aria-label={text("password")}
              autoComplete="current-password"
              className="mt-1 h-11 w-full rounded-xl border-2 border-slate-200 px-3 outline-none focus:border-purple-400 focus:ring-2 focus:ring-purple-100"
            />
          </label>

          <p className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-[11px] font-bold leading-5 text-amber-950">
            <TriangleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{text("adjustmentMeaning")}</span>
          </p>
        </form>
      ) : null}
    </Modal>
  );
}
