import { useEffect, useState } from "react";
import { Calculator, FlaskConical, Sparkles } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { offerPreview, taxPreview } from "./api";
import { useCatalogVariants, useOfferCatalogVariants, useTaxJurisdictions } from "./hooks";
import type { OfferPreview, TaxPreview } from "./contracts";

const positiveId = (value: string, label: string) => { const parsed = Number(value); if (!Number.isSafeInteger(parsed) || parsed <= 0) throw new Error(`${label} غير صالح.`); return parsed; };
const previewChannelCode = (value: string) => { const clean = value.trim().toUpperCase(); if (!/^[A-Z0-9][A-Z0-9_.:-]{0,49}$/.test(clean)) throw new Error("رمز القناة غير صالح."); return clean; };
const previewQuantity = (value: string) => {
  const clean = value.trim(); if (!/^\d+(?:\.\d+)?$/.test(clean) || /^0+(?:\.0+)?$/.test(clean)) throw new Error("الكمية يجب أن تكون أكبر من صفر.");
  const [wholeRaw, fractionRaw = ""] = clean.split("."); const whole = wholeRaw.replace(/^0+/, "") || "0"; const fraction = fractionRaw.replace(/0+$/, "");
  if (fraction.length > 6) throw new Error("الكمية لا تقبل أكثر من 6 منازل عشرية.");
  if (whole.length > 14) throw new Error("الكمية تتجاوز سعة NUMERIC(20,6).");
  return clean;
};

