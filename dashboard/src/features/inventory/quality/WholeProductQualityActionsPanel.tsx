import { AlertTriangle, ArrowRight, PackageCheck, Trash2, Truck, Warehouse } from "lucide-react";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { parseConversions } from "@/features/catalog/contracts";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import {
  compareQuantity,
  formatCommercialQuantity,
  parseQuantity,
  type Quantity,
} from "@/lib/quantity";
import { QualityHandlingDestinationsCard } from "./QualityHandlingDestinationsCard";
import {
  actionTotal,
  aggregateProductQualityLocations,
  type ProductQualityLocation,
} from "./productQualityLocationModel";
import { useProductQualityCommands } from "./useProductQualityCommands";
import { useProductQualitySources } from "./useProductQualitySources";
import type { QualityDispatchPurpose, QualityTerminalAction } from "./wholeProductQualityContract";

type ActionKind =
  | { kind: "stage"; purpose: QualityDispatchPurpose; location: ProductQualityLocation }
  | { kind: "terminal"; action: QualityTerminalAction; location: ProductQualityLocation };

const scaled = (value: string): bigint => {
  const [whole, fraction = ""] = value.split(".");
  return BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0"));
};
const canonical = (value: bigint): Quantity => {
  const whole = value / 1_000_000n;
  const fraction = (value % 1_000_000n).toString().padStart(6, "0").replace(/0+$/, "");
  return (fraction ? `${whole}.${fraction}` : whole.toString()) as Quantity;
};
const exactRatio = (numerator: Quantity, denominator: Quantity): Quantity | null => {
  const top = scaled(numerator) * 1_000_000n;
  const bottom = scaled(denominator);
  if (bottom <= 0n || top % bottom !== 0n) return null;
  return canonical(top / bottom);
};

