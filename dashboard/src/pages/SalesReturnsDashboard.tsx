import { currentLocale } from "@/i18n";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  BadgeDollarSign,
  CheckCircle2,
  CircleDollarSign,
  HelpCircle,
  History,
  PackageOpen,
  ReceiptText,
  RotateCcw,
  Search,
  ShieldCheck,
  Sparkles,
  Store,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import {
  createSalesReturn,
  fetchReturnableSales,
  fetchSalesReturns,
  fetchSalesReturnSource,
} from "@/features/salesReturns/api";
import type {
  SalesReturnDetail,
  SalesReturnEligibleSource,
  SalesReturnSource,
} from "@/features/salesReturns/contracts";

type CreateSalesReturnInput = Parameters<typeof createSalesReturn>[1];

const decimalParts = (value: string): [string, string] | null => {
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,6})?$/.test(value)) return null;
  const [integerRaw, fractionRaw = ""] = value.split(".");
  const integer = integerRaw.replace(/^0+(?=\d)/, "");
  return [integer, fractionRaw.padEnd(6, "0")];
};

const compareDecimal = (left: string, right: string): number => {
  const a = decimalParts(left);
  const b = decimalParts(right);
  if (!a || !b) throw new Error("Decimal comparison received invalid input.");
  if (a[0].length !== b[0].length) return a[0].length > b[0].length ? 1 : -1;
  if (a[0] !== b[0]) return a[0] > b[0] ? 1 : -1;
  if (a[1] !== b[1]) return a[1] > b[1] ? 1 : -1;
  return 0;
};

const decimalPositive = (value: string) =>
  decimalParts(value) !== null && compareDecimal(value, "0") > 0;

