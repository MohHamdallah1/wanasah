import type { TFunction } from "i18next";

import { Modal } from "@/components/ui/modal";
import { absoluteQuantity, compareQuantity, formatQuantity } from "@/lib/quantity";
import type { LedgerReferenceState } from "./useLedgerReference";
import { ledgerBadgeClass, ledgerMovementLabel, ledgerText } from "./ledgerI18n";

interface Props {
  t: TFunction;
  language: string;
  controller: LedgerReferenceState;
}

export function LedgerReferenceModal({ t, language, controller }: Props) {
  const text = (key: Parameters<typeof ledgerText>[2], values: Record<string, unknown> = {}) =>
    ledgerText(t, language, key, values);
  const reference = controller.entry?.reference ?? "";

  return (
    <Modal
      isOpen={controller.entry !== null}
      onClose={controller.close}
      title={text("referenceDetails", { reference })}
      maxWidth="max-w-3xl"
    >
      <div className="space-y-3">
        {controller.loading && controller.items.length === 0 ? (
          <p role="status" className="py-8 text-center text-sm font-bold text-slate-400">{text("referenceLoading")}</p>
        ) : null}

        {controller.items.length > 0 ? (
          <div className="max-h-[60vh] overflow-auto rounded-xl border border-slate-200">
            <table className="w-full min-w-[560px] text-sm">
              <thead className="sticky top-0 bg-slate-50">
                <tr>
                  <th className="px-3 py-2 text-start text-xs font-black text-slate-500">{text("product")}</th>
                  <th className="px-3 py-2 text-start text-xs font-black text-slate-500">{text("quantity")}</th>
                  <th className="px-3 py-2 text-start text-xs font-black text-slate-500">{text("movement")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {controller.items.map((item) => (
                  <tr key={item.id}>
                    <td className="px-3 py-3 font-bold text-slate-800">{item.product_name}</td>
                    <td className="px-3 py-3 font-black text-slate-700">
                      {compareQuantity(item.quantity, "0") < 0 ? "-" : "+"}
                      {formatQuantity(absoluteQuantity(item.quantity), item.base_uom_code)}
                    </td>
                    <td className="px-3 py-3">
                      <span className={`inline-flex rounded-md border px-2 py-1 text-[10px] font-black ${ledgerBadgeClass(item.type)}`}>
                        {ledgerMovementLabel(t, language, item.type)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {controller.error ? (
          <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs font-bold text-red-800">
            <p>{text("referenceFailed")}</p>
            <button type="button" onClick={controller.retry} className="mt-2 rounded-lg border border-red-200 bg-white px-3 py-1.5 outline-none focus-visible:ring-2 focus-visible:ring-red-300">{text("retry")}</button>
          </div>
        ) : null}

        {!controller.loading && !controller.error && controller.items.length === 0 ? (
          <p className="py-6 text-center text-xs font-semibold text-slate-500">{text("referenceEmpty")}</p>
        ) : null}
      </div>
    </Modal>
  );
}
