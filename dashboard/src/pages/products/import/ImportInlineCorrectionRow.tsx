import { AlertCircle } from "lucide-react";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import {
  Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from "@/components/ui/tooltip";
import { importMappingLabelKey, type ImportMappingField } from "@/pages/products/import/importFields";
import {
  formatInlineValue, type InlineCorrectionError, type InlineCorrectionRow,
} from "@/pages/products/import/inlineCorrectionContracts";

type Props = {
  row: InlineCorrectionRow;
  fields: ImportMappingField[];
  index: number;
  edits: Partial<Record<ImportMappingField, string>>;
  disabled: boolean;
  onChange: (identity: string, field: ImportMappingField, value: string) => void;
};

function hasFieldError(error: InlineCorrectionError, field: ImportMappingField) {
  return error.field === field ||
    (error.field === "barcode" && (field === "unit_barcode" || field === "package_barcode")) ||
    (error.field === "price" && (field === "unit_price" || field === "package_price"));
}

export function ImportInlineCorrectionRow({
  row, fields, index, edits, disabled, onChange,
}: Props) {
  const { t, i18n } = useTranslation();
  const prefix = useId();
  const errorText = (error: InlineCorrectionError) => {
    const key = error.code ? "errors.codes." + error.code : "";
    return key && i18n.exists(key) ? t(key) : t("products.inlineCorrection.genericError");
  };
  const errors = row.errors.map((error) => errorText(error));
  const name = formatInlineValue(row.values.name);
  return (
    <li className="list-none">
      <details className="group rounded-xl border border-amber-200 bg-white" open={undefined} {...(index === 0 ? { defaultOpen: true } : {})}>
        <summary className="flex min-h-12 cursor-pointer flex-wrap items-start justify-between gap-2 px-3 py-2.5 marker:text-amber-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500">
          <span className="flex min-w-0 flex-1 items-start gap-2">
            <AlertCircle aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
            <span className="min-w-0">
              <strong className="block text-xs font-black text-slate-900">
                {t("products.rowNumber", { row: row.row_number })}
                {name ? <span className="ms-2 font-semibold text-slate-600">— {name}</span> : null}
              </strong>
              {errors.map((message, i) => (
                <span key={i} className="mt-1 block text-xs leading-5 text-rose-800">{message}</span>
              ))}
              {!row.editable ? (
                <span className="mt-1 block text-xs text-slate-500">
                  {t("products.inlineCorrection.unavailable." + (row.unavailable_reason || "JOB_NOT_CORRECTABLE"))}
                </span>
              ) : null}
            </span>
          </span>
          <span className="shrink-0 rounded-full bg-amber-50 px-2 py-1 text-[10px] font-black text-amber-900">
            {t("products.inlineCorrection.viewRow")}
          </span>
        </summary>

        {row.editable ? (
          <div className="grid gap-3 border-t border-slate-100 bg-slate-50/50 p-3 sm:grid-cols-2">
            <TooltipProvider delayDuration={180}>
              {fields.map((field) => {
                const fieldErrors = row.errors.filter((error) => hasFieldError(error, field));
                const issueText = fieldErrors.map(errorText).join(" ");
                const hasIssue = fieldErrors.length > 0;
                const issueId = prefix + "-" + field + "-issue";
                const current = Object.prototype.hasOwnProperty.call(edits, field)
                  ? edits[field] ?? "" : formatInlineValue(row.values[field]);
                const label = t(importMappingLabelKey(field));
                const tracking = field === "lot_control_mode" || field === "expiry_control_mode";
                const inputClass = "min-h-10 w-full rounded-lg border bg-white px-2.5 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 disabled:opacity-50 " +
                  (hasIssue ? "border-rose-400" : "border-slate-200");
                return (
                  <div key={field} className="min-w-0 space-y-1">
                    <div className="flex items-center gap-1.5">
                      <label className="text-xs font-bold text-slate-800" htmlFor={prefix + "-" + field}>
                        {label}
                      </label>
                      {hasIssue ? (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              aria-label={t("products.inlineCorrection.errorFor", { field: label })}
                              aria-describedby={issueId}
                              className="inline-flex h-6 w-6 items-center justify-center rounded-full text-rose-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
                            >
                              <AlertCircle aria-hidden className="h-4 w-4" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent side="top" className="max-w-64">
                            {issueText}
                          </TooltipContent>
                        </Tooltip>
                      ) : null}
                    </div>
                    {tracking ? (
                      <select
                        id={prefix + "-" + field}
                        value={current}
                        disabled={disabled}
                        aria-invalid={hasIssue}
                        aria-describedby={hasIssue ? issueId : undefined}
                        onChange={(event) => onChange(row.row_identity, field, event.target.value)}
                        className={inputClass}
                      >
                        {current && !["NONE", "OPTIONAL", "REQUIRED", "__DEFAULT__"].includes(current) ? (
                          <option value={current}>{current}</option>
                        ) : null}
                        <option value="">{t("products.inlineCorrection.emptyValue")}</option>
                        <option value="__DEFAULT__">{t("products.importGuideUseDefault")}</option>
                        {(["NONE", "OPTIONAL", "REQUIRED"] as const).map((mode) => (
                          <option key={mode} value={mode}>{t("products.tracking.importValues." + mode)}</option>
                        ))}
                      </select>
                    ) : (
                      <input
                        id={prefix + "-" + field}
                        type="text"
                        inputMode={field === "unit_price" || field === "package_price" || field === "units_per_package" ? "decimal" : "text"}
                        autoComplete="off"
                        maxLength={4096}
                        value={current}
                        disabled={disabled}
                        aria-invalid={hasIssue}
                        aria-describedby={hasIssue ? issueId : undefined}
                        onChange={(event) => onChange(row.row_identity, field, event.target.value)}
                        className={inputClass}
                      />
                    )}
                    {hasIssue ? (
                      <p id={issueId} className="text-[11px] font-semibold leading-4 text-rose-800">{issueText}</p>
                    ) : null}
                  </div>
                );
              })}
            </TooltipProvider>
          </div>
        ) : null}
      </details>
    </li>
  );
}