const previewTaxStableCode = (value: string, label: string, maximum: number) => {
  const clean = value.trim().toUpperCase(); if (!clean || clean.length > maximum || !/^[A-Z0-9][A-Z0-9_.:-]*$/.test(clean)) throw new Error(`${label} غير صالح.`); return clean;
};
const previewMoney = (value: string) => {
  const clean = value.trim(); if (!/^\d+(?:\.\d+)?$/.test(clean)) throw new Error("المبلغ يجب أن يكون رقماً عشرياً دقيقاً.");
  const [wholeRaw, fractionRaw = ""] = clean.split("."); const whole = wholeRaw.replace(/^0+/, "") || "0"; const fraction = fractionRaw.replace(/0+$/, "");
  if (fraction.length > 6) throw new Error("المبلغ لا يقبل أكثر من 6 منازل عشرية.");
  if (whole.length > 14) throw new Error("المبلغ يتجاوز سعة NUMERIC(20,6).");
  return clean;
};
export default function PreviewLab({ canOffers, canTax }: { canOffers: boolean; canTax: boolean }) {
  const authFetch = useAuthFetch(); const access = useInventoryAccess(); const catalogAvailable = access.isCompanyAdmin || access.canAny("catalog.read");
  const catalog = useCatalogVariants(catalogAvailable); const offerCatalog = useOfferCatalogVariants(catalogAvailable && canOffers); const jurisdictions = useTaxJurisdictions(canTax);
  const [mode, setMode] = useState<"offers" | "tax">(canOffers ? "offers" : "tax"); const [productId, setProductId] = useState(""); const [uomId, setUomId] = useState(""); const [quantity, setQuantity] = useState("1"); const [amount, setAmount] = useState("0.000000"); const [customerId, setCustomerId] = useState(""); const [branchId, setBranchId] = useState(""); const [channel, setChannel] = useState(""); const [jurisdictionId, setJurisdictionId] = useState(""); const [documentType, setDocumentType] = useState("SALE");
  const [offerResult, setOfferResult] = useState<OfferPreview | null>(null); const [taxResult, setTaxResult] = useState<TaxPreview | null>(null);
  useEffect(() => { if (mode === "offers" && !canOffers && canTax) setMode("tax"); if (mode === "tax" && !canTax && canOffers) setMode("offers"); if (mode !== "offers") setUomId(""); }, [canOffers, canTax, mode]);
  const mutation = useMutation({ mutationFn: async () => { const variant = positiveId(productId, "المنتج"); if (mode === "offers") return offerPreview(authFetch, { ...(customerId ? { customer_id: positiveId(customerId, "العميل") } : {}), ...(branchId ? { branch_id: positiveId(branchId, "الفرع") } : {}), ...(channel.trim() ? { channel_code: previewChannelCode(channel) } : {}), lines: [{ product_variant_id: variant, components: [{ uom_id: positiveId(uomId, "وحدة القياس"), quantity: previewQuantity(quantity) }] }] }); return taxPreview(authFetch, { jurisdiction_id: positiveId(jurisdictionId, "النطاق الضريبي"), ...(customerId ? { customer_id: positiveId(customerId, "العميل") } : {}), document_type_code: previewTaxStableCode(documentType, "نوع المستند", 80), lines: [{ line_id: 1, product_variant_id: variant, amount: previewMoney(amount) }] }); }, onSuccess: (result) => { if (mode === "offers") { setOfferResult(result as OfferPreview); setTaxResult(null); } else { setTaxResult(result as TaxPreview); setOfferResult(null); } toast.success("تمت المعاينة من المحرك الفعلي."); } });
  return <div className="commercial-rules-preview-grid">
    <section className="commercial-rules-panel commercial-rules-panel--preview-form"><div className="commercial-detail-title"><span className="commercial-detail-icon"><FlaskConical className="h-4 w-4" /></span><div><h2>مختبر Preview</h2><p>قراءة فقط — لا يكتب سجلًا ماليًا.</p></div></div>
      <div className="commercial-preview-mode">{canOffers ? <button data-active={mode === "offers"} onClick={() => setMode("offers")}>العروض</button> : null}{canTax ? <button data-active={mode === "tax"} onClick={() => setMode("tax")}>الضرائب</button> : null}</div>
      <div className="commercial-preview-form"><label><span>المنتج</span>{catalogAvailable ? <select value={productId} onChange={(e) => { const value = e.target.value; setProductId(value); if (mode === "offers") { const variant = offerCatalog.items.find((row) => String(row.id) === value); setUomId(variant ? String(variant.base_uom.id) : ""); } }}><option value="">اختر الصنف</option>{(mode === "offers" ? offerCatalog.items : catalog.items).map((row) => <option key={row.id} value={row.id}>{row.name} — {row.sku}</option>)}</select> : <input value={productId} onChange={(e) => setProductId(e.target.value)} placeholder="Product Variant ID" inputMode="numeric" dir="ltr" />}</label>
        {catalogAvailable && (mode === "offers" ? offerCatalog.hasNextPage : catalog.hasNextPage) ? <button className="commercial-load-more" disabled={mode === "offers" ? offerCatalog.isFetchingNextPage : catalog.isFetchingNextPage} onClick={() => void (mode === "offers" ? offerCatalog.fetchNextPage() : catalog.fetchNextPage())}>{(mode === "offers" ? offerCatalog.isFetchingNextPage : catalog.isFetchingNextPage) ? "جاري تحميل أصناف إضافية..." : "تحميل أصناف إضافية"}</button> : null}
        {mode === "offers" ? <><label><span>وحدة القياس</span>{catalogAvailable ? <select value={uomId} onChange={(e) => setUomId(e.target.value)} disabled={!productId}><option value="">اختر الوحدة</option>{offerCatalog.items.find((row) => String(row.id) === productId)?.uoms.map((uom) => <option key={uom.id} value={uom.id}>{uom.name} — {uom.code}</option>)}</select> : <input value={uomId} onChange={(e) => setUomId(e.target.value)} placeholder="UOM ID" inputMode="numeric" dir="ltr" />}</label><label><span>الكمية</span><input value={quantity} onChange={(e) => setQuantity(e.target.value)} inputMode="decimal" dir="ltr" /></label></> : <><label><span>المبلغ قبل الضريبة</span><input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" dir="ltr" /></label><label><span>النطاق الضريبي</span><select value={jurisdictionId} onChange={(e) => setJurisdictionId(e.target.value)}><option value="">اختر النطاق</option>{jurisdictions.items.filter((row) => row.is_active).map((row) => <option key={row.id} value={row.id}>{row.name} — {row.code}</option>)}</select></label><label><span>نوع المستند</span><input value={documentType} onChange={(e) => setDocumentType(e.target.value)} dir="ltr" /></label></>}
        <label><span>Customer ID — اختياري</span><input value={customerId} onChange={(e) => setCustomerId(e.target.value)} inputMode="numeric" dir="ltr" /></label>{mode === "offers" ? <><label><span>Branch ID — اختياري</span><input value={branchId} onChange={(e) => setBranchId(e.target.value)} inputMode="numeric" dir="ltr" /></label><label><span>Channel — اختياري</span><input value={channel} onChange={(e) => setChannel(e.target.value)} dir="ltr" /></label></> : null}
        <button className="commercial-primary-action commercial-preview-submit" disabled={mutation.isPending} onClick={() => mutation.mutate()}><Calculator className="h-4 w-4" /> {mutation.isPending ? "جاري الحساب..." : "تنفيذ المعاينة"}</button></div>
    </section>
    <section className="commercial-rules-panel commercial-rules-panel--preview-result">{!offerResult && !taxResult ? <div className="commercial-preview-empty"><Sparkles className="h-8 w-8" /><h3>النتيجة ستأتي من السيرفر</h3><p>لا يوجد أي تكرار لمنطق الأسعار أو العروض أو الضرائب داخل المتصفح.</p></div> : null}
      {offerResult ? <div className="commercial-preview-results custom-scrollbar"><div className="commercial-preview-totals"><div><small>قبل العروض</small><strong dir="ltr">{offerResult.gross_amount}</strong></div><div><small>الخصم</small><strong dir="ltr">{offerResult.discount_amount}</strong></div><div><small>بعد العروض</small><strong dir="ltr">{offerResult.net_amount}</strong></div></div><div className="commercial-result-section"><h3>العروض المطبقة</h3>{offerResult.applied_offers.map((row) => <div className="commercial-result-row" key={row.sequence}><span>{row.offer_type}</span><strong dir="ltr">-{row.discount_amount}</strong></div>)}{!offerResult.applied_offers.length ? <p className="commercial-empty">لا يوجد عرض مؤهل لهذه السلة.</p> : null}</div></div> : null}
      {taxResult ? <div className="commercial-preview-results custom-scrollbar"><div className="commercial-preview-totals"><div><small>الوعاء</small><strong dir="ltr">{taxResult.totals.taxable_base}</strong></div><div><small>الضريبة</small><strong dir="ltr">{taxResult.totals.tax_amount}</strong></div><div><small>الإجمالي</small><strong dir="ltr">{taxResult.totals.total_amount}</strong></div></div>{taxResult.lines.map((line) => <div className="commercial-result-section" key={line.line_id}><h3>سطر #{line.line_id} · Tax revision {line.resolution.tax_revision}</h3>{line.components.map((component) => <div className="commercial-result-row" key={component.tax_component_id}><span>{component.name} · {component.rate}%</span><strong dir="ltr">{component.tax_amount}</strong></div>)}</div>)}</div> : null}
    </section>
  </div>;
}
