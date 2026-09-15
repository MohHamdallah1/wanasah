import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import type { CatalogVariant, TaxJurisdiction, TaxRuleSet, TaxScopeType, TaxVersion } from "../contracts";
import { buildTaxVersionPayload, emptyTaxVersionForm, taxVersionToForm, type TaxVersionForm } from "../formUtils";
import { EditorDialog, EditorField, editorInputClass, editorSelectClass } from "../EditorDialog";

const positiveOptionalId = (value: string, label: string) => {
  if (!value.trim()) return null;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) throw new Error(`${label} غير صالح.`);
  return parsed;
};
const stableTaxCode = (value: string, label: string, maximum: number) => {
  const clean = value.trim().toUpperCase();
  if (!clean || clean.length > maximum || !/^[A-Z0-9][A-Z0-9_.:-]*$/.test(clean)) throw new Error(`${label} غير صالح.`);
  return clean;
};
const requiredTaxText = (value: string, label: string, maximum: number) => {
  const clean = value.trim();
  if (!clean || clean.length > maximum) throw new Error(`${label} غير صالح.`);
  return clean;
};
const countryTaxCode = (value: string) => {
  const clean = value.trim().toUpperCase();
  if (!/^[A-Z]{2,3}$/.test(clean)) throw new Error("كود الدولة يجب أن يكون حرفين أو 3 أحرف إنجليزية.");
  return clean;
};

