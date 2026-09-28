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
          className="max-w-[min(24rem,calc(100vw-2rem))] space-y-2 p-3 text-start text-xs leading-5"
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
