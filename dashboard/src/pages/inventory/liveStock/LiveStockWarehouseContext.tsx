import { RefreshCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { resolveI18nLocale } from "@/lib/locale";

type Props = {
  locationId: number;
  locations: Array<{ id: number; name: string }>;
  stockTotal: number | null;
  lastSync: Date | null;
  isAuditLocked: boolean;
  loading: boolean;
  onLocationChange: (value: string) => void;
  onRefresh: () => void;
};

export function LiveStockWarehouseContext({
  locationId,
  locations,
  stockTotal,
  lastSync,
  isAuditLocked,
  loading,
  onLocationChange,
  onRefresh,
}: Props) {
  const { t, i18n } = useTranslation();
  const locale = resolveI18nLocale(i18n);

  return (
    <div className="live-stock-context-panel" data-cp13-warehouse-context="true" dir={i18n.dir()}>
      <label className="live-stock-context-location">
        <span className="live-stock-context-label">
          {t("inventoryShell.warehouseSelectLabel")}
        </span>
        <select
          aria-label={t("inventoryShell.warehouseSelectLabel")}
          value={locationId}
          onChange={(event) => onLocationChange(event.target.value)}
          className="live-stock-context-select outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        >
          {locations.map((location) => (
            <option key={location.id} value={location.id}>
              {location.name}
            </option>
          ))}
        </select>
      </label>

      <div className="live-stock-context-separator" aria-hidden="true" />

      <div className="live-stock-context-status">
        <div className="live-stock-context-count" title={t("inventoryShell.summaryVariantCountHint")}>
          <span>{t("inventoryShell.liveStockCount")}</span>
          <strong className="tabular-nums" aria-label={stockTotal === null
            ? t("inventoryShell.countNotVerified")
            : undefined}>
            {stockTotal === null
              ? "—"
              : new Intl.NumberFormat(locale, {
                  numberingSystem: "latn",
                }).format(stockTotal)}
          </strong>
          <span className="sr-only">{t("inventoryShell.summaryVariantCountHint")}</span>
          {isAuditLocked ? (
            <span className="live-stock-lock-chip">{t("inventoryShell.locked")}</span>
          ) : null}
        </div>
        <div className="live-stock-context-sync">
          <span title={t("inventoryShell.lastUpdated")}>
            {t("inventoryShell.lastUpdated")}: {" "}
            {lastSync
              ? new Intl.DateTimeFormat(locale, {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                  hour12: false,
                  numberingSystem: "latn",
                }).format(lastSync)
              : <span aria-label={t("inventoryShell.countNotVerified")}>—</span>}
          </span>
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className="live-stock-context-refresh outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
            title={t("inventoryShell.refreshNow")}
            aria-label={t("inventoryShell.refreshNow")}
          >
            <RefreshCcw
              className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
              aria-hidden="true"
            />
          </button>
        </div>
      </div>
    </div>
  );
}
