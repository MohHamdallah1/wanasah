import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Boxes,
  ChevronLeft,
  ChevronRight,
  FileSpreadsheet,
  PackagePlus,
  RefreshCw,
  Search,
  Upload,
} from "lucide-react";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";

type Family = { id: number; name: string };
type SimpleProduct = {
  id: number;
  product_id: number;
  name: string;
  family_name: string;
  units_per_carton: number;
  currency_code: string;
  carton_price: string | null;
  unit_price: string | null;
  unit_barcode: string | null;
  carton_barcode: string | null;
  lifecycle_status: string;
  simple_compatible: boolean;
};
type SimpleProductPage = {
  currency_code: string;
  items: SimpleProduct[];
  next_cursor: string | null;
  has_more: boolean;
};
type ImportStatus = {
  job_id: string;
  status: string;
  file_name: string;
  total_rows: number;
  processed_rows: number;
  valid_rows: number;
  failed_rows: number;
  detected_headers: string[];
  suggested_mapping: Record<string, string>;
  column_mapping: Record<string, string>;
  error_summary: Record<string, unknown>;
  errors: Array<{ row_number: number; code: string | null; message: string | null }>;
};

const requestId = () => crypto.randomUUID();
const terminalImportStatuses = new Set([
  "COMPLETED",
  "VALIDATION_FAILED",
  "FAILED",
  "NEEDS_MAPPING",
]);

const money = (value: string | null) => {
  if (value === null) return "—";
  const numeric = Number(value);
  return Number.isFinite(numeric)
    ? numeric.toLocaleString("ar-JO", {
        minimumFractionDigits: 3,
        maximumFractionDigits: 6,
      })
    : value;
};

const derive = (units: string, carton: string, unit: string) => {
  const count = Number(units);
  const cartonValue = carton.trim() ? Number(carton) : null;
  const unitValue = unit.trim() ? Number(unit) : null;
  if (!Number.isInteger(count) || count <= 0) {
    return { carton: null, unit: null, independent: false };
  }
  if (
    (cartonValue !== null && (!Number.isFinite(cartonValue) || cartonValue <= 0)) ||
    (unitValue !== null && (!Number.isFinite(unitValue) || unitValue <= 0))
  ) {
    return { carton: null, unit: null, independent: false };
  }
  if (cartonValue === null && unitValue === null) {
    return { carton: null, unit: null, independent: false };
  }
  return {
    carton: cartonValue ?? (unitValue !== null ? unitValue * count : null),
    unit: unitValue ?? (cartonValue !== null ? cartonValue / count : null),
    independent: cartonValue !== null && unitValue !== null,
  };
};

const emptyDraft = {
  name: "",
  family: "",
  units_per_carton: "50",
  carton_price: "",
  unit_price: "",
  unit_barcode: "",
  carton_barcode: "",
};

const mappingLabels: Record<string, string> = {
  name: "اسم المنتج",
  family: "العائلة",
  units_per_carton: "عدد الحبات في الكرتونة",
  carton_price: "سعر الكرتونة",
  unit_price: "سعر الحبة",
  unit_barcode: "باركود الحبة",
  carton_barcode: "باركود الكرتونة",
};

