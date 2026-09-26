import {
  ChevronDown,
  FileSpreadsheet,
  PackagePlus,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type Props = {
  canCreateSimpleProduct: boolean;
  canImportProducts: boolean;
  onOpenCreateProduct: () => void;
  onOpenImport: () => void;
};

const primaryButtonClass =
  "inline-flex min-h-10 min-w-0 items-center justify-center gap-2 bg-amber-400 px-4 text-xs font-black text-slate-950 shadow-sm transition hover:bg-amber-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300";

export function ProductsAddAction({
  canCreateSimpleProduct,
  canImportProducts,
  onOpenCreateProduct,
  onOpenImport,
}: Props) {
  const { t, i18n } =
    useTranslation();
  const direction =
    i18n.dir();

  if (
    !canCreateSimpleProduct &&
    !canImportProducts
  ) {
    return null;
  }

  if (
    canCreateSimpleProduct &&
    !canImportProducts
  ) {
    return (
      <button
        type="button"
        onClick={onOpenCreateProduct}
        className={`${primaryButtonClass} flex-1 rounded-xl sm:flex-none`}
      >
        <PackagePlus className="h-4 w-4 shrink-0" />
        <span className="break-words">
          {t("products.addProduct")}
        </span>
      </button>
    );
  }

  if (
    !canCreateSimpleProduct &&
    canImportProducts
  ) {
    return (
      <button
        type="button"
        onClick={onOpenImport}
        className={`${primaryButtonClass} flex-1 rounded-xl sm:flex-none`}
      >
        <FileSpreadsheet className="h-4 w-4 shrink-0" />
        <span className="break-words">
          {t("products.importFile")}
        </span>
      </button>
    );
  }

  return (
    <div className="flex min-w-0 flex-1 sm:flex-none">
      <button
        type="button"
        onClick={onOpenCreateProduct}
        className={`${primaryButtonClass} flex-1 rounded-s-xl border-e border-slate-950/10 sm:flex-none`}
      >
        <PackagePlus className="h-4 w-4 shrink-0" />
        <span className="break-words">
          {t("products.addProduct")}
        </span>
      </button>

      <DropdownMenu dir={direction}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label={t(
              "products.importFile",
            )}
            title={t(
              "products.importFile",
            )}
            className="inline-flex min-h-10 w-10 shrink-0 items-center justify-center rounded-e-xl bg-amber-400 text-slate-950 shadow-sm transition hover:bg-amber-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300"
          >
            <ChevronDown className="h-4 w-4" />
          </button>
        </DropdownMenuTrigger>

        <DropdownMenuContent
          dir={direction}
          align="end"
          className="w-56 rounded-xl border-slate-200 p-1.5 text-start shadow-xl"
        >
          <DropdownMenuItem
            onSelect={onOpenImport}
            className="gap-3 rounded-lg px-2.5 py-2.5 text-start text-xs font-bold text-slate-700"
          >
            <FileSpreadsheet className="h-4 w-4 shrink-0 text-slate-400" />
            {t("products.importFile")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
