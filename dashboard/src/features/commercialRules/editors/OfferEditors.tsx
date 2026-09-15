import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { CheckCircle2, ChevronLeft, ChevronRight, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import type { OfferCatalogVariant, OfferDefinition, OfferProductRole, OfferScopeType, OfferType, OfferVersion } from "../contracts";
import { buildOfferVersionPayload, emptyOfferVersionForm, offerVersionToForm, type OfferVersionForm } from "../formUtils";
import { EditorDialog, EditorField, editorInputClass, editorSelectClass } from "../EditorDialog";

export function OfferDefinitionEditor({ open, definition, pending, onClose, onSave }: {
  open: boolean; definition: OfferDefinition | null; pending: boolean; onClose: () => void;
  onSave: (input: { code: string; name: string; description: string | null }) => void;
}) {
  const [code, setCode] = useState(""); const [name, setName] = useState(""); const [description, setDescription] = useState("");
  useEffect(() => { if (open) { setCode(definition?.code ?? ""); setName(definition?.name ?? ""); setDescription(definition?.description ?? ""); } }, [definition, open]);
  return <EditorDialog open={open} onClose={onClose} title={definition ? "تعديل تعريف العرض" : "إنشاء عرض جديد"} subtitle="التعريف هو الهوية الثابتة؛ قواعد التنفيذ توضع داخل النسخ."
    footer={<><button className="commercial-editor-button commercial-editor-button--ghost" onClick={onClose}>إلغاء</button><button className="commercial-editor-button commercial-editor-button--primary" disabled={pending} onClick={() => { try { const cleanCode = code.trim().toUpperCase(); const cleanName = name.trim(); if (!cleanCode || !cleanName) throw new Error("كود واسم العرض مطلوبان."); onSave({ code: cleanCode, name: cleanName, description: description.trim() || null }); } catch (error) { toast.error(error instanceof Error ? error.message : "بيانات العرض غير صالحة."); } }}>{pending ? "جاري الحفظ..." : "حفظ التعريف"}</button></>}>
    <div className="commercial-editor-grid commercial-editor-grid--2"><EditorField label="الكود الثابت"><input className={editorInputClass} value={code} onChange={(e) => setCode(e.target.value)} maxLength={100} dir="ltr" /></EditorField><EditorField label="اسم العرض"><input className={editorInputClass} value={name} onChange={(e) => setName(e.target.value)} maxLength={150} /></EditorField></div>
    <EditorField label="الوصف"><textarea className={`${editorInputClass} min-h-24 resize-y`} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} /></EditorField>
  </EditorDialog>;
}

function VariantTarget({ value, onChange, variants, catalogAvailable }: { value: string; onChange: (value: string) => void; variants: OfferCatalogVariant[]; catalogAvailable: boolean }) {
  if (!catalogAvailable) return <input className={editorInputClass} value={value} onChange={(e) => onChange(e.target.value)} inputMode="numeric" placeholder="Product Variant ID" dir="ltr" />;
  return <select className={editorSelectClass} value={value} onChange={(e) => onChange(e.target.value)}><option value="">اختر الصنف</option>{variants.map((row) => <option key={row.id} value={row.id}>{row.name} — {row.sku}</option>)}</select>;
}

function UomTarget({ variantId, value, onChange, variants, catalogAvailable, allowAny = false }: { variantId: string; value: string; onChange: (value: string) => void; variants: OfferCatalogVariant[]; catalogAvailable: boolean; allowAny?: boolean }) {
  if (!catalogAvailable) return <input className={editorInputClass} value={value} readOnly disabled placeholder={allowAny ? "كل الوحدات" : "اختيار الوحدة يتطلب صلاحية قراءة الكتالوج"} aria-label="وحدة القياس" dir="ltr" />;
  const variant = variants.find((row) => String(row.id) === variantId);
  return <select className={editorSelectClass} value={value} onChange={(e) => onChange(e.target.value)} disabled={!variantId || !variant}><option value="">{allowAny ? "كل الوحدات" : variantId ? "اختر الوحدة" : "اختر الصنف أولاً"}</option>{variant?.uoms.map((uom) => <option key={uom.id} value={uom.id}>{uom.name} — {uom.code}</option>)}</select>;
}

