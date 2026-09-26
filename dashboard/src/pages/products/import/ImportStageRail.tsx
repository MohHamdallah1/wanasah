import {
  Check,
  FileUp,
  LoaderCircle,
  Rows3,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  ProductImportState,
} from "@/pages/products/contracts";

type Props = {
  jobId: string | null;
  status: ProductImportState | null;
};

type Stage =
  | "upload"
  | "mapping"
  | "processing"
  | "result";

const stageOrder: Stage[] = [
  "upload",
  "mapping",
  "processing",
  "result",
];

const stageIcon = {
  upload: FileUp,
  mapping: Rows3,
  processing: LoaderCircle,
  result: Check,
} as const;

const currentStage = (
  jobId: string | null,
  status: ProductImportState | null,
): Stage => {
  if (!jobId) {
    return "upload";
  }
  if (status?.status === "NEEDS_MAPPING") {
    return "mapping";
  }
  if (
    status?.status === "COMPLETED" ||
    status?.status === "FAILED" ||
    status?.status === "VALIDATION_FAILED"
  ) {
    return "result";
  }
  return "processing";
};

export function ImportStageRail({
  jobId,
  status,
}: Props) {
  const { t } = useTranslation();
  const active = currentStage(
    jobId,
    status,
  );
  const activeIndex =
    stageOrder.indexOf(active);

  return (
    <ol
      aria-label={t(
        "products.importStages.label",
      )}
      className="grid grid-cols-4 gap-1 rounded-xl bg-slate-100 p-1"
    >
      {stageOrder.map(
        (stage, index) => {
          const Icon =
            stageIcon[stage];
          const reached =
            index <= activeIndex;
          const selected =
            stage === active;

          return (
            <li
              key={stage}
              aria-current={
                selected
                  ? "step"
                  : undefined
              }
              className={
                "flex min-w-0 items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-[10px] font-black transition " +
                (
                  selected
                    ? "bg-white text-slate-950 shadow-sm ring-1 ring-slate-200"
                    : reached
                      ? "text-slate-700"
                      : "text-slate-400"
                )
              }
            >
              <Icon
                className={
                  "h-3.5 w-3.5 shrink-0 " +
                  (
                    stage ===
                      "processing" &&
                    selected
                      ? "animate-spin"
                      : ""
                  )
                }
              />
              <span className="truncate">
                {t(
                  "products.importStages." +
                    stage,
                )}
              </span>
            </li>
          );
        },
      )}
    </ol>
  );
}
