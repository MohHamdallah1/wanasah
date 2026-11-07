import type { TFunction } from "i18next";

import { Modal } from "@/components/ui/modal";
import { ledgerLocationEvidence, ledgerQuantityMeaning, ledgerSignedQuantity } from "./ledgerPresentation";
import { formatPublicBatchNumber } from "../publicBatchNumber";
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
                  <th className="px-3 py-2 text-start text-xs font-black text-slate-500">{text("batch")}</th>
                  <th className="px-3 py-2 text-start text-xs font-black text-slate-500">{text("quantity")}</th>
                  <th className="px-3 py-2 text-start text-xs font-black text-slate-500">{text("movement")}</th>
                  <th className="px-3 py-2 text-start text-xs font-black text-slate-500">{text("referenceEvidence")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {controller.items.map((item) => (
                  <tr key={item.id}>
                    <td className="px-3 py-3 font-bold text-slate-800">{item.product_name}</td>
                    <td className="px-3 py-3 text-xs font-bold text-slate-700">{formatPublicBatchNumber(item.batch_number, text("noLot"))}</td>
                    <td className="px-3 py-3 font-black text-slate-700">
                      <bdi dir="auto">{ledgerSignedQuantity(item, code => t(`uom.${code}`, { defaultValue: code }))}</bdi>
                      <div className="text-[10px] font-normal text-slate-500" data-ledger-quantity-kind={item.movement_kind ?? "PHYSICAL"}>{ledgerQuantityMeaning(t, language, item)}</div>
                    </td>
                    <td className="px-3 py-3">
                      <span className={`inline-flex rounded-md border px-2 py-1 text-[10px] font-black ${ledgerBadgeClass(item.type)}`}>
                        {ledgerMovementLabel(t, language, item.type)}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-[10px] leading-5 text-slate-600">
                      <div>#{item.id} · {new Date(item.date).toLocaleString(language.startsWith("ar") ? "ar" : "en", { numberingSystem: "latn" })}</div>
                      <div>{text("actor")}: {item.admin_name || text("unknown")}</div>
                      <div>{text("source")}: {ledgerLocationEvidence(t, language, item).source}</div>
                      <div>{text("destination")}: {ledgerLocationEvidence(t, language, item).destination}</div>
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