function PayloadFields({ form, setForm }: { form: OfferVersionForm; setForm: Dispatch<SetStateAction<OfferVersionForm>> }) {
  const set = <K extends keyof OfferVersionForm>(key: K, value: OfferVersionForm[K]) => setForm((current) => ({ ...current, [key]: value }));
  if (form.offer_type === "PERCENTAGE_DISCOUNT") return <EditorField label="نسبة الخصم %"><input className={editorInputClass} value={form.percentage} onChange={(e) => set("percentage", e.target.value)} inputMode="decimal" dir="ltr" /></EditorField>;
  if (form.offer_type === "FIXED_DISCOUNT") return <EditorField label="قيمة الخصم الثابت"><input className={editorInputClass} value={form.fixed_amount} onChange={(e) => set("fixed_amount", e.target.value)} inputMode="decimal" dir="ltr" /></EditorField>;
  if (form.offer_type === "BUY_X_GET_Y") return <EditorField label="كمية الشراء المؤهلة" hint="تُقاس بوحدة المنتجات المؤهلة؛ كل المكافآت تحدد كميتها في صفها أدناه."><input className={editorInputClass} value={form.buy_quantity} onChange={(e) => set("buy_quantity", e.target.value)} inputMode="decimal" dir="ltr" /></EditorField>;
  if (form.offer_type === "FREE_GOODS") return <EditorField label="الكمية المؤهلة" hint="تُقاس بوحدة المنتجات المؤهلة؛ كل مكافأة لها وحدتها وكميتها الخاصة."><input className={editorInputClass} value={form.qualifying_quantity} onChange={(e) => set("qualifying_quantity", e.target.value)} inputMode="decimal" dir="ltr" /></EditorField>;
  if (form.offer_type === "QUANTITY_TIERS") return <div className="commercial-editor-section"><div className="commercial-editor-section-head"><div><strong>شرائح الكمية</strong><small>الحدود تصاعدية وبدون تكرار.</small></div><button className="commercial-editor-mini" type="button" onClick={() => set("tiers", [...form.tiers, { minimum_quantity: "", reward_type: "PERCENTAGE_DISCOUNT", reward_value: "" }])}><Plus className="h-3.5 w-3.5" /> شريحة</button></div><div className="space-y-2">{form.tiers.map((tier, index) => <div key={index} className="commercial-editor-row commercial-editor-row--tier"><input className={editorInputClass} value={tier.minimum_quantity} onChange={(e) => set("tiers", form.tiers.map((row, i) => i === index ? { ...row, minimum_quantity: e.target.value } : row))} placeholder="من كمية" inputMode="decimal" dir="ltr" /><select className={editorSelectClass} value={tier.reward_type} onChange={(e) => set("tiers", form.tiers.map((row, i) => i === index ? { ...row, reward_type: e.target.value as typeof row.reward_type } : row))}><option value="PERCENTAGE_DISCOUNT">خصم نسبي</option><option value="FIXED_DISCOUNT">خصم ثابت</option><option value="FREE_QUANTITY">كمية مجانية</option></select><input className={editorInputClass} value={tier.reward_value} onChange={(e) => set("tiers", form.tiers.map((row, i) => i === index ? { ...row, reward_value: e.target.value } : row))} placeholder="القيمة" inputMode="decimal" dir="ltr" /><button type="button" className="commercial-editor-icon-button" disabled={form.tiers.length === 1} onClick={() => set("tiers", form.tiers.filter((_, i) => i !== index))}><Trash2 className="h-4 w-4" /></button></div>)}</div></div>;
  return <div className="commercial-editor-grid commercial-editor-grid--2"><EditorField label="نوع مكافأة الحزمة"><select className={editorSelectClass} value={form.bundle_reward_type} onChange={(e) => set("bundle_reward_type", e.target.value as OfferVersionForm["bundle_reward_type"])}><option value="PERCENTAGE_DISCOUNT">خصم نسبي</option><option value="FIXED_DISCOUNT">خصم ثابت</option><option value="FIXED_PRICE">سعر حزمة ثابت</option></select></EditorField><EditorField label="قيمة مكافأة الحزمة"><input className={editorInputClass} value={form.bundle_reward_value} onChange={(e) => set("bundle_reward_value", e.target.value)} inputMode="decimal" dir="ltr" /></EditorField></div>;
}

const roleLabel: Record<OfferProductRole, string> = {
  QUALIFYING: "منتج مؤهل",
  REWARD: "منتج مكافأة",
  BUNDLE_COMPONENT: "مكوّن حزمة",
};

const offerTypeOptions: Array<{ value: OfferType; label: string; description: string }> = [
  { value: "PERCENTAGE_DISCOUNT", label: "خصم نسبي", description: "نسبة مئوية على الأصناف أو النطاق المختار." },
  { value: "FIXED_DISCOUNT", label: "خصم ثابت", description: "قيمة مالية ثابتة وفق نطاق العرض." },
  { value: "BUY_X_GET_Y", label: "اشترِ X وخذ Y", description: "منتج أو مجموعة مؤهلة مع مكافأة واحدة أو أكثر." },
  { value: "FREE_GOODS", label: "بضاعة مجانية", description: "تأهيل بالكمية ثم صرف منتجات مكافأة بوحداتها." },
  { value: "QUANTITY_TIERS", label: "شرائح كمية", description: "مكافأة تتغير عند بلوغ حدود كمية تصاعدية." },
  { value: "BUNDLE", label: "حزمة", description: "عدة مكوّنات بكميات ووحدات صريحة مع مكافأة للحزمة." },
];