export function TaxJurisdictionEditor({ open, jurisdiction, jurisdictions, pending, onClose, onSave }: {
  open: boolean; jurisdiction: TaxJurisdiction | null; jurisdictions: TaxJurisdiction[]; pending: boolean; onClose: () => void; onSave: (input: Record<string, unknown>) => void;
}) {
  const [form, setForm] = useState({ code: "", name: "", jurisdiction_type: "COUNTRY" as TaxJurisdiction["jurisdiction_type"], country_code: "", subdivision_code: "", locality_code: "", parent_jurisdiction_id: "", is_active: true });
  useEffect(() => { if (open) setForm({ code: jurisdiction?.code ?? "", name: jurisdiction?.name ?? "", jurisdiction_type: jurisdiction?.jurisdiction_type ?? "COUNTRY", country_code: jurisdiction?.country_code ?? "", subdivision_code: jurisdiction?.subdivision_code ?? "", locality_code: jurisdiction?.locality_code ?? "", parent_jurisdiction_id: jurisdiction?.parent_jurisdiction_id == null ? "" : String(jurisdiction.parent_jurisdiction_id), is_active: jurisdiction?.is_active ?? true }); }, [jurisdiction, open]);
  const submit = () => {
    const code = stableTaxCode(form.code, "كود النطاق", 100); const name = requiredTaxText(form.name, "اسم النطاق", 150); const countryCode = countryTaxCode(form.country_code);
    const subdivisionCode = form.subdivision_code.trim() ? stableTaxCode(form.subdivision_code, "كود التقسيم الإداري", 50) : null;
    const localityCode = form.locality_code.trim() ? stableTaxCode(form.locality_code, "كود المنطقة المحلية", 100) : null;
    const parentId = positiveOptionalId(form.parent_jurisdiction_id, "النطاق الأب");
    if (form.jurisdiction_type === "COUNTRY" && (parentId !== null || subdivisionCode !== null || localityCode !== null)) throw new Error("نطاق الدولة لا يقبل نطاقاً أب أو أكواد تقسيم/منطقة.");
    if (form.jurisdiction_type === "SUBDIVISION" && (parentId === null || subdivisionCode === null || localityCode !== null)) throw new Error("التقسيم الإداري يحتاج نطاقاً أب وكود تقسيم فقط.");
    if (form.jurisdiction_type === "LOCALITY" && (parentId === null || localityCode === null)) throw new Error("المنطقة المحلية تحتاج نطاقاً أب وكود منطقة.");
    const normalized = { code, name, jurisdiction_type: form.jurisdiction_type, country_code: countryCode, subdivision_code: subdivisionCode, locality_code: localityCode, parent_jurisdiction_id: parentId };
    if (!jurisdiction) { onSave(normalized); return; }
    const input: Record<string, unknown> = {};
    if (code !== jurisdiction.code) input.code = code;
    if (name !== jurisdiction.name) input.name = name;
    if (form.jurisdiction_type !== jurisdiction.jurisdiction_type) input.jurisdiction_type = form.jurisdiction_type;
    if (countryCode !== jurisdiction.country_code) input.country_code = countryCode;
    if (subdivisionCode !== jurisdiction.subdivision_code) input.subdivision_code = subdivisionCode;
    if (localityCode !== jurisdiction.locality_code) input.locality_code = localityCode;
    if (parentId !== jurisdiction.parent_jurisdiction_id) input.parent_jurisdiction_id = parentId;
    if (form.is_active !== jurisdiction.is_active) input.is_active = form.is_active;
    if (!Object.keys(input).length) throw new Error("لا توجد تغييرات للحفظ.");
    onSave(input);
  };
  return <EditorDialog open={open} onClose={onClose} title={jurisdiction ? "تعديل النطاق الضريبي" : "نطاق ضريبي جديد"} subtitle="العلاقات الهرمية tenant-scoped ويتحقق منها السيرفر وقاعدة البيانات."
    footer={<><button className="commercial-editor-button commercial-editor-button--ghost" onClick={onClose}>إلغاء</button><button className="commercial-editor-button commercial-editor-button--primary" disabled={pending} onClick={() => { try { submit(); } catch (error) { toast.error(error instanceof Error ? error.message : "بيانات النطاق غير صالحة."); } }}>{pending ? "جاري الحفظ..." : "حفظ النطاق"}</button></>}>
    <div className="commercial-editor-grid commercial-editor-grid--3"><EditorField label="الكود"><input className={editorInputClass} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} dir="ltr" /></EditorField><EditorField label="الاسم"><input className={editorInputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></EditorField><EditorField label="النوع"><select className={editorSelectClass} value={form.jurisdiction_type} onChange={(e) => { const type = e.target.value as TaxJurisdiction["jurisdiction_type"]; setForm({ ...form, jurisdiction_type: type, parent_jurisdiction_id: type === "COUNTRY" ? "" : form.parent_jurisdiction_id, subdivision_code: type === "COUNTRY" ? "" : form.subdivision_code, locality_code: ["COUNTRY", "SUBDIVISION"].includes(type) ? "" : form.locality_code }); }}><option value="COUNTRY">دولة</option><option value="SUBDIVISION">تقسيم إداري</option><option value="LOCALITY">منطقة محلية</option><option value="CUSTOM">مخصص</option></select></EditorField></div>
    <div className="commercial-editor-grid commercial-editor-grid--3"><EditorField label="Country code"><input className={editorInputClass} value={form.country_code} onChange={(e) => setForm({ ...form, country_code: e.target.value })} maxLength={3} dir="ltr" /></EditorField><EditorField label="Subdivision code"><input className={editorInputClass} value={form.subdivision_code} disabled={form.jurisdiction_type === "COUNTRY"} onChange={(e) => setForm({ ...form, subdivision_code: e.target.value })} dir="ltr" /></EditorField><EditorField label="Locality code"><input className={editorInputClass} value={form.locality_code} disabled={["COUNTRY", "SUBDIVISION"].includes(form.jurisdiction_type)} onChange={(e) => setForm({ ...form, locality_code: e.target.value })} dir="ltr" /></EditorField></div>
    {form.jurisdiction_type !== "COUNTRY" ? <EditorField label="النطاق الأب"><select className={editorSelectClass} value={form.parent_jurisdiction_id} onChange={(e) => setForm({ ...form, parent_jurisdiction_id: e.target.value })}><option value="">اختر النطاق الأب</option>{jurisdictions.filter((row) => row.id !== jurisdiction?.id && row.is_active).map((row) => <option key={row.id} value={row.id}>{row.name} — {row.code}</option>)}</select></EditorField> : null}
    {jurisdiction ? <label className="commercial-editor-check"><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /><span>النطاق نشط</span></label> : null}
  </EditorDialog>;
}

