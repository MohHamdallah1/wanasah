import { LockKeyhole, Truck } from "lucide-react";
import { useTranslation } from "react-i18next";

export function VehiclesTabPlaceholder() {
  const { t } = useTranslation();
  return (
    <section className="grid min-h-[320px] flex-1 place-items-center rounded-[26px] border border-dashed border-slate-300 bg-white/55 p-8 text-center backdrop-blur-xl" aria-disabled="true">
      <div className="max-w-md">
        <div className="mx-auto grid h-16 w-16 place-items-center rounded-[22px] bg-slate-100 text-slate-500"><Truck className="h-7 w-7" /></div>
        <div className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-[11px] font-black text-slate-600"><LockKeyhole className="h-3.5 w-3.5" />{t("representativesVehicles.vehicles.gated")}</div>
        <h2 className="mt-3 text-base font-black text-slate-900">{t("representativesVehicles.vehicles.title")}</h2>
        <p className="mt-2 text-sm font-semibold leading-6 text-slate-500">{t("representativesVehicles.vehicles.hint")}</p>
      </div>
    </section>
  );
}