const formatDate = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(currentLocale(), {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
};

const inputClass =
  "h-11 w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-slate-400 focus:ring-4 focus:ring-slate-100";

function ReturnHelpModal({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/35 p-4 backdrop-blur-sm"
      dir="rtl"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onClose();
      }}
    >
      <div className="w-full max-w-3xl overflow-hidden rounded-[32px] border border-white/70 bg-white shadow-2xl">
        <div className="relative overflow-hidden border-b border-slate-100 bg-gradient-to-l from-slate-950 via-slate-900 to-slate-800 p-6 text-white">
          <div className="absolute -left-12 -top-16 h-40 w-40 rounded-full bg-white/10 blur-2xl" />
          <div className="relative flex items-start justify-between gap-4">
            <div>
              <div className="mb-2 flex items-center gap-2 text-xs font-black text-slate-300">
                <Sparkles className="h-4 w-4" />
                دليل سريع
              </div>
              <h2 className="text-2xl font-black">كيف تعمل صفحة مرتجعات البيع؟</h2>
              <p className="mt-2 text-sm leading-6 text-slate-300">
                الصفحة مخصصة لإنشاء مرتجع مالي من عملية بيع سابقة، وليست شاشة
                دفع نقدي أو استلام مخزون.
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-white/15 bg-white/10 p-2 text-white transition hover:bg-white/20"
              aria-label="إغلاق"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div className="p-6">
          <div className="rounded-3xl border border-slate-200 bg-slate-50 p-5">
            <p className="text-base font-bold leading-9 text-slate-800">
              عميل رجّع بضاعة كان اشتراها سابقًا → المسؤول يفتح الصفحة → يختار
              عملية البيع الأصلية → يحدد الصنف والكمية المرتجعة → يضغط
              &quot;إنشاء مرتجع مالي&quot; → النظام يحسب تلقائيًا كم أصبح مستحقًا
              للعميل من السعر/الخصم/الضريبة الأصلية.
            </p>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-4">
            {[
              ["1", "اختر البيع", "حدد عملية البيع الأصلية."],
              ["2", "حدد الكمية", "اختر ما أعاده العميل فقط."],
              ["3", "أنشئ المرتجع", "ثبّت الإشعار الدائن."],
              ["4", "يُحسب الحق", "يُحسب من البيع الأصلي تلقائيًا."],
            ].map(([number, title, description]) => (
              <div
                key={number}
                className="rounded-2xl border border-slate-200 bg-white p-4"
              >
                <span className="mb-3 flex h-8 w-8 items-center justify-center rounded-xl bg-slate-900 text-xs font-black text-white">
                  {number}
                </span>
                <strong className="text-sm text-slate-900">{title}</strong>
                <p className="mt-1 text-xs leading-5 text-slate-500">
                  {description}
                </p>
              </div>
            ))}
          </div>

          <div className="mt-5 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4">
            <BadgeDollarSign className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" />
            <p className="text-xs font-semibold leading-6 text-amber-900">
              هذه الصفحة تثبت الرصيد الدائن فقط. لا يتم دفع كاش ولا تنفيذ تحويل
              بنكي ولا إعادة البضاعة للمخزون من هنا.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function SaleCard({
  sale,
  selected,
  loading,
  onSelect,
}: {
  sale: SalesReturnEligibleSource;
  selected: boolean;
  loading: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={loading}
      className={`group w-full overflow-hidden rounded-3xl border text-right transition ${
        selected
          ? "border-slate-900 bg-slate-900 text-white shadow-lg shadow-slate-200"
          : "border-slate-200 bg-white hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md"
      } disabled:cursor-wait disabled:opacity-60`}
    >
      <div className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span
                className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl ${
                  selected
                    ? "bg-white/10 text-white"
                    : "bg-slate-100 text-slate-700"
                }`}
              >
                <Store className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <strong className="block truncate text-sm">{sale.shop_name}</strong>
                <span
                  className={`mt-0.5 block text-[11px] ${
                    selected ? "text-slate-300" : "text-slate-500"
                  }`}
                >
                  زيارة #{sale.visit_id} · {formatDate(sale.sold_at)}
                </span>
              </div>
            </div>
          </div>

          <span
            className={`rounded-full px-2.5 py-1 text-[10px] font-black ${
              selected
                ? "bg-emerald-400/15 text-emerald-200"
                : "bg-emerald-100 text-emerald-700"
            }`}
          >
            قابل للمرتجع
          </span>
        </div>

        <div
          className={`mt-4 flex items-end justify-between border-t pt-3 ${
            selected ? "border-white/10" : "border-slate-100"
          }`}
        >
          <div>
            <span
              className={`text-[10px] font-bold ${
                selected ? "text-slate-400" : "text-slate-500"
              }`}
            >
              قيمة البيع الأصلي
            </span>
            <strong className="mt-0.5 block text-base">
              {sale.final_amount} {sale.transaction_currency_code}
            </strong>
          </div>

          <span
            className={`inline-flex items-center gap-1 text-xs font-black ${
              selected ? "text-white" : "text-slate-700"
            }`}
          >
            {loading ? "جاري التحميل..." : "اختيار"}
            <ArrowLeft className="h-3.5 w-3.5 transition group-hover:-translate-x-0.5" />
          </span>
        </div>
      </div>
    </button>
  );
}

export default function SalesReturnsDashboard() {
  const access = useInventoryAccess();
  const authFetch = useAuthFetch();
  const queryClient = useQueryClient();

  const [activeView, setActiveView] = useState<"create" | "history">("create");
  const [helpOpen, setHelpOpen] = useState(false);
  const [searchDraft, setSearchDraft] = useState("");
  const [search, setSearch] = useState("");
  const [dateFromDraft, setDateFromDraft] = useState("");
  const [dateToDraft, setDateToDraft] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sourceCursor, setSourceCursor] = useState<number | null>(null);
  const [sourceCursorHistory, setSourceCursorHistory] = useState<
    Array<number | null>
  >([]);
  const [selectedVisitId, setSelectedVisitId] = useState<number | null>(null);
  const [loadedSource, setLoadedSource] = useState<SalesReturnSource | null>(null);
  const [reason, setReason] = useState("");
  const [quantities, setQuantities] = useState<Record<number, string>>({});

  const sourcesQuery = useQuery({
    queryKey: [
      "sales-return-sources",
      search,
      dateFrom,
      dateTo,
      sourceCursor,
    ],
    queryFn: () =>
      fetchReturnableSales(authFetch, {
        search,
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || undefined,
        beforeRevisionId: sourceCursor,
        limit: 50,
      }),
    enabled: access.isCompanyAdmin,
  });

  const returnsQuery = useQuery({
    queryKey: ["sales-returns"],
    queryFn: () => fetchSalesReturns(authFetch),
    enabled: access.isCompanyAdmin,
  });

  const sourceMutation = useMutation({
    mutationFn: (visitId: number) => fetchSalesReturnSource(authFetch, visitId),
    onSuccess: (source) => {
      setSelectedVisitId(source.visit_id);
      setLoadedSource(source);
      setQuantities({});
      setReason("");
    },
  });

  const createMutation = useMutation<
    SalesReturnDetail,
    Error,
    CreateSalesReturnInput
  >({
    mutationFn: (input) => createSalesReturn(authFetch, input),
    onSuccess: async (created) => {
      toast.success(
        `تم إنشاء المرتجع المالي #${created.id} بقيمة ${created.credit_amount} ${created.transaction_currency_code}`
      );
      setQuantities({});
      setReason("");

      if (loadedSource) {
        try {
          const refreshed = await fetchSalesReturnSource(
            authFetch,
            loadedSource.visit_id
          );
          setLoadedSource(refreshed);
        } catch {
          setLoadedSource(null);
          setSelectedVisitId(null);
        }
      }

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["sales-returns"] }),
        queryClient.invalidateQueries({ queryKey: ["sales-return-sources"] }),
      ]);
    },
  });

  const selectedComponents = useMemo(
    () =>
      Object.entries(quantities)
        .filter(([, quantity]) => decimalPositive(quantity.trim()))
        .map(([componentId, quantity]) => ({
          original_price_component_id: Number(componentId),
          quantity: quantity.trim(),
        })),
    [quantities]
  );

  const selectedCount = selectedComponents.length;

  if (!access.isCompanyAdmin) {
    return (
      <div className="flex h-full items-center justify-center" dir="rtl">
        <div className="rounded-3xl border border-white/60 bg-white/80 p-8 text-center shadow-sm backdrop-blur-xl">
          <ShieldCheck className="mx-auto mb-3 h-9 w-9 text-slate-700" />
          <h1 className="text-xl font-black text-slate-900">
            مرتجعات البيع للإدارة فقط
          </h1>
          <p className="mt-2 text-sm text-slate-500">
            هذه العملية تنشئ مستندًا ماليًا غير قابل للتعديل.
          </p>
        </div>
      </div>
    );
  }

  const selectSale = (visitId: number) => {
    setSelectedVisitId(visitId);
    sourceMutation.mutate(visitId);
  };

  const applySearch = () => {
    if (dateFromDraft && dateToDraft && dateFromDraft > dateToDraft) {
      toast.error("تاريخ البداية لا يمكن أن يكون بعد تاريخ النهاية.");
      return;
    }
    setSearch(searchDraft.trim());
    setDateFrom(dateFromDraft);
    setDateTo(dateToDraft);
    setSourceCursor(null);
    setSourceCursorHistory([]);
  };

  const clearSourceFilters = () => {
    setSearchDraft("");
    setDateFromDraft("");
    setDateToDraft("");
    setSearch("");
    setDateFrom("");
    setDateTo("");
    setSourceCursor(null);
    setSourceCursorHistory([]);
  };

  const nextSourcePage = () => {
    const next = sourcesQuery.data?.next_cursor;
    if (!next) return;
    setSourceCursorHistory((history) => [...history, sourceCursor]);
    setSourceCursor(next);
  };

  const previousSourcePage = () => {
    setSourceCursorHistory((history) => {
      if (history.length === 0) return history;
      const previous = history[history.length - 1] ?? null;
      setSourceCursor(previous);
      return history.slice(0, -1);
    });
  };

  const setFullRemaining = (componentId: number, available: string) => {
    if (compareDecimal(available, "0") <= 0) return;
    setQuantities((current) => ({
      ...current,
      [componentId]: available,
    }));
  };

  const submit = () => {
    if (!loadedSource || selectedComponents.length === 0) {
      toast.error("حدد البيع والكمية المراد إرجاعها أولاً.");
      return;
    }

    const cleanReason = reason.trim();
    if (cleanReason.length < 3 || cleanReason.length > 1000) {
      toast.error("اكتب سببًا واضحًا للمرتجع بين 3 و1000 حرف.");
      return;
    }

    for (const line of loadedSource.lines) {
      for (const component of line.components) {
        const raw = quantities[component.price_component_id];
        if (!raw?.trim()) continue;
        if (!decimalPositive(raw.trim())) {
          toast.error(`كمية ${line.product_name} غير صالحة.`);
          return;
        }
        if (compareDecimal(raw.trim(), component.available_quantity) > 0) {
          toast.error(
            `كمية ${line.product_name} أكبر من الكمية المتاحة للمرتجع.`
          );
          return;
        }
      }
    }

    createMutation.mutate({
      original_sales_revision_id: loadedSource.sales_revision_id,
      reason: cleanReason,
      components: selectedComponents,
    });
  };

  return (
    <>
      {helpOpen ? <ReturnHelpModal onClose={() => setHelpOpen(false)} /> : null}

      <div
        className="flex h-full min-h-0 flex-col gap-4 overflow-hidden"
        dir="rtl"
      >
        <header className="relative shrink-0 overflow-hidden rounded-[30px] border border-white/70 bg-white/80 p-5 shadow-sm backdrop-blur-xl">
          <div className="pointer-events-none absolute -left-14 -top-20 h-52 w-52 rounded-full bg-slate-100 blur-3xl" />
          <div className="relative flex flex-wrap items-center justify-between gap-4">
            <div className="flex min-w-0 items-center gap-4">
              <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-[20px] bg-slate-950 text-white shadow-lg shadow-slate-200">
                <RotateCcw className="h-6 w-6" />
              </span>
              <div className="min-w-0">
                <div className="mb-1 flex items-center gap-2 text-[11px] font-black text-slate-400">
                  العمليات المالية
                  <span className="h-1 w-1 rounded-full bg-slate-300" />
                  مرتجعات البيع
                </div>
                <h1 className="text-2xl font-black tracking-tight text-slate-950">
                  إنشاء مرتجع مالي
                </h1>
                <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-500">
                  سجّل بضاعة أعادها العميل من بيع سابق، والنظام يحسب الرصيد
                  الدائن من نفس سعر وخصم وضريبة البيع الأصلي.
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setHelpOpen(true)}
                className="inline-flex h-10 items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 text-xs font-black text-slate-700 shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md"
              >
                <HelpCircle className="h-4 w-4" />
                كيف تعمل الصفحة؟
              </button>

              <div className="flex rounded-2xl border border-slate-200 bg-slate-100/80 p-1">
                <button
                  type="button"
                  onClick={() => setActiveView("create")}
                  className={`inline-flex h-9 items-center gap-2 rounded-xl px-4 text-xs font-black transition ${
                    activeView === "create"
                      ? "bg-white text-slate-950 shadow-sm"
                      : "text-slate-500 hover:text-slate-800"
                  }`}
                >
                  <CircleDollarSign className="h-4 w-4" />
                  إنشاء مرتجع
                </button>
                <button
                  type="button"
                  onClick={() => setActiveView("history")}
                  className={`inline-flex h-9 items-center gap-2 rounded-xl px-4 text-xs font-black transition ${
                    activeView === "history"
                      ? "bg-white text-slate-950 shadow-sm"
                      : "text-slate-500 hover:text-slate-800"
                  }`}
                >
                  <History className="h-4 w-4" />
                  السجل المالي
                </button>
              </div>
            </div>
          </div>
        </header>

        {activeView === "create" ? (
          <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[370px_minmax(0,1fr)]">
            <aside className="flex min-h-0 flex-col overflow-hidden rounded-[30px] border border-white/70 bg-white/80 shadow-sm backdrop-blur-xl">
              <div className="shrink-0 border-b border-slate-100 p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <h2 className="text-sm font-black text-slate-900">
                      1. ابحث واختر البيع الأصلي
                    </h2>
                    <p className="mt-1 text-[11px] text-slate-500">
                      هذه المنطقة للعثور على البيع فقط؛ التفاصيل تظهر في المساحة الكبيرة.
                    </p>
                  </div>
                  <span className="flex h-9 w-9 items-center justify-center rounded-2xl bg-slate-100 text-slate-600">
                    <Search className="h-4 w-4" />
                  </span>
                </div>

                <div className="space-y-2.5">
                  <input
                    value={searchDraft}
                    onChange={(event) => setSearchDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") applySearch();
                    }}
                    placeholder="اسم المحل أو رقم الزيارة"
                    className={inputClass}
                  />

                  <div className="grid grid-cols-2 gap-2">
                    <label className="space-y-1">
                      <span className="block text-[10px] font-black text-slate-400">
                        من تاريخ
                      </span>
                      <input
                        type="date"
                        value={dateFromDraft}
                        onChange={(event) => setDateFromDraft(event.target.value)}
                        className={inputClass}
                      />
                    </label>
                    <label className="space-y-1">
                      <span className="block text-[10px] font-black text-slate-400">
                        إلى تاريخ
                      </span>
                      <input
                        type="date"
                        value={dateToDraft}
                        onChange={(event) => setDateToDraft(event.target.value)}
                        className={inputClass}
                      />
                    </label>
                  </div>

                  <div className="grid grid-cols-[1fr_auto] gap-2">
                    <button
                      type="button"
                      onClick={applySearch}
                      className="inline-flex h-10 items-center justify-center gap-2 rounded-2xl bg-slate-950 px-4 text-xs font-black text-white transition hover:bg-slate-800"
                    >
                      <Search className="h-3.5 w-3.5" />
                      تطبيق البحث والفلاتر
                    </button>
                    <button
                      type="button"
                      onClick={clearSourceFilters}
                      className="h-10 rounded-2xl border border-slate-200 bg-white px-3 text-[11px] font-black text-slate-500 transition hover:bg-slate-50"
                    >
                      مسح
                    </button>
                  </div>
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto p-4">
                {sourcesQuery.isPending ? (
                  <div className="flex h-full min-h-48 items-center justify-center rounded-3xl border border-dashed border-slate-200 bg-slate-50/60 text-sm text-slate-500">
                    جاري تحميل المبيعات...
                  </div>
                ) : sourcesQuery.isError ? (
                  <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm font-bold text-rose-700">
                    تعذر تحميل المبيعات القابلة للمرتجع.
                  </div>
                ) : sourcesQuery.data?.items.length ? (
                  <div className="space-y-3">
                    {sourcesQuery.data.items.map((sale) => (
                      <SaleCard
                        key={sale.visit_id}
                        sale={sale}
                        selected={selectedVisitId === sale.visit_id}
                        loading={
                          sourceMutation.isPending &&
                          selectedVisitId === sale.visit_id
                        }
                        onSelect={() => selectSale(sale.visit_id)}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="flex h-full min-h-52 flex-col items-center justify-center rounded-3xl border border-dashed border-slate-200 bg-slate-50/60 p-6 text-center">
                    <ReceiptText className="mb-3 h-8 w-8 text-slate-300" />
                    <strong className="text-sm text-slate-700">
                      لا توجد مبيعات قابلة للمرتجع
                    </strong>
                    <p className="mt-1 text-xs leading-5 text-slate-500">
                      غيّر البحث أو تأكد أن البيع مكتمل وفيه كمية متبقية.
                    </p>
                  </div>
                )}

                {sourcesQuery.data ? (
                  <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3">
                    <button
                      type="button"
                      onClick={previousSourcePage}
                      disabled={sourceCursorHistory.length === 0}
                      className="h-9 rounded-xl border border-slate-200 bg-white px-3 text-[11px] font-black text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-35"
                    >
                      السابق
                    </button>

                    <span className="text-[10px] font-bold text-slate-400">
                      حتى 50 عملية في الصفحة
                    </span>

                    <button
                      type="button"
                      onClick={nextSourcePage}
                      disabled={!sourcesQuery.data.has_more}
                      className="h-9 rounded-xl border border-slate-200 bg-white px-3 text-[11px] font-black text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-35"
                    >
                      التالي
                    </button>
                  </div>
                ) : null}
              </div>
            </aside>

            <main className="flex min-h-0 flex-col overflow-hidden rounded-[30px] border border-white/70 bg-white/80 shadow-sm backdrop-blur-xl">
              {sourceMutation.isPending ? (
                <div className="flex h-full items-center justify-center">
                  <div className="text-center">
                    <span className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100">
                      <PackageOpen className="h-5 w-5 animate-pulse text-slate-500" />
                    </span>
                    <p className="text-sm font-bold text-slate-600">
                      جاري تحميل تفاصيل البيع الأصلي...
                    </p>
                  </div>
                </div>
              ) : sourceMutation.isError ? (
                <div className="m-5 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm font-bold text-rose-700">
                  {sourceMutation.error instanceof Error
                    ? sourceMutation.error.message
                    : "تعذر تحميل البيع الأصلي."}
                </div>
              ) : !loadedSource ? (
                <div className="flex h-full min-h-0 flex-col">
                  <div className="flex flex-1 items-center justify-center p-8">
                    <div className="max-w-xl text-center">
                      <span className="mx-auto mb-5 flex h-20 w-20 items-center justify-center rounded-[28px] border border-slate-200 bg-gradient-to-br from-white to-slate-100 shadow-sm">
                        <ReceiptText className="h-8 w-8 text-slate-400" />
                      </span>
                      <h2 className="text-xl font-black text-slate-900">
                        تفاصيل البيع وإنشاء المرتجع
                      </h2>
                      <p className="mx-auto mt-2 max-w-md text-sm leading-7 text-slate-500">
                        بعد اختيار عملية بيع من القائمة سيظهر هنا كل صنف والكمية
                        المباعة والكمية المتبقية للمرتجع.
                      </p>
                      <div className="mt-5 inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-4 py-2 text-xs font-bold text-slate-500">
                        <ArrowLeft className="h-3.5 w-3.5" />
                        اختر بيعًا من القائمة
                      </div>
                    </div>
                  </div>

                  <div className="shrink-0 border-t border-slate-100 bg-white/95 p-4 backdrop-blur">
                    <button
                      type="button"
                      disabled
                      className="inline-flex h-11 min-w-52 items-center justify-center gap-2 rounded-2xl bg-emerald-700 px-5 text-sm font-black text-white opacity-40"
                    >
                      <CircleDollarSign className="h-4 w-4" />
                      إنشاء مرتجع مالي
                    </button>
                    <p className="mt-2 text-[11px] font-semibold text-slate-400">
                      اختر عملية بيع من القائمة أولًا، ثم حدد الصنف والكمية المرتجعة.
                    </p>
                  </div>
                </div>
              ) : (
                <>
                  <div className="shrink-0 border-b border-slate-100 p-5">
                    <div className="flex flex-wrap items-center justify-between gap-4">
                      <div>
                        <div className="mb-1 flex items-center gap-2 text-[11px] font-black text-slate-400">
                          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                          تم اختيار البيع الأصلي
                        </div>
                        <h2 className="text-lg font-black text-slate-950">
                          {loadedSource.shop.name}
                        </h2>
                        <p className="mt-1 text-xs text-slate-500">
                          زيارة #{loadedSource.visit_id}
                        </p>
                      </div>

                      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-left">
                        <span className="block text-[10px] font-black text-slate-400">
                          قيمة البيع الأصلي
                        </span>
                        <strong className="mt-0.5 block text-lg text-slate-950">
                          {loadedSource.final_amount}{" "}
                          {loadedSource.transaction_currency_code}
                        </strong>
                      </div>
                    </div>
                  </div>

                  <div className="min-h-0 flex-1 overflow-y-auto p-5">
                    <div className="mb-4 flex items-center justify-between">
                      <div>
                        <h3 className="text-sm font-black text-slate-900">
                          2. حدد البضاعة المرتجعة
                        </h3>
                        <p className="mt-1 text-[11px] text-slate-500">
                          أدخل فقط الكمية التي أعادها العميل الآن.
                        </p>
                      </div>
                      <span className="rounded-full bg-slate-100 px-3 py-1.5 text-[11px] font-black text-slate-600">
                        مختار: {selectedCount}
                      </span>
                    </div>

                    <div className="space-y-3">
                      {loadedSource.lines.map((line) => (
                        <div
                          key={line.visit_item_id}
                          className="rounded-3xl border border-slate-200 bg-slate-50/60 p-4"
                        >
                          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                            <div>
                              <strong className="text-sm text-slate-900">
                                {line.product_name}
                              </strong>
                              <p className="mt-1 text-[11px] text-slate-500">
                                صافي السطر الأصلي: {line.net_amount}{" "}
                                {loadedSource.transaction_currency_code}
                              </p>
                            </div>
                          </div>

                          <div className="grid gap-3 md:grid-cols-2">
                            {line.components.map((component) => {
                              const unavailable =
                                compareDecimal(
                                  component.available_quantity,
                                  "0"
                                ) <= 0;

                              return (
                                <div
                                  key={component.price_component_id}
                                  className={`rounded-2xl border p-3 ${
                                    unavailable
                                      ? "border-slate-200 bg-slate-100/80 opacity-70"
                                      : "border-slate-200 bg-white shadow-sm"
                                  }`}
                                >
                                  <div className="mb-3 flex items-start justify-between gap-3">
                                    <div>
                                      <strong className="text-xs text-slate-800">
                                        {component.uom_name}
                                      </strong>
                                      <p className="mt-1 text-[10px] leading-5 text-slate-400">
                                        مباع {component.sold_quantity} · مرتجع
                                        سابقًا {component.returned_quantity}
                                      </p>
                                    </div>

                                    <span
                                      className={`rounded-full px-2.5 py-1 text-[10px] font-black ${
                                        unavailable
                                          ? "bg-slate-200 text-slate-500"
                                          : "bg-emerald-100 text-emerald-700"
                                      }`}
                                    >
                                      المتبقي {component.available_quantity}
                                    </span>
                                  </div>

                                  <div className="flex gap-2">
                                    <input
                                      disabled={unavailable}
                                      value={
                                        quantities[
                                          component.price_component_id
                                        ] ?? ""
                                      }
                                      onChange={(event) =>
                                        setQuantities((current) => ({
                                          ...current,
                                          [component.price_component_id]:
                                            event.target.value,
                                        }))
                                      }
                                      placeholder={
                                        unavailable
                                          ? "تم إرجاع الكمية كاملة"
                                          : "الكمية المرتجعة"
                                      }
                                      className={inputClass}
                                    />
                                    <button
                                      type="button"
                                      disabled={unavailable}
                                      onClick={() =>
                                        setFullRemaining(
                                          component.price_component_id,
                                          component.available_quantity
                                        )
                                      }
                                      className="h-11 shrink-0 rounded-2xl border border-slate-200 bg-white px-3 text-xs font-black text-slate-700 transition hover:bg-slate-50 disabled:opacity-40"
                                    >
                                      الكل
                                    </button>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="shrink-0 border-t border-slate-100 bg-white/95 p-4 backdrop-blur">
                    <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
                      <div>
                        <label className="mb-1.5 block text-[11px] font-black text-slate-600">
                          سبب المرتجع
                        </label>
                        <input
                          value={reason}
                          onChange={(event) => setReason(event.target.value)}
                          maxLength={1000}
                          placeholder="مثال: العميل أعاد الكمية لعدم حاجته إليها"
                          className={inputClass}
                        />
                      </div>

                      <button
                        type="button"
                        onClick={submit}
                        disabled={
                          createMutation.isPending ||
                          selectedCount === 0 ||
                          reason.trim().length < 3
                        }
                        className="mt-auto inline-flex h-11 min-w-52 items-center justify-center gap-2 rounded-2xl bg-emerald-700 px-5 text-sm font-black text-white shadow-lg shadow-emerald-100 transition hover:-translate-y-0.5 hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
                      >
                        <CircleDollarSign className="h-4 w-4" />
                        {createMutation.isPending
                          ? "جاري التثبيت..."
                          : 'إنشاء مرتجع مالي'}
                      </button>
                    </div>

                    <div className="mt-2 flex items-center gap-2 text-[10px] font-semibold text-slate-400">
                      <BadgeDollarSign className="h-3.5 w-3.5" />
                      سيُنشئ النظام إشعارًا دائنًا فقط؛ لا يتم دفع كاش أو تحويل
                      بنكي ولا تحريك المخزون من هذه الصفحة.
                    </div>

                    {createMutation.isError ? (
                      <p className="mt-2 text-xs font-bold text-rose-600">
                        {createMutation.error instanceof Error
                          ? createMutation.error.message
                          : "تعذر إنشاء المرتجع."}
                      </p>
                    ) : null}
                  </div>
                </>
              )}
            </main>
          </div>
        ) : (
          <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[30px] border border-white/70 bg-white/80 shadow-sm backdrop-blur-xl">
            <div className="shrink-0 border-b border-slate-100 p-5">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <div className="mb-1 flex items-center gap-2 text-[11px] font-black text-slate-400">
                    <History className="h-3.5 w-3.5" />
                    للعرض والمتابعة
                  </div>
                  <h2 className="text-lg font-black text-slate-950">
                    سجل المرتجعات المالية
                  </h2>
                  <p className="mt-1 text-xs leading-5 text-slate-500">
                    هنا تظهر الإشعارات الدائنة التي تم تثبيتها سابقًا. هذا السجل
                    لا ينفذ تسوية نقدية أو بنكية.
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => setActiveView("create")}
                  className="inline-flex h-10 items-center gap-2 rounded-2xl bg-slate-950 px-4 text-xs font-black text-white transition hover:bg-slate-800"
                >
                  <CircleDollarSign className="h-4 w-4" />
                  مرتجع جديد
                </button>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-auto p-5">
              {returnsQuery.isPending ? (
                <div className="flex h-full min-h-52 items-center justify-center text-sm text-slate-500">
                  جاري تحميل السجل...
                </div>
              ) : returnsQuery.isError ? (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm font-bold text-rose-700">
                  تعذر تحميل سجل المرتجعات.
                </div>
              ) : returnsQuery.data?.items.length ? (
                <div className="overflow-hidden rounded-3xl border border-slate-200 bg-white">
                  <table className="w-full min-w-[840px] text-sm">
                    <thead className="bg-slate-50 text-right text-[11px] font-black text-slate-500">
                      <tr>
                        <th className="p-4">المستند</th>
                        <th className="p-4">المحل</th>
                        <th className="p-4">البيع الأصلي</th>
                        <th className="p-4">الرصيد الدائن</th>
                        <th className="p-4">الحالة</th>
                        <th className="p-4">التاريخ</th>
                        <th className="p-4">السبب</th>
                      </tr>
                    </thead>
                    <tbody>
                      {returnsQuery.data.items.map((item) => (
                        <tr
                          key={item.id}
                          className="border-t border-slate-100 transition hover:bg-slate-50/70"
                        >
                          <td className="p-4 font-black text-slate-950">
                            #{item.id}
                          </td>
                          <td className="p-4 font-semibold text-slate-800">
                            {item.shop_name}
                          </td>
                          <td className="p-4 text-slate-600">
                            زيارة #{item.original_visit_id}
                          </td>
                          <td className="p-4 font-black text-slate-950">
                            {item.credit_amount}{" "}
                            {item.transaction_currency_code}
                          </td>
                          <td className="p-4">
                            <span className="rounded-full bg-amber-100 px-2.5 py-1 text-[10px] font-black text-amber-800">
                              بانتظار التسوية
                            </span>
                          </td>
                          <td className="p-4 text-xs text-slate-500">
                            {formatDate(item.posted_at)}
                          </td>
                          <td className="max-w-72 truncate p-4 text-slate-600">
                            {item.reason}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="flex h-full min-h-60 flex-col items-center justify-center rounded-3xl border border-dashed border-slate-200 bg-slate-50/60 text-center">
                  <History className="mb-3 h-8 w-8 text-slate-300" />
                  <strong className="text-sm text-slate-700">
                    لا توجد مرتجعات مالية مثبتة حتى الآن
                  </strong>
                  <p className="mt-1 text-xs text-slate-500">
                    عند إنشاء أول مرتجع مالي سيظهر هنا.
                  </p>
                </div>
              )}
            </div>
          </section>
        )}
      </div>
    </>
  );
}