const wizardSteps = [
  { id: "type", label: "نوع العرض" },
  { id: "products", label: "الأصناف والوحدات" },
  { id: "terms", label: "الشروط والحدود" },
  { id: "commercial", label: "التوقيت التجاري" },
  { id: "scopes", label: "نطاقات إضافية" },
  { id: "review", label: "المراجعة" },
] as const;

const blankProduct = (role: OfferProductRole): OfferVersionForm["products"][number] => ({
  role,
  product_variant_id: "",
  uom_id: "",
  quantity_per_application: "",
});

const blankProductScope = (): OfferVersionForm["scopes"][number] => ({
  scope_type: "PRODUCT_VARIANT",
  target: "",
  uom_id: "",
});

const initialStructureForType = (offerType: OfferType): Pick<OfferVersionForm, "products" | "scopes"> => {
  if (["BUY_X_GET_Y", "FREE_GOODS"].includes(offerType)) {
    return { products: [blankProduct("QUALIFYING"), blankProduct("REWARD")], scopes: [] };
  }
  if (offerType === "BUNDLE") {
    return { products: [blankProduct("BUNDLE_COMPONENT"), blankProduct("BUNDLE_COMPONENT")], scopes: [] };
  }
  if (offerType === "QUANTITY_TIERS") {
    return { products: [], scopes: [blankProductScope()] };
  }
  return { products: [], scopes: [] };
};

const benefitSummary = (form: OfferVersionForm) => {
  switch (form.offer_type) {
    case "PERCENTAGE_DISCOUNT": return `${form.percentage || "—"}% خصم`;
    case "FIXED_DISCOUNT": return `${form.fixed_amount || "—"} ${form.currency_code || "عملة غير محددة"}`;
    case "BUY_X_GET_Y": return `كل ${form.buy_quantity || "—"} من مجموعة التأهيل → المكافآت المحددة`;
    case "FREE_GOODS": return `كل ${form.qualifying_quantity || "—"} من مجموعة التأهيل → بضاعة مجانية`;
    case "QUANTITY_TIERS": return `${form.tiers.length} شريحة كمية`;
    case "BUNDLE": return `${form.bundle_reward_type === "PERCENTAGE_DISCOUNT" ? "خصم" : form.bundle_reward_type === "FIXED_DISCOUNT" ? "خصم ثابت" : "سعر ثابت"} ${form.bundle_reward_value || "—"}`;
  }
};

const validateOfferReferences = (form: OfferVersionForm, variantById: Map<string, OfferCatalogVariant>, catalogAvailable: boolean): string | null => {
  if (!catalogAvailable) return null;
  for (const product of form.products) {
    const variant = variantById.get(product.product_variant_id);
    if (!variant) return `تعذر تحميل مرجع الصنف #${product.product_variant_id}.`;
    if (!variant.uoms.some((uom) => String(uom.id) === product.uom_id)) return `وحدة القياس المحددة للصنف ${variant.name} لم تعد صالحة لهذا الصنف.`;
  }
  for (const scope of form.scopes) {
    if (scope.scope_type !== "PRODUCT_VARIANT") continue;
    const variant = variantById.get(scope.target);
    if (!variant) return `تعذر تحميل مرجع الصنف #${scope.target}.`;
    if (scope.uom_id && !variant.uoms.some((uom) => String(uom.id) === scope.uom_id)) return `وحدة القياس المحددة لنطاق الصنف ${variant.name} لم تعد صالحة لهذا الصنف.`;
  }
  return null;
};

