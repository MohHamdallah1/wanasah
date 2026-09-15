import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CircleDollarSign,
  ReceiptText,
  RotateCcw,
  Search,
  ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import {
  createSalesReturn,
  fetchSalesReturns,
  fetchSalesReturnSource,
} from "@/features/salesReturns/api";
import type { SalesReturnSource } from "@/features/salesReturns/contracts";

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

export default function SalesReturnsDashboard() {
  const access = useInventoryAccess();
  const authFetch = useAuthFetch();
  const queryClient = useQueryClient();
  const [visitId, setVisitId] = useState("");
  const [loadedSource, setLoadedSource] = useState<SalesReturnSource | null>(null);
  const [reason, setReason] = useState("");
  const [quantities, setQuantities] = useState<Record<number, string>>({});

  const returnsQuery = useQuery({
    queryKey: ["sales-returns"],
    queryFn: () => fetchSalesReturns(authFetch),
    enabled: access.isCompanyAdmin,
  });

  const sourceMutation = useMutation({
    mutationFn: (id: number) => fetchSalesReturnSource(authFetch, id),
    onSuccess: (source) => {
      setLoadedSource(source);
      setQuantities({});
    },
  });

  const createMutation = useMutation({
    mutationFn: createSalesReturn.bind(null, authFetch),
    onSuccess: async (created) => {
      toast.success(`تم إنشاء إشعار دائن #${created.id}`);
      setReason("");
      setQuantities({});
      if (loadedSource) {
        const refreshed = await fetchSalesReturnSource(
          authFetch,
          loadedSource.visit_id
        );
        setLoadedSource(refreshed);
      }
      await queryClient.invalidateQueries({ queryKey: ["sales-returns"] });
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

  if (!access.isCompanyAdmin) {
    return (
      <div className="flex h-full items-center justify-center" dir="rtl">
        <div className="rounded-3xl border bg-white/70 p-8 text-center shadow-sm">
          <ShieldCheck className="mx-auto mb-3 h-9 w-9" />
          <h1 className="text-xl font-black">مرتجعات البيع للإدارة فقط</h1>
        </div>
      </div>
    );
  }

  const loadSource = () => {
    const id = Number(visitId);
    if (!Number.isSafeInteger(id) || id <= 0) {
      toast.error("أدخل رقم زيارة صالح.");
      return;
    }
    sourceMutation.mutate(id);
  };

  const submit = () => {
    if (!loadedSource || selectedComponents.length === 0) {
      toast.error("اختر كمية مرتجعة واحدة على الأقل.");
      return;
    }
    const cleanReason = reason.trim();
    if (cleanReason.length < 3 || cleanReason.length > 1000) {
      toast.error("سبب المرتجع يجب أن يكون بين 3 و1000 حرف.");
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
          toast.error(`الكمية تتجاوز المتاح للمرتجع: ${line.product_name}.`);
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
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-auto pb-8" dir="rtl">
      <header className="rounded-3xl border border-white/60 bg-white/70 p-5 shadow-sm backdrop-blur-xl">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2 text-sm font-bold text-slate-500">
              <RotateCcw className="h-4 w-4" />
              Sales Return / Credit Note
            </div>
            <h1 className="text-2xl font-black text-slate-900">مرتجعات البيع المالية</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              العكس يُبنى حصراً من سطور البيع الأصلية المجمدة؛ لا إعادة تسعير،
              ولا إعادة تشغيل عروض أو ضرائب اليوم.
            </p>
          </div>
          <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs font-bold text-amber-800">
            إشعار دائن غير مسوّى — لا ينفذ رد نقدي تلقائي.
          </div>
        </div>
      </header>

      <section className="rounded-3xl border border-white/60 bg-white/75 p-5 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <Search className="h-5 w-5 text-slate-500" />
          <h2 className="font-black">اختيار البيع الأصلي</h2>
        </div>
        <div className="flex flex-wrap gap-3">
          <input
            value={visitId}
            onChange={(event) => setVisitId(event.target.value)}
            inputMode="numeric"
            placeholder="رقم الزيارة"
            className="h-11 min-w-56 rounded-xl border border-slate-200 bg-white px-4 outline-none focus:border-slate-400"
          />
          <button
            onClick={loadSource}
            disabled={sourceMutation.isPending}
            className="h-11 rounded-xl bg-slate-900 px-5 font-bold text-white disabled:opacity-50"
          >
            {sourceMutation.isPending ? "جاري التحميل..." : "عرض السطور الأصلية"}
          </button>
        </div>

        {sourceMutation.isError ? (
          <p className="mt-3 text-sm font-bold text-red-600">
            {sourceMutation.error instanceof Error
              ? sourceMutation.error.message
              : "تعذر تحميل البيع الأصلي."}
          </p>
        ) : null}
      </section>

      {loadedSource ? (
        <section className="rounded-3xl border border-white/60 bg-white/75 p-5 shadow-sm">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-black">
                {loadedSource.shop.name} — زيارة #{loadedSource.visit_id}
              </h2>
              <p className="mt-1 text-xs font-bold text-slate-500">
                Revision #{loadedSource.sales_revision_id} · أصل الفاتورة{" "}
                {loadedSource.final_amount} {loadedSource.transaction_currency_code}
              </p>
            </div>
            <ReceiptText className="h-7 w-7 text-slate-400" />
          </div>

          <div className="space-y-4">
            {loadedSource.lines.map((line) => (
              <div key={line.visit_item_id} className="rounded-2xl border border-slate-200 bg-slate-50/60 p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <strong>{line.product_name}</strong>
                  <span className="text-xs font-bold text-slate-500">
                    صافي السطر الأصلي: {line.net_amount} {loadedSource.transaction_currency_code}
                  </span>
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  {line.components.map((component) => (
                    <div key={component.price_component_id} className="rounded-xl border bg-white p-3">
                      <div className="mb-2 flex items-center justify-between text-xs font-bold text-slate-500">
                        <span>{component.uom_name} ({component.uom_code})</span>
                        <span>المتاح: {component.available_quantity}</span>
                      </div>
                      <input
                        value={quantities[component.price_component_id] ?? ""}
                        onChange={(event) =>
                          setQuantities((current) => ({
                            ...current,
                            [component.price_component_id]: event.target.value,
                          }))
                        }
                        placeholder="كمية المرتجع"
                        className="h-10 w-full rounded-lg border border-slate-200 px-3 outline-none focus:border-slate-400"
                      />
                      <div className="mt-2 text-[11px] text-slate-400">
                        المباع {component.sold_quantity} · مرتجع سابقًا {component.returned_quantity} · سعر الأصل {component.unit_price}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-[1fr_auto]">
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={1000}
              placeholder="سبب المرتجع المالي"
              className="min-h-24 rounded-xl border border-slate-200 bg-white p-3 outline-none focus:border-slate-400"
            />
            <button
              onClick={submit}
              disabled={createMutation.isPending}
              className="min-h-12 rounded-xl bg-emerald-700 px-6 font-black text-white disabled:opacity-50"
            >
              {createMutation.isPending ? "جاري التثبيت..." : "تثبيت الإشعار الدائن"}
            </button>
          </div>

          {createMutation.isError ? (
            <p className="mt-3 text-sm font-bold text-red-600">
              {createMutation.error instanceof Error
                ? createMutation.error.message
                : "تعذر إنشاء المرتجع."}
            </p>
          ) : null}
        </section>
      ) : null}

      <section className="rounded-3xl border border-white/60 bg-white/75 p-5 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <CircleDollarSign className="h-5 w-5 text-slate-500" />
          <h2 className="font-black">آخر الإشعارات الدائنة</h2>
        </div>
        {returnsQuery.isPending ? (
          <p className="text-sm text-slate-500">جاري التحميل...</p>
        ) : returnsQuery.isError ? (
          <p className="text-sm font-bold text-red-600">تعذر تحميل المرتجعات.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="text-right text-xs text-slate-500">
                <tr className="border-b">
                  <th className="p-3">المستند</th>
                  <th className="p-3">المحل</th>
                  <th className="p-3">الزيارة الأصلية</th>
                  <th className="p-3">الرصيد الدائن</th>
                  <th className="p-3">التسوية</th>
                  <th className="p-3">السبب</th>
                </tr>
              </thead>
              <tbody>
                {returnsQuery.data?.items.map((item) => (
                  <tr key={item.id} className="border-b border-slate-100">
                    <td className="p-3 font-black">#{item.id}</td>
                    <td className="p-3">{item.shop_name}</td>
                    <td className="p-3">#{item.original_visit_id}</td>
                    <td className="p-3 font-black">
                      {item.credit_amount} {item.transaction_currency_code}
                    </td>
                    <td className="p-3">
                      <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-bold text-amber-800">
                        غير مسوّى
                      </span>
                    </td>
                    <td className="max-w-64 truncate p-3">{item.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