export function TaxRuleSetEditor({ open, ruleSet, pending, onClose, onSave }: { open: boolean; ruleSet: TaxRuleSet | null; pending: boolean; onClose: () => void; onSave: (input: { code: string; name: string; description: string | null }) => void }) {
  const [code, setCode] = useState(""); const [name, setName] = useState(""); const [description, setDescription] = useState("");
  useEffect(() => { if (open) { setCode(ruleSet?.code ?? ""); setName(ruleSet?.name ?? ""); setDescription(ruleSet?.description ?? ""); } }, [open, ruleSet]);
  return <EditorDialog open={open} onClose={onClose} title={ruleSet ? "تعديل مجموعة القواعد" : "مجموعة ضريبية جديدة"} subtitle="المجموعة هوية ثابتة، والتغييرات الفعلية تتم عبر نسخ مؤرخة."
    footer={<><button className="commercial-editor-button commercial-editor-button--ghost" onClick={onClose}>إلغاء</button><button className="commercial-editor-button commercial-editor-button--primary" disabled={pending} onClick={() => { try { const cleanCode = stableTaxCode(code, "كود المجموعة", 100); const cleanName = requiredTaxText(name, "اسم المجموعة", 150); const cleanDescription = description.trim(); if (cleanDescription.length > 2000) throw new Error("الوصف يتجاوز 2000 حرف."); onSave({ code: cleanCode, name: cleanName, description: cleanDescription || null }); } catch (error) { toast.error(error instanceof Error ? error.message : "بيانات المجموعة غير صالحة."); } }}>{pending ? "جاري الحفظ..." : "حفظ المجموعة"}</button></>}>
    <div className="commercial-editor-grid commercial-editor-grid--2"><EditorField label="الكود"><input className={editorInputClass} value={code} onChange={(e) => setCode(e.target.value)} dir="ltr" /></EditorField><EditorField label="الاسم"><input className={editorInputClass} value={name} onChange={(e) => setName(e.target.value)} /></EditorField></div><EditorField label="الوصف"><textarea className={`${editorInputClass} min-h-24 resize-y`} value={description} onChange={(e) => setDescription(e.target.value)} /></EditorField>
  </EditorDialog>;
}

function VariantTarget({ value, onChange, variants, catalogAvailable }: { value: string; onChange: (value: string) => void; variants: CatalogVariant[]; catalogAvailable: boolean }) {
  if (!catalogAvailable) return <input className={editorInputClass} value={value} onChange={(e) => onChange(e.target.value)} inputMode="numeric" placeholder="Product Variant ID" dir="ltr" />;
  return <select className={editorSelectClass} value={value} onChange={(e) => onChange(e.target.value)}><option value="">اختر الصنف</option>{variants.map((row) => <option key={row.id} value={row.id}>{row.name} — {row.sku}</option>)}</select>;
}