export default function ProductsDashboard() {
  const authFetch = useAuthFetch();
  const queryClient = useQueryClient();
  const access = useInventoryAccess();
  const canManage =
    access.isCompanyAdmin ||
    (access.canAny("catalog.manage") &&
      access.canAny("catalog.publish") &&
      access.canAny("pricing.manage"));

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [history, setHistory] = useState<Array<string | null>>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [draft, setDraft] = useState(emptyDraft);
  const [priceEdit, setPriceEdit] = useState<SimpleProduct | null>(null);
  const [editCarton, setEditCarton] = useState("");
  const [editUnit, setEditUnit] = useState("");

  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importRequestId, setImportRequestId] = useState<string | null>(null);
  const [importJobId, setImportJobId] = useState<string | null>(null);
  const [importStatus, setImportStatus] = useState<ImportStatus | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [importPollKey, setImportPollKey] = useState(0);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = searchInput.trim();
      setSearch(clean.length >= 2 ? clean : "");
      setCursor(null);
      setHistory([]);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const params = useMemo(() => {
    const value = new URLSearchParams({ limit: "100" });
    if (search) value.set("search", search);
    if (cursor) value.set("cursor", cursor);
    return value.toString();
  }, [search, cursor]);

  const productsQuery = useQuery({
    queryKey: ["simple-products", search, cursor],
    queryFn: async ({ signal }) =>
      (await authFetch(`/simple-products?${params}`, { signal })) as SimpleProductPage,
  });
  const page = productsQuery.data;
  const currency = page?.currency_code || "—";

  const familiesQuery = useQuery({
    queryKey: ["simple-product-families"],
    queryFn: async ({ signal }) =>
      (await authFetch("/simple-products/families?limit=100", { signal })) as {
        items: Family[];
      },
  });
  const families = familiesQuery.data?.items ?? [];

  const createMutation = useMutation({
    mutationFn: async () => {
      const units = Number(draft.units_per_carton);
      if (!draft.name.trim()) throw new Error("اسم المنتج مطلوب.");
      if (!Number.isInteger(units) || units <= 0) {
        throw new Error("عدد الحبات في الكرتونة يجب أن يكون رقماً صحيحاً موجباً.");
      }
      if (!draft.carton_price.trim() && !draft.unit_price.trim()) {
        throw new Error("أدخل سعر الكرتونة أو سعر الحبة على الأقل.");
      }
      const selectedFamily = families.find(
        (item) =>
          item.name.trim().toLowerCase() === draft.family.trim().toLowerCase()
      );
      return authFetch("/simple-products", {
        method: "POST",
        body: JSON.stringify({
          request_id: requestId(),
          name: draft.name.trim(),
          family_id: selectedFamily?.id ?? null,
          family_name:
            !selectedFamily && draft.family.trim() ? draft.family.trim() : null,
          units_per_carton: units,
          carton_price: draft.carton_price.trim() || null,
          unit_price: draft.unit_price.trim() || null,
          unit_barcode: draft.unit_barcode.trim() || null,
          carton_barcode: draft.carton_barcode.trim() || null,
        }),
      });
    },
    onSuccess: async () => {
      toast.success("تم حفظ المنتج والسعر.");
      setDraft(emptyDraft);
      setCreateOpen(false);
      setCursor(null);
      setHistory([]);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["simple-products"] }),
        queryClient.invalidateQueries({ queryKey: ["simple-product-families"] }),
      ]);
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "تعذر حفظ المنتج.")),
  });

  const priceMutation = useMutation({
    mutationFn: async () => {
      if (!priceEdit) return;
      if (!editCarton.trim() && !editUnit.trim()) {
        throw new Error("أدخل سعر الكرتونة أو سعر الحبة على الأقل.");
      }
      return authFetch(`/simple-products/${priceEdit.id}/price`, {
        method: "PATCH",
        body: JSON.stringify({
          request_id: requestId(),
          carton_price: editCarton.trim() || null,
          unit_price: editUnit.trim() || null,
        }),
      });
    },
    onSuccess: async () => {
      toast.success("تم تحديث الأسعار.");
      setPriceEdit(null);
      await queryClient.invalidateQueries({ queryKey: ["simple-products"] });
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "تعذر تحديث الأسعار.")),
  });

  const importMutation = useMutation({
    mutationFn: async () => {
      if (!importFile || !importRequestId) throw new Error("اختر ملفاً أولاً.");
      const form = new FormData();
      form.append("request_id", importRequestId);
      form.append("file", importFile);
      return (await authFetch("/simple-products/imports", {
        method: "POST",
        body: form,
      })) as { job_id: string; status: string; message: string };
    },
    onSuccess: (result) => {
      setImportJobId(result.job_id);
      setImportStatus(null);
      toast.success("تم استلام الملف. المعالجة تعمل في الخلفية.");
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "تعذر رفع ملف الاستيراد.")),
  });

  const mappingMutation = useMutation({
    mutationFn: async () => {
      if (!importJobId) return;
      return authFetch(`/simple-products/imports/${importJobId}/mapping`, {
        method: "PUT",
        body: JSON.stringify({ mapping }),
      });
    },
    onSuccess: () => {
      setImportStatus((current) =>
        current ? { ...current, status: "VALIDATING" } : current
      );
      setImportPollKey((current) => current + 1);
      toast.success("تم اعتماد ربط الأعمدة.");
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "تعذر اعتماد ربط الأعمدة.")),
  });

  const retryImportMutation = useMutation({
    mutationFn: async () => {
      if (!importJobId) return;
      return authFetch(`/simple-products/imports/${importJobId}/retry`, {
        method: "POST",
      });
    },
    onSuccess: () => {
      setImportStatus((current) =>
        current ? { ...current, status: "QUEUED" } : current
      );
      setImportPollKey((current) => current + 1);
      toast.success("تمت إعادة العملية إلى الطابور.");
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "تعذر إعادة المحاولة.")),
  });

  useEffect(() => {
    if (!importJobId) return;
    let disposed = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const status = (await authFetch(
          `/simple-products/imports/${importJobId}`
        )) as ImportStatus;
        if (disposed) return;
        setImportStatus(status);
        if (status.status === "NEEDS_MAPPING") {
          setMapping(
            Object.keys(status.column_mapping || {}).length
              ? status.column_mapping
              : status.suggested_mapping
          );
        }
        if (status.status === "COMPLETED") {
          toast.success(`اكتمل استيراد ${status.processed_rows} منتج.`);
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: ["simple-products"] }),
            queryClient.invalidateQueries({
              queryKey: ["simple-product-families"],
            }),
          ]);
          return;
        }
        if (!terminalImportStatuses.has(status.status)) {
          timer = window.setTimeout(poll, 1500);
        }
      } catch {
        if (!disposed) timer = window.setTimeout(poll, 3000);
      }
    };
    void poll();
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [authFetch, importJobId, importPollKey, queryClient]);

  const chooseFile = (file: File | null) => {
    if (!file) return;
    const lower = file.name.toLowerCase();
    if (!lower.endsWith(".csv") && !lower.endsWith(".xlsx")) {
      toast.error("الملفات المدعومة CSV و XLSX.");
      return;
    }
    setImportFile(file);
    setImportRequestId(requestId());
    setImportJobId(null);
    setImportStatus(null);
    setMapping({});
  };

  const downloadTemplate = () => {
    const lines = [
      "اسم المنتج,العائلة,عدد الحبات في الكرتونة,سعر الكرتونة,سعر الحبة,باركود الحبة,باركود الكرتونة",
      "شيبس لولو جبنة 20غ,شيبس لولو,50,10.000,,6251234567890,",
      "شيبس لولو كاتشب 20غ,شيبس لولو,50,,0.300,,",
    ];
    const blob = new Blob(["\ufeff", lines.join("\n")], {
      type: "text/csv;charset=utf-8",
    });
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = "نموذج-استيراد-المنتجات.csv";
    anchor.click();
    URL.revokeObjectURL(href);
  };

  const derived = derive(
    draft.units_per_carton,
    draft.carton_price,
    draft.unit_price
  );
  const importProgress =
    importStatus && importStatus.valid_rows > 0
      ? Math.min(
          100,
          Math.round(
            (importStatus.processed_rows / importStatus.valid_rows) * 100
          )
        )
      : 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden" dir="rtl">
      <header className="shrink-0 rounded-[26px] border border-white/70 bg-white/85 px-5 py-4 shadow-sm backdrop-blur-xl">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-[16px] bg-slate-950 text-white">
              <Boxes className="h-5 w-5" />
            </span>
            <div>
              <h1 className="text-xl font-black text-slate-950">المنتجات</h1>
              <p className="mt-0.5 text-xs font-semibold text-slate-500">
                أضف المنتج وسعره في عملية واحدة. النظام يتكفل بالباقي.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void productsQuery.refetch()}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-600"
            >
              <RefreshCw
                className={`h-4 w-4 ${
                  productsQuery.isFetching ? "animate-spin" : ""
                }`}
              />
              تحديث
            </button>
            {canManage ? (
              <>
                <button
                  type="button"
                  onClick={() => setImportOpen(true)}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700"
                >
                  <FileSpreadsheet className="h-4 w-4" />
                  استيراد ملف
                </button>
                <button
                  type="button"
                  onClick={() => setCreateOpen(true)}
                  className="inline-flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2 text-xs font-black text-white"
                >
                  <PackagePlus className="h-4 w-4" />
                  إضافة منتج
                </button>
              </>
            ) : null}
          </div>
        </div>
      </header>

      <section className="mt-3 flex min-h-0 flex-1 flex-col overflow-hidden rounded-[26px] border border-white/70 bg-white/85 shadow-sm backdrop-blur-xl">
        <div className="shrink-0 border-b border-slate-100 p-4">
          <div className="relative max-w-md">
            <Search className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="search"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="ابحث باسم المنتج أو العائلة..."
              className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2.5 pl-3 pr-9 text-sm font-bold outline-none focus:border-slate-400 focus:bg-white"
            />
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          <table className="w-full min-w-[850px] text-right text-sm">
            <thead className="sticky top-0 z-10 bg-slate-50 text-xs font-black text-slate-500">
              <tr>
                <th className="px-5 py-3">المنتج</th>
                <th className="px-5 py-3">الحبات / كرتونة</th>
                <th className="px-5 py-3">سعر الكرتونة</th>
                <th className="px-5 py-3">سعر الحبة</th>
                <th className="px-5 py-3">الإجراء</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {productsQuery.isLoading ? (
                <tr>
                  <td colSpan={5} className="py-16 text-center font-bold text-slate-400">
                    جاري تحميل المنتجات...
                  </td>
                </tr>
              ) : null}
              {!productsQuery.isLoading && !page?.items.length ? (
                <tr>
                  <td colSpan={5} className="py-16 text-center">
                    <Boxes className="mx-auto mb-3 h-8 w-8 text-slate-300" />
                    <p className="font-black text-slate-700">لا توجد منتجات بعد</p>
                    <p className="mt-1 text-xs text-slate-400">
                      أضف منتجاً أو استورد ملفاً.
                    </p>
                  </td>
                </tr>
              ) : null}
              {page?.items.map((item) => (
                <tr key={item.id} className="bg-white hover:bg-slate-50/70">
                  <td className="px-5 py-4">
                    <div className="font-black text-slate-900">{item.name}</div>
                    {item.family_name !== item.name ? (
                      <div className="mt-1 text-[10px] font-bold text-slate-400">
                        {item.family_name}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-5 py-4 font-black tabular-nums">
                    {item.units_per_carton}
                  </td>
                  <td className="px-5 py-4 font-black tabular-nums">
                    {money(item.carton_price)} {item.currency_code}
                  </td>
                  <td className="px-5 py-4 font-black tabular-nums">
                    {money(item.unit_price)} {item.currency_code}
                  </td>
                  <td className="px-5 py-4">
                    {canManage && item.simple_compatible ? (
                      <button
                        type="button"
                        onClick={() => {
                          setPriceEdit(item);
                          setEditCarton(item.carton_price ?? "");
                          setEditUnit(item.unit_price ?? "");
                        }}
                        className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700 hover:bg-slate-50"
                      >
                        تعديل السعر
                      </button>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {history.length > 0 || page?.next_cursor ? (
          <div className="flex shrink-0 justify-end gap-2 border-t border-slate-100 bg-slate-50 px-4 py-3">
            <button
              type="button"
              disabled={!history.length || productsQuery.isFetching}
              onClick={() => {
                const previous = history.at(-1) ?? null;
                setHistory((current) => current.slice(0, -1));
                setCursor(previous);
              }}
              className="rounded-lg border border-slate-200 bg-white p-2 disabled:opacity-30"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
            <button
              type="button"
              disabled={!page?.next_cursor || productsQuery.isFetching}
              onClick={() => {
                if (!page?.next_cursor) return;
                setHistory((current) => [...current, cursor]);
                setCursor(page.next_cursor);
              }}
              className="rounded-lg border border-slate-200 bg-white p-2 disabled:opacity-30"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
          </div>
        ) : null}
      </section>

      <Modal
        isOpen={createOpen}
        onClose={() => !createMutation.isPending && setCreateOpen(false)}
        title="إضافة منتج"
        maxWidth="max-w-2xl"
        footer={
          <>
            <button
              type="button"
              disabled={createMutation.isPending}
              onClick={() => setCreateOpen(false)}
              className="px-4 py-2 text-sm font-bold text-slate-600"
            >
              إلغاء
            </button>
            <button
              type="button"
              disabled={createMutation.isPending}
              onClick={() => createMutation.mutate()}
              className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-black text-white disabled:opacity-50"
            >
              حفظ المنتج
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-black text-slate-600">
              اسم المنتج
              <input
                value={draft.name}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, name: event.target.value }))
                }
                placeholder="مثال: شيبس لولو جبنة 20غ"
                className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-bold outline-none focus:border-slate-400"
              />
            </label>
            <label className="text-xs font-black text-slate-600">
              العائلة <span className="font-bold text-slate-400">اختياري</span>
              <input
                list="product-family-options"
                value={draft.family}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, family: event.target.value }))
                }
                placeholder="اختر عائلة أو اكتب اسماً جديداً"
                className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-bold outline-none focus:border-slate-400"
              />
              <datalist id="product-family-options">
                {families.map((family) => (
                  <option key={family.id} value={family.name} />
                ))}
              </datalist>
            </label>
            <label className="text-xs font-black text-slate-600">
              عدد الحبات في الكرتونة
              <input
                inputMode="numeric"
                value={draft.units_per_carton}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    units_per_carton: event.target.value,
                  }))
                }
                className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-bold outline-none"
              />
            </label>
            <div className="hidden sm:block" />
            <label className="text-xs font-black text-slate-600">
              سعر الكرتونة <span className="font-bold text-slate-400">اختياري</span>
              <input
                inputMode="decimal"
                value={draft.carton_price}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, carton_price: event.target.value }))
                }
                placeholder="اتركه فارغاً إذا أدخلت سعر الحبة"
                className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-black outline-none"
              />
            </label>
            <label className="text-xs font-black text-slate-600">
              سعر الحبة <span className="font-bold text-slate-400">اختياري</span>
              <input
                inputMode="decimal"
                value={draft.unit_price}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, unit_price: event.target.value }))
                }
                placeholder="اتركه فارغاً ليحسبه النظام"
                className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-black outline-none"
              />
            </label>
          </div>
          {derived.carton !== null || derived.unit !== null ? (
            <div className="rounded-2xl bg-emerald-50 p-3 text-xs font-bold leading-6 text-emerald-900">
              {derived.independent ? (
                <>سيتم اعتماد السعرين كما أدخلتهما، حتى لو كانا مختلفين عن نتيجة القسمة.</>
              ) : (
                <>
                  النظام سيكمل السعر الناقص تلقائياً: الكرتونة {derived.carton?.toFixed(6)}، الحبة {derived.unit?.toFixed(6)}.
                </>
              )}
            </div>
          ) : null}
          <details className="rounded-2xl border border-slate-200 bg-white p-3">
            <summary className="cursor-pointer text-xs font-black text-slate-600">
              الباركود — اختياري
            </summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <label className="text-xs font-bold text-slate-500">
                باركود الحبة
                <input
                  value={draft.unit_barcode}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, unit_barcode: event.target.value }))
                  }
                  className="mt-1.5 w-full rounded-xl border border-slate-200 p-2.5 font-mono"
                />
              </label>
              <label className="text-xs font-bold text-slate-500">
                باركود الكرتونة
                <input
                  value={draft.carton_barcode}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, carton_barcode: event.target.value }))
                  }
                  className="mt-1.5 w-full rounded-xl border border-slate-200 p-2.5 font-mono"
                />
              </label>
            </div>
          </details>
        </div>
      </Modal>

      <Modal
        isOpen={priceEdit !== null}
        onClose={() => !priceMutation.isPending && setPriceEdit(null)}
        title={`تعديل السعر — ${priceEdit?.name ?? ""}`}
        maxWidth="max-w-xl"
        footer={
          <>
            <button
              type="button"
              disabled={priceMutation.isPending}
              onClick={() => setPriceEdit(null)}
              className="px-4 py-2 text-sm font-bold text-slate-600"
            >
              إلغاء
            </button>
            <button
              type="button"
              disabled={priceMutation.isPending}
              onClick={() => priceMutation.mutate()}
              className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-black text-white disabled:opacity-50"
            >
              حفظ السعر
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="rounded-2xl bg-sky-50 p-3 text-xs font-bold leading-6 text-sky-900">
            اترك أحد السعرين فارغاً ليحسبه النظام، أو أدخل السعرين ليتم اعتمادهما كما هما.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-black text-slate-600">
              سعر الكرتونة
              <input
                inputMode="decimal"
                value={editCarton}
                onChange={(event) => setEditCarton(event.target.value)}
                className="mt-1.5 w-full rounded-xl border p-2.5 font-black"
              />
            </label>
            <label className="text-xs font-black text-slate-600">
              سعر الحبة
              <input
                inputMode="decimal"
                value={editUnit}
                onChange={(event) => setEditUnit(event.target.value)}
                className="mt-1.5 w-full rounded-xl border p-2.5 font-black"
              />
            </label>
          </div>
        </div>
      </Modal>

      <Modal
        isOpen={importOpen}
        onClose={() => !importMutation.isPending && setImportOpen(false)}
        title="استيراد المنتجات"
        maxWidth="max-w-2xl"
      >
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-sky-50 p-3">
            <p className="text-xs font-bold leading-6 text-sky-900">
              يدعم CSV وExcel. ترتيب الأعمدة لا يهم، وإذا لم يتعرف النظام عليها سيطلب منك ربطها مرة واحدة.
            </p>
            <button
              type="button"
              onClick={downloadTemplate}
              className="rounded-xl bg-white px-3 py-2 text-xs font-black text-sky-900 shadow-sm"
            >
              تحميل النموذج
            </button>
          </div>

          {!importJobId ? (
            <>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                className="hidden"
                onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
              />
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                onDragEnter={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setDragging(false);
                  chooseFile(event.dataTransfer.files?.[0] ?? null);
                }}
                className={`flex min-h-48 w-full flex-col items-center justify-center rounded-[24px] border border-dashed text-center transition ${
                  dragging
                    ? "border-slate-950 bg-slate-100"
                    : "border-slate-300 bg-slate-50 hover:bg-white"
                }`}
              >
                <Upload className="mb-3 h-8 w-8 text-slate-400" />
                <strong className="text-sm text-slate-700">
                  {importFile?.name ?? "اسحب الملف هنا أو اضغط للاختيار"}
                </strong>
                <span className="mt-1 text-xs text-slate-400">
                  حتى 50,000 صف — المعالجة تتم في الخلفية
                </span>
              </button>
              <button
                type="button"
                disabled={!importFile || importMutation.isPending}
                onClick={() => importMutation.mutate()}
                className="w-full rounded-xl bg-slate-950 px-4 py-3 text-sm font-black text-white disabled:opacity-40"
              >
                رفع وبدء الاستيراد
              </button>
            </>
          ) : null}

          {importJobId && !importStatus ? (
            <div className="rounded-2xl bg-slate-50 p-5 text-center text-sm font-black text-slate-600">
              تم إدراج العملية في الطابور...
            </div>
          ) : null}

          {importStatus?.status === "NEEDS_MAPPING" ? (
            <div className="space-y-3">
              <div className="rounded-2xl bg-amber-50 p-3 text-xs font-bold leading-6 text-amber-900">
                لم نخمن الأعمدة غير الواضحة. اربط المطلوب فقط ثم اضغط متابعة.
              </div>
              {Object.entries(mappingLabels).map(([field, label]) => (
                <label
                  key={field}
                  className="grid gap-2 text-xs font-black text-slate-600 sm:grid-cols-[180px_1fr] sm:items-center"
                >
                  <span>
                    {label}
                    {["name", "units_per_carton"].includes(field) ? " *" : ""}
                  </span>
                  <select
                    value={mapping[field] ?? ""}
                    onChange={(event) =>
                      setMapping((current) => ({
                        ...current,
                        [field]: event.target.value,
                      }))
                    }
                    className="rounded-xl border border-slate-200 bg-white p-2.5"
                  >
                    <option value="">غير مربوط</option>
                    {importStatus.detected_headers.map((header) => (
                      <option key={header} value={header}>
                        {header}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
              <button
                type="button"
                disabled={mappingMutation.isPending}
                onClick={() => mappingMutation.mutate()}
                className="w-full rounded-xl bg-slate-950 px-4 py-3 text-sm font-black text-white"
              >
                متابعة الاستيراد
              </button>
            </div>
          ) : null}

          {importStatus &&
          !["NEEDS_MAPPING", "VALIDATION_FAILED", "FAILED", "COMPLETED"].includes(
            importStatus.status
          ) ? (
            <div className="rounded-[22px] border border-slate-200 p-4">
              <div className="flex items-center justify-between text-xs font-black">
                <span>
                  {importStatus.status === "IMPORTING"
                    ? "جاري إضافة المنتجات"
                    : "جاري تجهيز وفحص الملف"}
                </span>
                <span>
                  {importStatus.processed_rows} / {importStatus.valid_rows || importStatus.total_rows}
                </span>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
                <div
                  className="h-full rounded-full bg-slate-950 transition-all"
                  style={{ width: `${importProgress}%` }}
                />
              </div>
              <p className="mt-3 text-[11px] text-slate-500">
                يمكنك إغلاق هذه النافذة؛ العملية مستمرة في الخلفية.
              </p>
            </div>
          ) : null}

          {importStatus?.status === "VALIDATION_FAILED" ? (
            <div className="space-y-3">
              <div className="rounded-2xl bg-rose-50 p-3 text-xs font-bold leading-6 text-rose-900">
                لم يتم استيراد أي منتج. يوجد {importStatus.failed_rows} صف بحاجة تصحيح.
              </div>
              <div className="max-h-64 overflow-auto rounded-xl border">
                {importStatus.errors.map((error) => (
                  <div
                    key={`${error.row_number}-${error.code}`}
                    className="border-b p-3 text-xs last:border-b-0"
                  >
                    <strong>الصف {error.row_number}</strong>
                    <span className="mr-2 text-rose-700">{error.message}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {importStatus?.status === "FAILED" ? (
            <div className="space-y-3 rounded-2xl bg-rose-50 p-4 text-xs font-bold leading-6 text-rose-900">
              <p>
                توقفت العملية بعد استيراد {importStatus.processed_rows} من{" "}
                {importStatus.valid_rows || importStatus.total_rows} منتج.
                كل دفعة تم اعتمادها مكتملة، ولن يعيد النظام إنشاءها عند الاستكمال.
              </p>
              {typeof importStatus.error_summary?.detail === "string" ? (
                <p className="rounded-xl bg-white/70 p-2 text-rose-800">
                  {String(importStatus.error_summary.detail)}
                </p>
              ) : null}
              {importStatus.error_summary?.retryable === true ? (
                <button
                  type="button"
                  disabled={retryImportMutation.isPending}
                  onClick={() => retryImportMutation.mutate()}
                  className="w-full rounded-xl bg-rose-900 px-4 py-2.5 text-xs font-black text-white disabled:opacity-50"
                >
                  إعادة المحاولة من حيث توقفت
                </button>
              ) : (
                <p className="text-[11px] text-rose-700">
                  الخطأ يحتاج تصحيحاً قبل إعادة رفع الملف.
                </p>
              )}
            </div>
          ) : null}

          {importStatus?.status === "COMPLETED" ? (
            <div className="rounded-2xl bg-emerald-50 p-5 text-center">
              <strong className="text-sm text-emerald-900">
                تم استيراد {importStatus.processed_rows} منتج بنجاح
              </strong>
              <button
                type="button"
                onClick={() => {
                  setImportOpen(false);
                  setImportFile(null);
                  setImportRequestId(null);
                  setImportJobId(null);
                  setImportStatus(null);
                  setMapping({});
                }}
                className="mt-4 block w-full rounded-xl bg-emerald-900 px-4 py-2.5 text-xs font-black text-white"
              >
                تم
              </button>
            </div>
          ) : null}
        </div>
      </Modal>
    </div>
  );
}
