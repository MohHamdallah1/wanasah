import type { TFunction } from "i18next";

import type { LedgerEntry } from "./contracts";
import { ledgerText } from "./ledgerI18n";
import { ledgerMoney } from "./ledgerPresentation";

interface Props {
  t: TFunction;
  language: string;
  entry: LedgerEntry;
}

export function LedgerCostEvidence({ t, language, entry }: Props) {
  const text = (key: Parameters<typeof ledgerText>[2]) => ledgerText(t, language, key);
  const unit = (code: string) => t(`uom.${code}`, { defaultValue: code });
  const hasEvidence = entry.input_unit_cost !== null
    || entry.total_cost !== null || entry.average_cost_after !== null;
  if (!hasEvidence) return <>—</>;

  return (
    <div className="text-[10px] font-semibold leading-5 text-slate-600" data-ledger-cost-evidence="true">
      {entry.input_unit_cost !== null && (
        <div>{text("inputPrice")}: {ledgerMoney(entry.input_unit_cost, entry.currency_code)} / {unit(entry.input_uom_code ?? entry.base_uom_code)}</div>
      )}
      {entry.total_cost !== null && (
        <div>{text("inventoryValueMovement")}: {ledgerMoney(entry.total_cost, entry.currency_code)}</div>
      )}
      {entry.average_cost_after !== null && (
        <div>{text("averageAfter")}: {ledgerMoney(entry.average_cost_after, entry.currency_code)} / {unit(entry.average_cost_uom_code ?? entry.base_uom_code)}</div>
      )}
      {entry.cost_method && (
        <div>{text("costMethod")}: {text(entry.cost_method === "FIFO" ? "costMethod_FIFO" : "costMethod_MOVING_AVERAGE")}</div>
      )}
      <div className="mt-0.5 text-slate-500">{text("costMeaning")}</div>
    </div>
  );
}
