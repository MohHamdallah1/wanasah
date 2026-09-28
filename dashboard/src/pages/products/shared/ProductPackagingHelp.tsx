import {
  CircleHelp,
} from "lucide-react";
import {
  useTranslation,
} from "react-i18next";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

type Props = {
  compact?: boolean;
};

export function ProductPackagingHelp({
  compact = false,
}: Props) {
  const { t } = useTranslation();

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={t(
              "products.packageGlossary.title",
            )}
            className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-1.5 text-[11px] font-bold text-slate-700 underline-offset-2 hover:text-slate-950 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
          >
            <CircleHelp
              aria-hidden="true"
              className="h-4 w-4 shrink-0"
            />
            {!compact ? (
              <span>
                {t(
                  "products.packageGlossary.title",
                )}
              </span>
            ) : null}
          </button>
        </TooltipTrigger>
        <TooltipContent
          side="bottom"
          align="start"
          className="max-h-[70vh] max-w-[min(26rem,calc(100vw-2rem))] space-y-2 overflow-y-auto p-3 text-start text-xs leading-5"
        >
          <p className="font-semibold">
            {t(
              "products.packageGlossary.base",
            )}
          </p>
          <p>
            {t(
              "products.packageGlossary.outer",
            )}
          </p>
          <p>
            {t(
              "products.packageGlossary.none",
            )}
          </p>
          <div className="border-t border-border pt-2">
            <p className="mb-1 font-bold">
              {t(
                "products.packageGlossary.examplesTitle",
              )}
            </p>
            <table className="w-full table-fixed border-collapse text-[11px] leading-4">
              <thead>
                <tr>
                  <th scope="col" className="w-2/5 pb-1 text-start font-bold">
                    {t(
                      "products.packageGlossary.caseHeading",
                    )}
                  </th>
                  <th scope="col" className="pb-1 text-start font-bold">
                    {t(
                      "products.packageGlossary.setupHeading",
                    )}
                  </th>
                </tr>
              </thead>
              <tbody>
                {(["single", "carton", "pack"] as const).map(
                  (kind) => (
                    <tr key={kind} className="border-t border-border">
                      <th scope="row" className="py-1 text-start align-top font-medium">
                        {t(
                          `products.packageGlossary.examples.${kind}.case`,
                        )}
                      </th>
                      <td className="py-1 align-top">
                        {t(
                          `products.packageGlossary.examples.${kind}.setup`,
                        )}
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
          <p className="border-t border-border pt-2 text-muted-foreground">
            {t(
              "products.packageGlossary.limits",
            )}
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