export function OfferVersionEditor({ open, definition, version, variants, catalogAvailable, hasMoreVariants, loadingMoreVariants, onLoadMoreVariants, pending, onClose, onSave }: {
  open: boolean; definition: OfferDefinition | null; version: OfferVersion | null; variants: OfferCatalogVariant[]; catalogAvailable: boolean;
  hasMoreVariants: boolean; loadingMoreVariants: boolean; onLoadMoreVariants: () => void; pending: boolean; onClose: () => void; onSave: (payload: Record<string, unknown>) => void;
}) {
  const [form, setForm] = useState<OfferVersionForm>(emptyOfferVersionForm());
  const [stepIndex, setStepIndex] = useState(0);

  useEffect(() => {
    if (!open) return;
    setForm(version ? offerVersionToForm(version) : emptyOfferVersionForm());
    setStepIndex(0);
  }, [open, version]);

  const set = <K extends keyof OfferVersionForm>(key: K, value: OfferVersionForm[K]) => setForm((current) => ({ ...current, [key]: value }));
  const isCrossProductReward = ["BUY_X_GET_Y", "FREE_GOODS"].includes(form.offer_type);
  const productRows = useMemo(() => form.products.map((product, index) => ({ product, index })), [form.products]);
  const qualifyingRows = productRows.filter(({ product }) => product.role === "QUALIFYING");
  const rewardRows = productRows.filter(({ product }) => product.role === "REWARD");
  const bundleRows = productRows.filter(({ product }) => product.role === "BUNDLE_COMPONENT");
  const scopeRows = useMemo(() => form.scopes.map((scope, index) => ({ scope, index })), [form.scopes]);
  const productScopes = scopeRows.filter(({ scope }) => scope.scope_type === "PRODUCT_VARIANT");
  const nonProductScopes = scopeRows.filter(({ scope }) => scope.scope_type !== "PRODUCT_VARIANT");
  const variantById = useMemo(() => new Map(variants.map((row) => [String(row.id), row])), [variants]);
  const selectedType = offerTypeOptions.find((option) => option.value === form.offer_type) ?? offerTypeOptions[0];

  const reviewValidation = useMemo(() => {
  try {
    const payload = buildOfferVersionPayload(form);
    const referenceError = validateOfferReferences(form, variantById, catalogAvailable);
    return referenceError ? { payload: null, error: referenceError } : { payload, error: null as string | null };
  } catch (error) {
    return { payload: null, error: error instanceof Error ? error.message : "إعدادات العرض غير صالحة." };
  }
}, [catalogAvailable, form, variantById]);

  const changeOfferType = (offerType: OfferType) => {
    if (offerType === form.offer_type) return;
    const structure = initialStructureForType(offerType);
    setForm((current) => ({
      ...current,
      offer_type: offerType,
      products: structure.products,
      scopes: structure.scopes,
      max_reward_quantity: "",
    }));
  };

  const updateProduct = (index: number, patch: Partial<OfferVersionForm["products"][number]>) => {
    setForm((current) => ({
      ...current,
      products: current.products.map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row),
    }));
  };

  const removeProduct = (index: number) => {
    setForm((current) => ({ ...current, products: current.products.filter((_, rowIndex) => rowIndex !== index) }));
  };

  const updateScope = (index: number, patch: Partial<OfferVersionForm["scopes"][number]>) => {
    setForm((current) => ({
      ...current,
      scopes: current.scopes.map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row),
    }));
  };

  const removeScope = (index: number) => {
    setForm((current) => ({ ...current, scopes: current.scopes.filter((_, rowIndex) => rowIndex !== index) }));
  };

  const variantLabel = (variantId: string) => {
    const variant = variantById.get(variantId);
    return variant ? `${variant.name} — ${variant.sku}` : variantId ? `Variant #${variantId}` : "غير محدد";
  };

  const uomLabel = (variantId: string, uomId: string, allowAny = false) => {
    if (!uomId) return allowAny ? "كل الوحدات" : "غير محددة";
    const uom = variantById.get(variantId)?.uoms.find((row) => String(row.id) === uomId);
    return uom ? `${uom.name} — ${uom.code}` : `UOM #${uomId}`;
  };

  const renderProductScopeRows = (required: boolean) => (
    <div className="space-y-2">
      {productScopes.map(({ scope, index }) => (
        <div key={index} className="grid gap-2 md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_auto]">
          <VariantTarget
            value={scope.target}
            variants={variants}
            catalogAvailable={catalogAvailable}
            onChange={(value) => updateScope(index, { target: value, uom_id: "" })}
          />
          <UomTarget
            variantId={scope.target}
            value={scope.uom_id}
            variants={variants}
            catalogAvailable={catalogAvailable}
            allowAny={!required}
            onChange={(value) => updateScope(index, { uom_id: value })}
          />
          {!required || productScopes.length > 1 ? (
            <button type="button" className="commercial-editor-icon-button" onClick={() => removeScope(index)} aria-label="حذف الصنف من نطاق العرض"><Trash2 className="h-4 w-4" /></button>
          ) : null}
        </div>
      ))}
      {!required || productScopes.length === 0 ? (
        <button type="button" className="commercial-editor-mini" onClick={() => set("scopes", [...form.scopes, blankProductScope()])}><Plus className="h-3.5 w-3.5" /> {required ? "اختيار الصنف" : "إضافة صنف"}</button>
      ) : null}
    </div>
  );

  const renderProductStep = () => {
    if (isCrossProductReward) {
      const qualifyingField = form.offer_type === "BUY_X_GET_Y" ? "buy_quantity" : "qualifying_quantity";
      const qualifyingLabel = form.offer_type === "BUY_X_GET_Y" ? "كمية الشراء اللازمة لكل تطبيق" : "الكمية المؤهلة لكل تطبيق";
      return <div className="space-y-4">
        <div className="rounded-2xl border border-sky-100 bg-sky-50/70 p-4">
          <EditorField label={qualifyingLabel} hint="يُجمع الشراء عبر كل المنتجات المؤهلة. كل المنتجات المؤهلة يجب أن تستخدم وحدة القياس نفسها.">
            <input className={editorInputClass} value={form[qualifyingField]} onChange={(e) => set(qualifyingField, e.target.value)} inputMode="decimal" dir="ltr" />
          </EditorField>
        </div>

        <section className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-sm font-black text-slate-800">المنتجات المؤهلة</h3><p className="mt-1 text-xs font-semibold text-slate-500">اختر المنتج والوحدة. يمكن جمع أكثر من منتج داخل نفس pool التأهيل.</p></div><button type="button" className="commercial-editor-mini" onClick={() => set("products", [...form.products, blankProduct("QUALIFYING")])}><Plus className="h-3.5 w-3.5" /> منتج مؤهل</button></div>
          <div className="space-y-2">{qualifyingRows.map(({ product, index }) => <div key={index} className="grid gap-2 md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_auto]"><VariantTarget value={product.product_variant_id} variants={variants} catalogAvailable={catalogAvailable} onChange={(value) => updateProduct(index, { product_variant_id: value, uom_id: "" })} /><UomTarget variantId={product.product_variant_id} value={product.uom_id} variants={variants} catalogAvailable={catalogAvailable} onChange={(value) => updateProduct(index, { uom_id: value })} /><button type="button" className="commercial-editor-icon-button" disabled={qualifyingRows.length === 1} onClick={() => removeProduct(index)} aria-label="حذف المنتج المؤهل"><Trash2 className="h-4 w-4" /></button></div>)}</div>
        </section>

        <section className="rounded-2xl border border-amber-200 bg-amber-50/55 p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-sm font-black text-slate-800">المكافآت</h3><p className="mt-1 text-xs font-semibold text-slate-500">A→A وA→B مدعومان. أضف أي عدد من المكافآت، ولكل مكافأة منتج ووحدة وكمية مستقلة.</p></div><button type="button" className="commercial-editor-mini" onClick={() => set("products", [...form.products, blankProduct("REWARD")])}><Plus className="h-3.5 w-3.5" /> مكافأة</button></div>
          <div className="space-y-2">{rewardRows.map(({ product, index }) => <div key={index} className="grid gap-2 md:grid-cols-[minmax(0,1.4fr)_minmax(0,.9fr)_minmax(8rem,.7fr)_auto]"><VariantTarget value={product.product_variant_id} variants={variants} catalogAvailable={catalogAvailable} onChange={(value) => updateProduct(index, { product_variant_id: value, uom_id: "" })} /><UomTarget variantId={product.product_variant_id} value={product.uom_id} variants={variants} catalogAvailable={catalogAvailable} onChange={(value) => updateProduct(index, { uom_id: value })} /><input className={editorInputClass} value={product.quantity_per_application} onChange={(e) => updateProduct(index, { quantity_per_application: e.target.value })} placeholder="كمية المكافأة" inputMode="decimal" dir="ltr" /><button type="button" className="commercial-editor-icon-button" disabled={rewardRows.length === 1} onClick={() => removeProduct(index)} aria-label="حذف المكافأة"><Trash2 className="h-4 w-4" /></button></div>)}</div>
        </section>
      </div>;
    }

    if (form.offer_type === "BUNDLE") {
      return <section className="rounded-2xl border border-slate-200 bg-white p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-sm font-black text-slate-800">مكوّنات الحزمة</h3><p className="mt-1 text-xs font-semibold text-slate-500">يلزم منتجان مختلفان على الأقل. لكل مكوّن وحدة وكمية صريحتان.</p></div><button type="button" className="commercial-editor-mini" onClick={() => set("products", [...form.products, blankProduct("BUNDLE_COMPONENT")])}><Plus className="h-3.5 w-3.5" /> مكوّن</button></div>
        <div className="space-y-2">{bundleRows.map(({ product, index }) => <div key={index} className="grid gap-2 md:grid-cols-[minmax(0,1.4fr)_minmax(0,.9fr)_minmax(8rem,.7fr)_auto]"><VariantTarget value={product.product_variant_id} variants={variants} catalogAvailable={catalogAvailable} onChange={(value) => updateProduct(index, { product_variant_id: value, uom_id: "" })} /><UomTarget variantId={product.product_variant_id} value={product.uom_id} variants={variants} catalogAvailable={catalogAvailable} onChange={(value) => updateProduct(index, { uom_id: value })} /><input className={editorInputClass} value={product.quantity_per_application} onChange={(e) => updateProduct(index, { quantity_per_application: e.target.value })} placeholder="الكمية" inputMode="decimal" dir="ltr" /><button type="button" className="commercial-editor-icon-button" disabled={bundleRows.length <= 2} onClick={() => removeProduct(index)} aria-label="حذف مكوّن الحزمة"><Trash2 className="h-4 w-4" /></button></div>)}</div>
      </section>;
    }

    const quantityTier = form.offer_type === "QUANTITY_TIERS";
    return <section className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="mb-3"><h3 className="text-sm font-black text-slate-800">{quantityTier ? "الصنف الذي تُقاس عليه الشرائح" : "الأصناف المشمولة — اختياري"}</h3><p className="mt-1 text-xs font-semibold text-slate-500">{quantityTier ? "اختر صنفًا واحدًا ووحدة قياس صريحة؛ حدود الشرائح تُقاس بهذه الوحدة." : "اترك هذه القائمة فارغة ليكون العرض غير مقيد بصنف، أو أضف صنفًا/أصنافًا محددة."}</p></div>
      {renderProductScopeRows(quantityTier)}
    </section>;
  };

  const renderTermsStep = () => <div className="space-y-4">
    <section className="commercial-editor-section">
      <div className="commercial-editor-section-head"><div><strong>قيمة العرض</strong><small>{isCrossProductReward ? "حد التأهيل والمكافآت حُددا في خطوة الأصناف والوحدات." : "حدد القيمة التجارية للعرض."}</small></div></div>
      {isCrossProductReward ? <div className="rounded-xl border border-emerald-100 bg-emerald-50 px-4 py-3 text-xs font-bold leading-6 text-emerald-800">المكافآت لا تُختصر في كمية عامة؛ كل صف مكافأة يحتفظ بمنتجه ووحدته وكمية كل تطبيق.</div> : <PayloadFields form={form} setForm={setForm} />}
    </section>
    <section className="commercial-editor-section">
      <div className="commercial-editor-section-head"><div><strong>حدود التطبيق</strong><small>{isCrossProductReward ? "في العروض متعددة الوحدات استخدم حد مرات التطبيق بدل حد كمية مكافأة عام." : "اختيارية، وتبقى خاضعة للتحقق المركزي عند الحفظ."}</small></div></div>
      <div className="commercial-editor-grid commercial-editor-grid--3"><EditorField label="أقصى عدد تطبيقات"><input className={editorInputClass} value={form.max_applications_per_document} onChange={(e) => set("max_applications_per_document", e.target.value)} inputMode="numeric" dir="ltr" /></EditorField><EditorField label="أقصى خصم مالي"><input className={editorInputClass} value={form.max_discount_amount} onChange={(e) => set("max_discount_amount", e.target.value)} inputMode="decimal" dir="ltr" /></EditorField>{!isCrossProductReward ? <EditorField label="أقصى كمية مكافأة"><input className={editorInputClass} value={form.max_reward_quantity} onChange={(e) => set("max_reward_quantity", e.target.value)} inputMode="decimal" dir="ltr" /></EditorField> : null}</div>
    </section>
  </div>;

  const renderCommercialStep = () => <div className="space-y-4">
    <section className="commercial-editor-section"><div className="commercial-editor-section-head"><div><strong>الفترة الزمنية</strong><small>متى يصبح العرض مؤهلاً للتطبيق؟</small></div></div><div className="commercial-editor-grid commercial-editor-grid--2"><EditorField label="يبدأ من"><input type="datetime-local" className={editorInputClass} value={form.effective_from} onChange={(e) => set("effective_from", e.target.value)} /></EditorField><EditorField label="ينتهي في — اختياري"><input type="datetime-local" className={editorInputClass} value={form.effective_to} onChange={(e) => set("effective_to", e.target.value)} /></EditorField></div></section>
    <section className="commercial-editor-section"><div className="commercial-editor-section-head"><div><strong>السياسة التجارية</strong><small>هذه القيم لا تغيّر حساب العرض؛ تحدد الأولوية والتجميع والعملة عند الحاجة.</small></div></div><div className="commercial-editor-grid commercial-editor-grid--3"><EditorField label="الأولوية"><input className={editorInputClass} value={form.priority} onChange={(e) => set("priority", e.target.value)} inputMode="numeric" dir="ltr" /></EditorField><EditorField label="التجميع"><select className={editorSelectClass} value={form.stacking_mode} onChange={(e) => set("stacking_mode", e.target.value as OfferVersionForm["stacking_mode"])}><option value="EXCLUSIVE">حصري</option><option value="STACKABLE">قابل للتجميع</option></select></EditorField><EditorField label="العملة" hint="مطلوبة فقط عندما يحتوي العرض قيمة نقدية."><input className={editorInputClass} value={form.currency_code} onChange={(e) => set("currency_code", e.target.value.toUpperCase())} maxLength={10} dir="ltr" /></EditorField></div></section>
  </div>;

  const renderScopeStep = () => <section className="commercial-editor-section">
    <div className="commercial-editor-section-head"><div><strong>نطاقات إضافية — اختياري</strong><small>قيود العميل والفرع والقناة. الأصناف تُدار في خطوة الأصناف والوحدات حتى تبقى الوحدة واضحة.</small></div><button className="commercial-editor-mini" type="button" onClick={() => set("scopes", [...form.scopes, { scope_type: "CUSTOMER", target: "", uom_id: "" }])}><Plus className="h-3.5 w-3.5" /> نطاق</button></div>
    <div className="space-y-2">{nonProductScopes.map(({ scope, index }) => <div key={index} className="grid gap-2 md:grid-cols-[minmax(9rem,.7fr)_minmax(0,1.5fr)_auto]"><select className={editorSelectClass} value={scope.scope_type} onChange={(e) => updateScope(index, { scope_type: e.target.value as OfferScopeType, target: "", uom_id: "" })}><option value="CUSTOMER">عميل</option><option value="BRANCH">فرع</option><option value="CHANNEL">قناة</option></select><input className={editorInputClass} value={scope.target} onChange={(e) => updateScope(index, { target: e.target.value })} placeholder={scope.scope_type === "CHANNEL" ? "ONLINE / RETAIL" : "ID"} dir="ltr" /><button type="button" className="commercial-editor-icon-button" onClick={() => removeScope(index)} aria-label="حذف النطاق"><Trash2 className="h-4 w-4" /></button></div>)}</div>
    {!nonProductScopes.length ? <div className="rounded-xl border border-dashed border-slate-200 bg-white px-4 py-6 text-center text-xs font-bold text-slate-500">لا توجد قيود إضافية. سيبقى العرض مقيدًا فقط بما اخترته في الخطوات السابقة.</div> : null}
  </section>;

  const renderReviewStep = () => <div className="space-y-4">
    <div className={`rounded-2xl border p-4 ${reviewValidation.error ? "border-rose-200 bg-rose-50" : "border-emerald-200 bg-emerald-50"}`}>
    <div className="flex items-start gap-3"><CheckCircle2 className={`mt-0.5 h-5 w-5 shrink-0 ${reviewValidation.error ? "text-rose-600" : "text-emerald-600"}`} /><div><strong className={`text-sm font-black ${reviewValidation.error ? "text-rose-800" : "text-emerald-800"}`}>{reviewValidation.error ? "الإعداد يحتاج تصحيحًا قبل الحفظ" : "الإعداد جاهز للإرسال للتحقق النهائي"}</strong><p className={`mt-1 text-xs font-semibold leading-6 ${reviewValidation.error ? "text-rose-700" : "text-emerald-700"}`}>{reviewValidation.error ?? (catalogAvailable ? "تم التحقق من بنية العقد ومن مراجع الصنف/الوحدة المحمّلة من السيرفر. يبقى الـBackend السلطة النهائية عند الحفظ." : "تم التحقق من بنية العقد محليًا. التحقق المرجعي النهائي يتم في الـBackend عند الحفظ.")}</p></div></div>
    </div>

    <div className="grid gap-3 lg:grid-cols-2">
      <section className="rounded-2xl border border-slate-200 bg-white p-4"><span className="text-[11px] font-black text-slate-400">العرض</span><h3 className="mt-1 text-base font-black text-slate-800">{selectedType.label}</h3><p className="mt-2 text-sm font-bold text-sky-700">{benefitSummary(form)}</p><p className="mt-2 text-xs font-semibold leading-6 text-slate-500">{selectedType.description}</p></section>
      <section className="rounded-2xl border border-slate-200 bg-white p-4"><span className="text-[11px] font-black text-slate-400">التوقيت والسياسة</span><dl className="mt-2 grid grid-cols-2 gap-3 text-xs"><div><dt className="font-bold text-slate-400">من</dt><dd className="mt-1 font-black text-slate-700" dir="ltr">{form.effective_from || "—"}</dd></div><div><dt className="font-bold text-slate-400">إلى</dt><dd className="mt-1 font-black text-slate-700" dir="ltr">{form.effective_to || "مفتوح"}</dd></div><div><dt className="font-bold text-slate-400">التجميع</dt><dd className="mt-1 font-black text-slate-700">{form.stacking_mode === "STACKABLE" ? "قابل للتجميع" : "حصري"}</dd></div><div><dt className="font-bold text-slate-400">الأولوية / العملة</dt><dd className="mt-1 font-black text-slate-700">{form.priority || "0"} · {form.currency_code || "—"}</dd></div></dl></section>
    </div>

    {(form.products.length || productScopes.length) ? <section className="rounded-2xl border border-slate-200 bg-white p-4"><h3 className="text-sm font-black text-slate-800">الأصناف والوحدات</h3><div className="mt-3 space-y-2">{form.products.map((product, index) => <div key={`product-${index}`} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-slate-50 px-3 py-2 text-xs"><span className="font-black text-slate-700">{roleLabel[product.role]} · {variantLabel(product.product_variant_id)}</span><span className="font-bold text-slate-500">{uomLabel(product.product_variant_id, product.uom_id)}{product.role === "QUALIFYING" ? " · الكمية من حد التأهيل" : ` · ${product.quantity_per_application || "—"}`}</span></div>)}{productScopes.map(({ scope, index }) => <div key={`scope-${index}`} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-slate-50 px-3 py-2 text-xs"><span className="font-black text-slate-700">نطاق صنف · {variantLabel(scope.target)}</span><span className="font-bold text-slate-500">{uomLabel(scope.target, scope.uom_id, form.offer_type !== "QUANTITY_TIERS")}</span></div>)}</div></section> : null}

    <section className="rounded-2xl border border-slate-200 bg-white p-4"><h3 className="text-sm font-black text-slate-800">النطاقات والحدود</h3><div className="mt-3 grid gap-2 md:grid-cols-2"><div className="rounded-xl bg-slate-50 px-3 py-2 text-xs font-bold text-slate-600">نطاقات إضافية: {nonProductScopes.length || "لا يوجد"}</div><div className="rounded-xl bg-slate-50 px-3 py-2 text-xs font-bold text-slate-600">حد مرات التطبيق: {form.max_applications_per_document || "غير محدد"}</div><div className="rounded-xl bg-slate-50 px-3 py-2 text-xs font-bold text-slate-600">أقصى خصم: {form.max_discount_amount || "غير محدد"}</div><div className="rounded-xl bg-slate-50 px-3 py-2 text-xs font-bold text-slate-600">أقصى كمية مكافأة: {isCrossProductReward ? "غير مستخدم لهذا النوع" : form.max_reward_quantity || "غير محدد"}</div></div></section>
  </div>;

  const currentStep = wizardSteps[stepIndex]?.id ?? "type";
  const body = currentStep === "type" ? <div className="space-y-4"><div><h3 className="text-base font-black text-slate-800">ما نوع العرض الذي تريد إنشاءه؟</h3><p className="mt-1 text-xs font-semibold leading-6 text-slate-500">اختر المنطق التجاري أولًا؛ الحقول اللاحقة ستتكيّف معه ولن تظهر لك تفاصيل غير مرتبطة بنوع العرض.</p></div><div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{offerTypeOptions.map((option) => { const active = option.value === form.offer_type; return <button key={option.value} type="button" aria-pressed={active} onClick={() => changeOfferType(option.value)} className={`min-h-28 rounded-2xl border p-4 text-start transition ${active ? "border-sky-400 bg-sky-50 shadow-sm" : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"}`}><span className={`block text-sm font-black ${active ? "text-sky-800" : "text-slate-800"}`}>{option.label}</span><small className="mt-2 block text-xs font-semibold leading-6 text-slate-500">{option.description}</small>{active ? <span className="mt-3 inline-flex items-center gap-1 rounded-full bg-sky-100 px-2 py-1 text-[10px] font-black text-sky-700"><CheckCircle2 className="h-3 w-3" /> مختار</span> : null}</button>; })}</div></div> : currentStep === "products" ? renderProductStep() : currentStep === "terms" ? renderTermsStep() : currentStep === "commercial" ? renderCommercialStep() : currentStep === "scopes" ? renderScopeStep() : renderReviewStep();

  return <EditorDialog
    open={open}
    onClose={onClose}
    title={version ? "تعديل نسخة العرض المسودة" : `نسخة جديدة — ${definition?.name ?? ""}`}
    subtitle="مسار تجاري موجّه؛ الحساب والتحقق النهائي يبقيان داخل نفس العقد المركزي."
    footer={<>
      <button className="commercial-editor-button commercial-editor-button--ghost" onClick={onClose}>إلغاء</button>
      <span className="mx-1 text-[11px] font-black text-slate-400">{stepIndex + 1} / {wizardSteps.length}</span>
      {stepIndex > 0 ? <button className="commercial-editor-button commercial-editor-button--ghost" type="button" onClick={() => setStepIndex((current) => Math.max(0, current - 1))}><ChevronRight className="h-3.5 w-3.5" /> السابق</button> : null}
      {stepIndex < wizardSteps.length - 1 ? <button className="commercial-editor-button commercial-editor-button--primary" type="button" onClick={() => setStepIndex((current) => Math.min(wizardSteps.length - 1, current + 1))}>التالي <ChevronLeft className="h-3.5 w-3.5" /></button> : <button className="commercial-editor-button commercial-editor-button--primary" disabled={pending || Boolean(reviewValidation.error) || !reviewValidation.payload} onClick={() => { if (reviewValidation.payload) onSave(reviewValidation.payload); }}>{pending ? "جاري الحفظ..." : version ? "حفظ المسودة" : "إنشاء المسودة"}</button>}
    </>}
  >
    <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
      {wizardSteps.map((step, index) => { const active = index === stepIndex; const done = index < stepIndex; return <button key={step.id} type="button" onClick={() => setStepIndex(index)} className={`rounded-xl border px-3 py-2 text-start transition ${active ? "border-sky-300 bg-sky-50 text-sky-800" : done ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-slate-200 bg-white text-slate-500"}`}><span className="flex items-center gap-2"><i className={`grid h-5 w-5 place-items-center rounded-full text-[10px] font-black not-italic ${active ? "bg-sky-600 text-white" : done ? "bg-emerald-600 text-white" : "bg-slate-100 text-slate-500"}`}>{done ? "✓" : index + 1}</i><b className="text-[11px] font-black">{step.label}</b></span></button>; })}
    </div>

    <div className="rounded-2xl border border-slate-200 bg-slate-50/60 p-4">{body}</div>

    {catalogAvailable && hasMoreVariants && currentStep === "products" ? <button type="button" className="commercial-load-more" disabled={loadingMoreVariants} onClick={onLoadMoreVariants}>{loadingMoreVariants ? "جاري تحميل أصناف إضافية..." : "تحميل أصناف إضافية"}</button> : null}
  </EditorDialog>;
}