export function TaxVersionEditor({ open, ruleSet, version, jurisdictions, variants, catalogAvailable, hasMoreVariants, loadingMoreVariants, onLoadMoreVariants, pending, onClose, onSave }: {
  open: boolean; ruleSet: TaxRuleSet | null; version: TaxVersion | null; jurisdictions: TaxJurisdiction[]; variants: CatalogVariant[]; catalogAvailable: boolean;
  hasMoreVariants: boolean; loadingMoreVariants: boolean; onLoadMoreVariants: () => void; pending: boolean; onClose: () => void; onSave: (payload: Record<string, unknown>) => void;
}) {
  const [form, setForm] = useState<TaxVersionForm>(emptyTaxVersionForm());
  useEffect(() => { if (open) setForm(version ? taxVersionToForm(version) : emptyTaxVersionForm()); }, [open, version]);
  const set = <K extends keyof TaxVersionForm>(key: K, value: TaxVersionForm[K]) => setForm((current) => ({ ...current, [key]: value }));
  return <EditorDialog open={open} onClose={onClose} title={version ? "تعديل النسخة الضريبية المسودة" : `نسخة ضريبية جديدة — ${ruleSet?.name ?? ""}`} subtitle="ترتيب المكونات هو ترتيب الحساب؛ المكوّن الأول دائمًا TAXABLE_BASE."
    footer={<><button className="commercial-editor-button commercial-editor-button--ghost" onClick={onClose}>إلغاء</button><button className="commercial-editor-button commercial-editor-button--primary" disabled={pending} onClick={() => { try { onSave(buildTaxVersionPayload(form)); } catch (error) { toast.error(error instanceof Error ? error.message : "إعدادات الضريبة غير صالحة."); } }}>{pending ? "جاري الحفظ..." : version ? "حفظ المسودة" : "إنشاء المسودة"}</button></>}>
    <div className="commercial-editor-grid commercial-editor-grid--4"><EditorField label="الأولوية"><input className={editorInputClass} value={form.priority} onChange={(e) => set("priority", e.target.value)} inputMode="numeric" dir="ltr" /></EditorField><EditorField label="وضع السعر"><select className={editorSelectClass} value={form.price_mode} onChange={(e) => set("price_mode", e.target.value as TaxVersionForm["price_mode"])}><option value="EXCLUSIVE">غير شامل الضريبة</option><option value="INCLUSIVE">شامل الضريبة</option></select></EditorField><EditorField label="يبدأ من"><input type="datetime-local" className={editorInputClass} value={form.effective_from} onChange={(e) => set("effective_from", e.target.value)} /></EditorField><EditorField label="ينتهي في — اختياري"><input type="datetime-local" className={editorInputClass} value={form.effective_to} onChange={(e) => set("effective_to", e.target.value)} /></EditorField></div>
    <div className="commercial-editor-section"><div className="commercial-editor-section-head"><div><strong>مكونات الضريبة</strong><small>sequence متصل تلقائيًا من 1؛ لا يمكن كسره.</small></div><button type="button" className="commercial-editor-mini" onClick={() => set("components", [...form.components, { component_code: "", name: "", rate: "0", basis_mode: "TAXABLE_BASE", reporting_code: "" }])}><Plus className="h-3.5 w-3.5" /> مكوّن</button></div><div className="space-y-2">{form.components.map((component, index) => <div key={index} className="commercial-editor-row commercial-editor-row--tax"><span className="commercial-editor-sequence">#{index + 1}</span><input className={editorInputClass} value={component.component_code} onChange={(e) => set("components", form.components.map((row, i) => i === index ? { ...row, component_code: e.target.value } : row))} placeholder="VAT" dir="ltr" /><input className={editorInputClass} value={component.name} onChange={(e) => set("components", form.components.map((row, i) => i === index ? { ...row, name: e.target.value } : row))} placeholder="اسم الضريبة" /><input className={editorInputClass} value={component.rate} onChange={(e) => set("components", form.components.map((row, i) => i === index ? { ...row, rate: e.target.value } : row))} inputMode="decimal" dir="ltr" /><select className={editorSelectClass} value={index === 0 ? "TAXABLE_BASE" : component.basis_mode} disabled={index === 0} onChange={(e) => set("components", form.components.map((row, i) => i === index ? { ...row, basis_mode: e.target.value as typeof row.basis_mode } : row))}><option value="TAXABLE_BASE">Taxable base</option><option value="TAXABLE_BASE_PLUS_PRIOR_TAX">Base + prior tax</option></select><input className={editorInputClass} value={component.reporting_code} onChange={(e) => set("components", form.components.map((row, i) => i === index ? { ...row, reporting_code: e.target.value } : row))} placeholder="Reporting code" dir="ltr" /><button type="button" className="commercial-editor-icon-button" disabled={form.components.length === 1} onClick={() => set("components", form.components.filter((_, i) => i !== index))}><Trash2 className="h-4 w-4" /></button></div>)}</div></div>
    <div className="commercial-editor-section"><div className="commercial-editor-section-head"><div><strong>نطاقات القاعدة</strong><small>القيم داخل النوع OR والأنواع المختلفة AND.</small></div><button type="button" className="commercial-editor-mini" onClick={() => set("scopes", [...form.scopes, { scope_type: "JURISDICTION", target: "" }])}><Plus className="h-3.5 w-3.5" /> نطاق</button></div><div className="space-y-2">{form.scopes.map((scope, index) => <div key={index} className="commercial-editor-row"><select className={editorSelectClass} value={scope.scope_type} onChange={(e) => set("scopes", form.scopes.map((row, i) => i === index ? { scope_type: e.target.value as TaxScopeType, target: "" } : row))}><option value="JURISDICTION">نطاق ضريبي</option><option value="PRODUCT_VARIANT">منتج</option><option value="CUSTOMER">عميل</option><option value="DOCUMENT_TYPE">نوع مستند</option></select>{scope.scope_type === "JURISDICTION" ? <select className={editorSelectClass} value={scope.target} onChange={(e) => set("scopes", form.scopes.map((row, i) => i === index ? { ...row, target: e.target.value } : row))}><option value="">اختر النطاق</option>{jurisdictions.filter((row) => row.is_active).map((row) => <option key={row.id} value={row.id}>{row.name} — {row.code}</option>)}</select> : scope.scope_type === "PRODUCT_VARIANT" ? <VariantTarget value={scope.target} variants={variants} catalogAvailable={catalogAvailable} onChange={(value) => set("scopes", form.scopes.map((row, i) => i === index ? { ...row, target: value } : row))} /> : <input className={editorInputClass} value={scope.target} onChange={(e) => set("scopes", form.scopes.map((row, i) => i === index ? { ...row, target: e.target.value } : row))} placeholder={scope.scope_type === "DOCUMENT_TYPE" ? "SALE" : "Customer ID"} dir="ltr" />}<button type="button" className="commercial-editor-icon-button" onClick={() => set("scopes", form.scopes.filter((_, i) => i !== index))}><Trash2 className="h-4 w-4" /></button></div>)}</div></div>
    {catalogAvailable && hasMoreVariants ? <button type="button" className="commercial-load-more" disabled={loadingMoreVariants} onClick={onLoadMoreVariants}>{loadingMoreVariants ? "جاري تحميل أصناف إضافية..." : "تحميل أصناف إضافية"}</button> : null}
  </EditorDialog>;
}
