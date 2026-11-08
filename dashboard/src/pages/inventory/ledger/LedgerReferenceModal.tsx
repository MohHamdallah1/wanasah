import type { TFunction } from "i18next";
import { useEffect, useRef } from "react";
import { operationText, localizedOperationLocationNames, abbreviatedOperationReference } from "./operationI18n";
import { formatLedgerDate } from "./contracts";

import { Modal } from "@/components/ui/modal";
import { ledgerLocationEvidence, ledgerQuantityMeaning, ledgerSignedQuantity } from "./ledgerPresentation";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import type { LedgerReferenceState } from "./useLedgerReference";
import { ledgerBadgeClass, ledgerMovementLabel, ledgerText } from "./ledgerI18n";

interface Props {
  t: TFunction;
  language: string;
  controller: LedgerReferenceState;
  embedded?: boolean;
  onBack?: () => void;
}

export function LedgerReferenceModal({ t, language, controller, embedded = false, onBack }: Props) {
  const backRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (embedded && controller.entry) backRef.current?.focus();
  }, [embedded, controller.entry]);
  const text = (key: Parameters<typeof ledgerText>[2], values: Record<string, unknown> = {}) =>
    ledgerText(t, language, key, values);
  const reference = controller.entry?.reference ?? "";

  const content = (
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
                      <div><bdi dir="ltr">#{item.id}</bdi> · <time dateTime={item.date}
                        lang={language.startsWith("ar") ? "ar" : "en"} dir={language.startsWith("ar") ? "rtl" : "ltr"}
                        className="inline-block isolate whitespace-nowrap">{formatLedgerDate(item.date, language.startsWith("ar") ? "ar" : "en")}</time></div>
                      <div>{text("actor")}: {item.admin_name || text("unknown")}</div>
                      <div>{text("source")}: {ledgerLocationEvidence(t, language, localizedOperationLocationNames(item, language, t)).source}</div>
                      <div>{text("destination")}: {ledgerLocationEvidence(t, language, localizedOperationLocationNames(item, language, t)).destination}</div>
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
  );
  if (embedded) {
    if (!controller.entry) return null;
    return (
      <section data-ledger-reference-in-panel="true" className="min-h-0 flex-1 overflow-y-auto" aria-label={text("referenceDetails", { reference })}>
        <div className="sticky top-0 z-10 mb-2 flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white pb-2">
          <button ref={backRef} data-ledger-reference-back="true" type="button"
            onClick={onBack ?? controller.close}
            className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-bold text-blue-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">
            {operationText(t, language, "backToOperation")}
          </button>
          <h4 className="min-w-0 flex-1 text-start text-xs font-bold text-slate-800"
            title={reference}>
            {operationText(t, language, "copy21")} ·{" "}
            <bdi dir="ltr" tabIndex={0} title={reference} aria-label={reference}
              className="inline-block max-w-full truncate align-bottom outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">
              {abbreviatedOperationReference(reference)}
            </bdi>
          </h4>
        </div>
        {content}
      </section>
    );
  }
  return (
    <Modal isOpen={controller.entry !== null} onClose={controller.close}
      title={text("referenceDetails", { reference })} maxWidth="max-w-3xl">
      {content}
    </Modal>
  );
}