export function WholeProductQualityActionsPanel({
  productVariantId,
  baseUomId,
  baseUomName,
  onBack,
}: {
  productVariantId: number;
  baseUomId: number;
  baseUomName: string;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const query = useProductQualitySources(productVariantId);
  const [active, setActive] = useState<ActionKind | null>(null);
  const [quantityInput, setQuantityInput] = useState("");
  const [reason, setReason] = useState("");
  const [method, setMethod] = useState("");
  const [evidence, setEvidence] = useState("");
  const [vendorName, setVendorName] = useState("");
  const [vendorReference, setVendorReference] = useState("");
  const [handoverReference, setHandoverReference] = useState("");
  const [showSetup, setShowSetup] = useState(false);
  const pages = query.data?.pages ?? [];
  const allLoaded = !query.hasNextPage && !query.isFetchingNextPage;
  const baseIdentity = pages[0] ? { id: pages[0].baseUomId, code: pages[0].baseUomCode } : null;
  const locations = useMemo(
    () => (allLoaded ? aggregateProductQualityLocations(pages) : []),
    [allLoaded, pages],
  );
  const commands = useProductQualityCommands({
    productVariantId,
    baseUomId: baseIdentity?.id ?? baseUomId,
    onSucceeded: async () => { await query.refetch(); },
  });
  const conversions = useQuery({
    queryKey: ["product-quality-display-uom", access.data?.company_id ?? null, access.data?.driver_id ?? null, productVariantId],
    enabled: access.data !== undefined,
    queryFn: async ({ signal }) => parseConversions(await authFetch(`/catalog/variants/${productVariantId}/conversions`, { signal })),
    staleTime: 60_000,
    retry: false,
  });

  const display = useMemo(() => {
    const candidates = (conversions.data ?? []).filter((item) =>
      item.to_uom.id === baseUomId && compareQuantity(item.numerator, item.denominator) > 0,
    );
    if (candidates.length !== 1) return { name: baseUomName, factor: "1" as Quantity };
    const factor = exactRatio(candidates[0].numerator, candidates[0].denominator);
    return factor ? { name: candidates[0].from_uom.name, factor } : { name: baseUomName, factor: "1" as Quantity };
  }, [baseUomId, baseUomName, conversions.data]);

  const format = (value: Quantity) => formatCommercialQuantity(value, display.name, baseUomName, display.factor);
  const canManageSettings = access.isCompanyAdmin || access.can("inventory.transfer_policy.manage");
  const needsSetup = locations.some((location) => location.needsDestinationSetup);

  const openStage = (location: ProductQualityLocation, purpose: QualityDispatchPurpose) => {
    setActive({ kind: "stage", purpose, location });
    setQuantityInput(actionTotal(location.dispatch[purpose]));
    setReason("");
  };
  const openTerminal = (location: ProductQualityLocation, action: QualityTerminalAction) => {
    setActive({ kind: "terminal", action, location });
    setQuantityInput(actionTotal(location.terminal[action]));
    setReason(t("products.qualityInline.defaultDisposalConfirmationReason"));
    setMethod("");
    setEvidence("");
    setVendorName("");
    setVendorReference("");
    setHandoverReference("");
  };

  const submit = async () => {
    if (!active) return;
    let quantity: Quantity;
    try { quantity = parseQuantity(quantityInput, "quantity"); }
    catch { return; }
    if (active.kind === "stage") {
      if (!reason.trim()) return;
      const ok = await commands.stage({
        purpose: active.purpose,
        locationId: active.location.locationId,
        quantity,
        lines: active.location.dispatch[active.purpose],
        reason,
      });
      if (ok) setActive(null);
      return;
    }
    if (active.action === "CONFIRM_DISPOSAL") {
      const ok = await commands.confirmTerminal({
        action: active.action,
        locationId: active.location.locationId,
        quantity,
        lines: active.location.terminal[active.action],
        reason,
        method,
        evidenceReference: evidence,
      });
      if (ok) setActive(null);
      return;
    }
    if (!vendorName.trim() || !vendorReference.trim() || !handoverReference.trim()) return;
    const ok = await commands.confirmTerminal({
      action: active.action,
      locationId: active.location.locationId,
      quantity,
      lines: active.location.terminal[active.action],
      vendorName,
      vendorReference,
      handoverReference,
    });
    if (ok) setActive(null);
  };

  return <div className="space-y-3" dir={t("common.direction", { defaultValue: "rtl" })}>
    <div className="flex items-center justify-between gap-2">
      <button type="button" onClick={onBack} className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-black text-slate-700">
        <ArrowRight className="h-4 w-4" />{t("common.back")}
      </button>
      <h3 className="text-sm font-black text-slate-950">{t("products.qualityInline.title")}</h3>
    </div>

    {query.isLoading || !allLoaded ? <p role="status" className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs font-bold text-slate-500">{t("common.loading")}</p> : null}
    {query.isError ? <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs font-bold text-rose-800">{apiErrorMessage(query.error, t("products.qualityInline.errors.load"))}</div> : null}

    {!query.isLoading && allLoaded && !query.isError && locations.length === 0 ? <p className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs font-bold text-slate-500">{t("products.qualityInline.noStock")}</p> : null}

    {allLoaded && !query.isError ? <div className="space-y-2">
      {locations.map((location) => {
        const quantity = format(location.onHandQuantity);
        const disposal = actionTotal(location.dispatch.DISPOSAL);
        const vendor = actionTotal(location.dispatch.RETURN_TO_VENDOR);
        const confirmDisposal = actionTotal(location.terminal.CONFIRM_DISPOSAL);
        const confirmVendor = actionTotal(location.terminal.CONFIRM_VENDOR_HANDOVER);
        return <section key={location.locationId} className="rounded-xl border border-slate-200 bg-white p-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
              {location.locationType === "VEHICLE" ? <Truck className="h-4 w-4 text-slate-400" /> : <Warehouse className="h-4 w-4 text-slate-400" />}
              <div className="min-w-0">
                <p className="truncate text-xs font-black text-slate-950">{location.locationName}</p>
                <p className="mt-0.5 text-[10px] font-semibold text-slate-500">{quantity.primary}{quantity.secondary ? ` (${quantity.secondary})` : ""}</p>
              </div>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {compareQuantity(disposal, "0") > 0 ? <button type="button" onClick={() => openStage(location, "DISPOSAL")} disabled={commands.busyKey !== null} className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-rose-200 bg-rose-50 px-3 text-[10px] font-black text-rose-800 disabled:opacity-40"><Trash2 className="h-3.5 w-3.5" />{t("products.qualityInline.actions.dispose")}</button> : null}
              {compareQuantity(vendor, "0") > 0 ? <button type="button" onClick={() => openStage(location, "RETURN_TO_VENDOR")} disabled={commands.busyKey !== null} className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-sky-200 bg-sky-50 px-3 text-[10px] font-black text-sky-900 disabled:opacity-40"><Truck className="h-3.5 w-3.5" />{t("products.qualityInline.actions.returnVendor")}</button> : null}
              {compareQuantity(confirmDisposal, "0") > 0 ? <button type="button" onClick={() => openTerminal(location, "CONFIRM_DISPOSAL")} disabled={commands.busyKey !== null} className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-rose-700 px-3 text-[10px] font-black text-white disabled:opacity-40"><PackageCheck className="h-3.5 w-3.5" />{t("products.qualityInline.actions.confirmDisposal")}</button> : null}
              {compareQuantity(confirmVendor, "0") > 0 ? <button type="button" onClick={() => openTerminal(location, "CONFIRM_VENDOR_HANDOVER")} disabled={commands.busyKey !== null} className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-sky-700 px-3 text-[10px] font-black text-white disabled:opacity-40"><PackageCheck className="h-3.5 w-3.5" />{t("products.qualityInline.actions.confirmVendor")}</button> : null}
            </div>
          </div>
          {compareQuantity(location.reservedQuantity, "0") > 0 ? <p className="mt-2 text-[9px] font-semibold text-amber-700">{t("products.qualityInline.reserved", { quantity: format(location.reservedQuantity).primary })}</p> : null}
          {active?.location.locationId === location.locationId ? <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="text-[10px] font-black text-slate-700">{t("products.qualityInline.fields.quantity")}<input value={quantityInput} onChange={(event) => setQuantityInput(event.target.value)} inputMode="decimal" className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" /></label>
              {active.kind === "stage" || active.action === "CONFIRM_DISPOSAL" ? <label className="text-[10px] font-black text-slate-700">{t("products.qualityInline.fields.reason")}<input value={reason} onChange={(event) => setReason(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" /></label> : null}
              {active.kind === "terminal" && active.action === "CONFIRM_DISPOSAL" ? <>
                <label className="text-[10px] font-black text-slate-700">{t("products.qualityInline.fields.method")}<input value={method} onChange={(event) => setMethod(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" /></label>
                <label className="text-[10px] font-black text-slate-700">{t("products.qualityInline.fields.evidence")}<input value={evidence} onChange={(event) => setEvidence(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" /></label>
              </> : null}
              {active.kind === "terminal" && active.action === "CONFIRM_VENDOR_HANDOVER" ? <>
                <label className="text-[10px] font-black text-slate-700">{t("products.qualityInline.fields.vendorName")}<input value={vendorName} onChange={(event) => setVendorName(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" /></label>
                <label className="text-[10px] font-black text-slate-700">{t("products.qualityInline.fields.vendorReference")}<input value={vendorReference} onChange={(event) => setVendorReference(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" /></label>
                <label className="text-[10px] font-black text-slate-700 sm:col-span-2">{t("products.qualityInline.fields.handoverReference")}<input value={handoverReference} onChange={(event) => setHandoverReference(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" /></label>
              </> : null}
            </div>
            <div className="mt-3 flex justify-end gap-2"><button type="button" onClick={() => setActive(null)} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[10px] font-black">{t("common.cancel")}</button><button type="button" onClick={() => void submit()} disabled={commands.busyKey !== null} className="rounded-lg bg-slate-950 px-4 py-2 text-[10px] font-black text-white disabled:opacity-40">{t("common.confirm")}</button></div>
          </div> : null}
        </section>;
      })}
    </div> : null}

    {needsSetup ? <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-start gap-2"><AlertTriangle className="mt-0.5 h-4 w-4 text-amber-700" /><p className="text-[10px] font-bold leading-5 text-amber-900">{t("products.qualityInline.setupRequired")}</p></div>{canManageSettings ? <button type="button" onClick={() => setShowSetup((value) => !value)} className="rounded-lg border border-amber-300 bg-white px-3 py-2 text-[10px] font-black text-amber-900">{t(showSetup ? "common.close" : "products.qualityInline.setupNow")}</button> : null}</div>
      {showSetup ? <div className="mt-3"><QualityHandlingDestinationsCard compact onSaved={async () => { setShowSetup(false); await query.refetch(); }} /></div> : null}
    </div> : null}
  </div>;
}
