import {
  BookOpenText,
  ChevronDown,
  ChevronUp,
  Download,
} from "lucide-react";
import {
  useState,
} from "react";
import {
  useTranslation,
} from "react-i18next";

import type {
  ProductTrackingMode,
} from "@/pages/products/contracts";

type Props = {
  lotControlMode: ProductTrackingMode | null;
  expiryControlMode: ProductTrackingMode | null;
  trackingUsesCompanyDefaults: boolean;
  onDownloadTemplate: () => void;
};

export function ImportProductQuickGuide({
  lotControlMode,
  expiryControlMode,
  trackingUsesCompanyDefaults,
  onDownloadTemplate,
}: Props) {
  const { t } =
    useTranslation();
  const [
    exampleOpen,
    setExampleOpen,
  ] = useState(false);

  const modeLabel = (
    mode: ProductTrackingMode,
  ) =>
    t(
      `products.tracking.importValues.${mode}`,
    );

  const fallbackText =
    lotControlMode &&
    expiryControlMode
      ? t(
          trackingUsesCompanyDefaults
            ? "products.importGuideFallbackCompany"
            : "products.importGuideFallbackImport",
          {
            lot:
              modeLabel(
                lotControlMode,
              ),
            expiry:
              modeLabel(
                expiryControlMode,
              ),
          },
        )
      : t(
          "products.importGuideFallbackUnavailable",
        );

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-col gap-3 border-b border-slate-100 px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-950 text-white">
            <BookOpenText className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <h3 className="text-xs font-black text-slate-950">
              {t(
                "products.importGuideTitle",
              )}
            </h3>
            <p className="mt-0.5 text-[10px] font-semibold leading-4 text-slate-500">
              {t(
                "products.importGuideSubtitle",
              )}
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={
            onDownloadTemplate
          }
          className="inline-flex min-h-9 shrink-0 items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 text-xs font-black text-white transition hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        >
          <Download className="h-3.5 w-3.5" />
          {t(
            "products.downloadTemplate",
          )}
        </button>
      </div>

      <div className="grid divide-y divide-slate-100 md:grid-cols-3 md:divide-x md:divide-y-0 md:rtl:divide-x-reverse">
        <div className="px-3 py-2.5">
          <strong className="block text-[10px] font-black text-slate-900">
            {t(
              "products.importGuideRowTitle",
            )}
          </strong>
          <p className="mt-1 text-[10px] font-semibold leading-4 text-slate-500">
            {t(
              "products.importGuideRowRule",
            )}
          </p>
        </div>

        <div className="px-3 py-2.5">
          <strong className="block text-[10px] font-black text-slate-900">
            {t(
              "products.importGuideTrackingTitle",
            )}
          </strong>
          <p className="mt-1 text-[10px] font-semibold leading-4 text-slate-500">
            {t(
              "products.importGuideTrackingRule",
              {
                none: modeLabel(
                  "NONE",
                ),
                optional:
                  modeLabel(
                    "OPTIONAL",
                  ),
                required:
                  modeLabel(
                    "REQUIRED",
                  ),
              },
            )}
          </p>
        </div>

        <div className="px-3 py-2.5">
          <strong className="block text-[10px] font-black text-slate-900">
            {t(
              "products.importGuideBlankTitle",
            )}
          </strong>
          <p className="mt-1 text-[10px] font-semibold leading-4 text-slate-500">
            {fallbackText}
          </p>
        </div>
      </div>

      <div className="border-t border-slate-100">
        <button
          type="button"
          aria-expanded={
            exampleOpen
          }
          onClick={() =>
            setExampleOpen(
              (current) =>
                !current,
            )
          }
          className="flex min-h-9 w-full items-center justify-between gap-3 px-3 text-start text-[10px] font-black text-slate-700 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber-400"
        >
          <span>
            {t(
              exampleOpen
                ? "products.importGuideHideExample"
                : "products.importGuideShowExample",
            )}
          </span>
          {exampleOpen ? (
            <ChevronUp className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 shrink-0" />
          )}
        </button>

        {exampleOpen ? (
          <div className="overflow-x-auto border-t border-slate-100">
            <table className="w-full min-w-[34rem] text-start text-[10px]">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="px-3 py-2 font-black">
                    {t(
                      "products.importGuideExampleProduct",
                    )}
                  </th>
                  <th className="px-3 py-2 font-black">
                    {t(
                      "products.fields.lotControlMode",
                    )}
                  </th>
                  <th className="px-3 py-2 font-black">
                    {t(
                      "products.fields.expiryControlMode",
                    )}
                  </th>
                  <th className="px-3 py-2 font-black">
                    {t(
                      "products.importGuideExampleResult",
                    )}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                <tr>
                  <td className="px-3 py-2 font-bold">
                    {t(
                      "products.importGuideExampleA",
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {modeLabel(
                      "REQUIRED",
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {modeLabel(
                      "REQUIRED",
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {t(
                      "products.importGuideOwnValues",
                    )}
                  </td>
                </tr>
                <tr>
                  <td className="px-3 py-2 font-bold">
                    {t(
                      "products.importGuideExampleB",
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {modeLabel(
                      "OPTIONAL",
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {modeLabel(
                      "NONE",
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {t(
                      "products.importGuideOwnValues",
                    )}
                  </td>
                </tr>
                <tr>
                  <td className="px-3 py-2 font-bold">
                    {t(
                      "products.importGuideExampleC",
                    )}
                  </td>
                  <td className="px-3 py-2 text-slate-400">
                    —
                  </td>
                  <td className="px-3 py-2 text-slate-400">
                    —
                  </td>
                  <td className="px-3 py-2 font-bold text-slate-900">
                    {t(
                      "products.importGuideUsesDefaults",
                    )}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </section>
  );
}
