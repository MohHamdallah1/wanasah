import { Info } from "lucide-react";
import { useTranslation } from "react-i18next";

export function ProductExpiryRecommendation() {
  const { t } = useTranslation();

  return (
    <div className="flex items-start gap-2 rounded-lg border border-amber-100 bg-amber-50/70 px-3 py-2">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-700" />
      <p className="text-[10px] font-semibold leading-4 text-amber-950">
        {t("products.tracking.foodExpiryRecommendation")}
      </p>
    </div>
  );
}