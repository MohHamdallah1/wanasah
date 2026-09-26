import {
  ArrowLeftRight,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  IMPORT_MAPPING_FIELDS,
  importMappingLabelKey,
  type ImportMappingField,
} from "@/pages/products/import/importFields";

type Props = {
  detectedHeaders: string[];
  mapping: Record<string, string>;
  mappingPending: boolean;
  online: boolean;
  onMappingChange: (
    field: ImportMappingField,
    value: string,
  ) => void;
  onSubmitMapping: () => void;
};

export function ImportProductMappingPanel({
  detectedHeaders,
  mapping,
  mappingPending,
  online,
  onMappingChange,
  onSubmitMapping,
}: Props) {
  const { t } = useTranslation();

  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2 rounded-xl border border-amber-100 bg-amber-50/70 px-3 py-2.5">
        <ArrowLeftRight className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
        <p className="text-[10px] font-bold leading-4 text-amber-900">
          {t(
            "products.mappingIntro",
          )}
        </p>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {IMPORT_MAPPING_FIELDS.map(
          (field) => (
            <label
              key={field}
              className="min-w-0 rounded-xl border border-slate-200 bg-white p-2.5"
            >
              <span className="block truncate text-[10px] font-black text-slate-500">
                {t(
                  importMappingLabelKey(
                    field,
                  ),
                )}
              </span>
              <select
                value={
                  mapping[field] ?? ""
                }
                onChange={(event) =>
                  onMappingChange(
                    field,
                    event.target.value,
                  )
                }
                className="mt-1.5 h-9 w-full min-w-0 rounded-lg border border-slate-200 bg-slate-50 px-2 text-xs font-bold text-slate-700 outline-none transition focus:border-slate-400 focus:bg-white focus:ring-2 focus:ring-slate-100"
              >
                <option value="">
                  {t(
                    "products.unmapped",
                  )}
                </option>
                {detectedHeaders.map(
                  (header) => (
                    <option
                      key={header}
                      value={header}
                    >
                      {header}
                    </option>
                  ),
                )}
              </select>
            </label>
          ),
        )}
      </div>

      <button
        type="button"
        disabled={
          mappingPending ||
          !online
        }
        onClick={onSubmitMapping}
        className="w-full rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-black text-white disabled:opacity-40"
      >
        {t(
          "products.continueImport",
        )}
      </button>
    </div>
  );
}
