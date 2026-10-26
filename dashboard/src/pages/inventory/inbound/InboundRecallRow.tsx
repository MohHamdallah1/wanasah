import { useTranslation } from "react-i18next";

import { currentLocale } from "@/i18n";
import { INBOUND_RECALL_BLOCK_CODE } from "./eligibility";

export function InboundRecallRow({
  name,
  number,
  rowRef,
}: {
  name: string;
  number: number;
  rowRef: (node: HTMLTableRowElement | null) => void;
}) {
  const { t } = useTranslation();
  return (
    <tr ref={rowRef}>
      <td className="inventory-inbound-number-cell">
        {new Intl.NumberFormat(currentLocale()).format(number)}
      </td>
      <td className="inventory-inbound-product-cell">
        <strong>{name}</strong>
        <p className="font-semibold text-destructive">
          {t("inventoryInbound.recallStatus")}
        </p>
      </td>
      <td colSpan={5}>
        <p>{t(`errors.codes.${INBOUND_RECALL_BLOCK_CODE}`)}</p>
      </td>
    </tr>
  );
}
