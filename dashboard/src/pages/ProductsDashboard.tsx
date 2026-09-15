import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Boxes,
  ChevronLeft,
  ChevronRight,
  FileUp,
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

type SimpleProduct = {
  id: number;
  product_id: number;
  name: string;
  code: string;
  units_per_carton: number;
  currency_code: string;
  carton_price: string | null;
  unit_price: string | null;
  lifecycle_status: string;
  simple_compatible: boolean;
};

type SimpleProductPage = {
  currency_code: string;
  items: SimpleProduct[];
  next_cursor: string | null;
  has_more: boolean;
};

const requestId = () => crypto.randomUUID();

const parsePage = (raw: unknown): SimpleProductPage => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("استجابة المنتجات غير صالحة.");
  }
  const value = raw as Record<string, unknown>;
  if (
    typeof value.currency_code !== "string" ||
    !Array.isArray(value.items) ||
    typeof value.has_more !== "boolean" ||
    (value.next_cursor !== null &&
      typeof value.next_cursor !== "string")
  ) {
    throw new Error("استجابة المنتجات غير مكتملة.");
  }

  const items = value.items.map((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      throw new Error("بيانات منتج غير صالحة.");
    }
    const row = item as Record<string, unknown>;
    if (
      !Number.isSafeInteger(row.id) ||
      Number(row.id) <= 0 ||
      !Number.isSafeInteger(row.product_id) ||
      Number(row.product_id) <= 0 ||
      typeof row.name !== "string" ||
      typeof row.code !== "string" ||
      !Number.isSafeInteger(row.units_per_carton) ||
      Number(row.units_per_carton) <= 0 ||
      typeof row.currency_code !== "string" ||
      typeof row.lifecycle_status !== "string" ||
      typeof row.simple_compatible !== "boolean"
    ) {
      throw new Error("بيانات منتج غير مكتملة.");
    }

    const money = (field: "carton_price" | "unit_price") => {
      const fieldValue = row[field];
      if (fieldValue === null || typeof fieldValue === "string") {
        return fieldValue as string | null;
      }
      throw new Error("قيمة سعر غير صالحة.");
    };

    return {
      id: Number(row.id),
      product_id: Number(row.product_id),
      name: row.name,
      code: row.code,
      units_per_carton: Number(row.units_per_carton),
      currency_code: row.currency_code,
      carton_price: money("carton_price"),
      unit_price: money("unit_price"),
      lifecycle_status: row.lifecycle_status,
      simple_compatible: row.simple_compatible,
    };
  });

  return {
    currency_code: value.currency_code,
    items,
    next_cursor: value.next_cursor as string | null,
    has_more: value.has_more,
  };
};

const formatMoney = (value: string | null) => {
  if (value === null) return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString("ar-JO", {
        minimumFractionDigits: 3,
        maximumFractionDigits: 6,
      })
    : value;
};

const derivePreview = (
  cartonPrice: string,
  units: string
) => {
  const price = Number(cartonPrice);
  const count = Number(units);
  if (
    !Number.isFinite(price) ||
    price <= 0 ||
    !Number.isInteger(count) ||
    count <= 0
  ) {
    return null;
  }
  return price / count;
};

const emptyDraft = {
  name: "",
  code: "",
  units_per_carton: "50",
  carton_price: "",
};

export default function ProductsDashboard() {
  const authFetch = useAuthFetch();
  const queryClient = useQueryClient();
  const access = useInventoryAccess();

  const canManage =
    access.isCompanyAdmin ||
    (
      access.canAny("catalog.manage") &&
      access.canAny("catalog.publish") &&
      access.canAny("pricing.manage")
    );

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [history, setHistory] = useState<Array<string | null>>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [csvOpen, setCsvOpen] = useState(false);
  const [draft, setDraft] = useState(emptyDraft);
  const [csvText, setCsvText] = useState("");
  const [csvName, setCsvName] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [priceDraft, setPriceDraft] = useState("");
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
      parsePage(
        await authFetch(`/simple-products?${params}`, { signal })
      ),
  });

  const page = productsQuery.data;
  const currency = page?.currency_code || "—";

  const createMutation = useMutation({
    mutationFn: async () => {
      const units = Number(draft.units_per_carton);
      if (!draft.name.trim()) {
        throw new Error("اسم المنتج مطلوب.");
      }
      if (
        !Number.isSafeInteger(units) ||
        units <= 0
      ) {
        throw new Error(
          "عدد الحبات في الكرتونة يجب أن يكون رقماً صحيحاً موجباً."
        );
      }
      const price = Number(draft.carton_price);
      if (!Number.isFinite(price) || price <= 0) {
        throw new Error("سعر الكرتونة يجب أن يكون أكبر من صفر.");
      }

      return authFetch("/simple-products", {
        method: "POST",
        body: JSON.stringify({
          request_id: requestId(),
          name: draft.name.trim(),
          code: draft.code.trim() || null,
          units_per_carton: units,
          carton_price: draft.carton_price,
        }),
      });
    },
    onSuccess: async () => {
      toast.success("تم إنشاء المنتج واعتماد سعره.");
      setDraft(emptyDraft);
      setCreateOpen(false);
      setCursor(null);
      setHistory([]);
      await queryClient.invalidateQueries({
        queryKey: ["simple-products"],
      });
    },
    onError: (error) =>
      toast.error(
        apiErrorMessage(error, "تعذر إنشاء المنتج.")
      ),
  });

  const priceMutation = useMutation({
    mutationFn: async ({
      id,
      price,
    }: {
      id: number;
      price: string;
    }) => {
      const numeric = Number(price);
      if (!Number.isFinite(numeric) || numeric <= 0) {
        throw new Error(
          "سعر الكرتونة يجب أن يكون أكبر من صفر."
        );
      }
      return authFetch(`/simple-products/${id}/price`, {
        method: "PATCH",
        body: JSON.stringify({
          request_id: requestId(),
          carton_price: price,
        }),
      });
    },
    onSuccess: async () => {
      toast.success("تم تحديث السعر.");
      setEditingId(null);
      setPriceDraft("");
      await queryClient.invalidateQueries({
        queryKey: ["simple-products"],
      });
    },
    onError: (error) =>
      toast.error(
        apiErrorMessage(error, "تعذر تحديث السعر.")
      ),
  });

  const csvMutation = useMutation({
    mutationFn: async () => {
      if (!csvText.trim()) {
        throw new Error("اختر ملف CSV أولاً.");
      }
      return authFetch("/simple-products/import-csv", {
        method: "POST",
        body: JSON.stringify({
          request_id: requestId(),
          csv_text: csvText,
        }),
      }) as Promise<{
        message?: string;
        imported_count?: number;
      }>;
    },
    onSuccess: async (result) => {
      toast.success(
        typeof result?.message === "string"
          ? result.message
          : "تم استيراد المنتجات."
      );
      setCsvOpen(false);
      setCsvText("");
      setCsvName("");
      setCursor(null);
      setHistory([]);
      await queryClient.invalidateQueries({
        queryKey: ["simple-products"],
      });
    },
    onError: (error) =>
      toast.error(
        apiErrorMessage(error, "تعذر استيراد الملف.")
      ),
  });

  const loadCsv = async (file: File | undefined) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".csv")) {
      toast.error("اختر ملف CSV.");
      return;
    }
    if (file.size > 5_000_000) {
      toast.error("حجم الملف أكبر من الحد المسموح.");
      return;
    }
    setCsvText(await file.text());
    setCsvName(file.name);
  };

  const downloadTemplate = () => {
    const sample = [
      "name,units_per_carton,carton_price,code",
      "شيبس لولو,50,17.500,LOLO",
    ].join("\n");
    const blob = new Blob(
      ["\ufeff", sample],
      { type: "text/csv;charset=utf-8" }
    );
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = "products-template.csv";
    anchor.click();
    URL.revokeObjectURL(href);
  };

  const previewUnit = derivePreview(
    draft.carton_price,
    draft.units_per_carton
  );

  return (
    <div
      className="flex min-h-0 flex-1 flex-col overflow-hidden"
      dir="rtl"
    >
      <header className="shrink-0 rounded-[26px] border border-white/70 bg-white/85 px-5 py-4 shadow-sm backdrop-blur-xl">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-[16px] bg-slate-950 text-white">
              <Boxes className="h-5 w-5" />
            </span>
            <div>
              <h1 className="text-xl font-black text-slate-950">
                المنتجات
              </h1>
              <p className="mt-0.5 text-xs font-semibold text-slate-500">
                المنتج وسعره في مكان واحد — أدخل سعر الكرتونة فقط.
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
                  productsQuery.isFetching
                    ? "animate-spin"
                    : ""
                }`}
              />
              تحديث
            </button>

            {canManage ? (
              <>
                <button
                  type="button"
                  onClick={() => setCsvOpen(true)}
                  disabled={!page}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700 disabled:opacity-40"
                >
                  <FileUp className="h-4 w-4" />
                  استيراد CSV
                </button>
                <button
                  type="button"
                  onClick={() => setCreateOpen(true)}
                  disabled={!page}
                  className="inline-flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2 text-xs font-black text-white shadow-sm disabled:opacity-40"
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
              onChange={(event) =>
                setSearchInput(event.target.value)
              }
              placeholder="ابحث باسم المنتج أو رمزه..."
              className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2.5 pl-3 pr-9 text-sm font-bold outline-none transition focus:border-slate-400 focus:bg-white"
            />
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-auto">
          <table className="w-full min-w-[760px] text-right text-sm">
            <thead className="sticky top-0 z-10 bg-slate-50 text-xs font-black text-slate-500">
              <tr>
                <th className="px-5 py-3">المنتج</th>
                <th className="px-5 py-3">
                  الحبات / كرتونة
                </th>
                <th className="px-5 py-3">
                  سعر الكرتونة
                </th>
                <th className="px-5 py-3">
                  سعر الحبة
                </th>
                <th className="px-5 py-3">الإجراء</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-slate-100">
              {productsQuery.isLoading ? (
                <tr>
                  <td
                    colSpan={5}
                    className="py-16 text-center font-bold text-slate-400"
                  >
                    جاري تحميل المنتجات...
                  </td>
                </tr>
              ) : null}

              {productsQuery.isError ? (
                <tr>
                  <td
                    colSpan={5}
                    className="py-16 text-center"
                  >
                    <p className="font-black text-rose-700">
                      تعذر تحميل المنتجات
                    </p>
                    <button
                      type="button"
                      onClick={() => void productsQuery.refetch()}
                      className="mt-3 rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-black text-slate-700"
                    >
                      إعادة المحاولة
                    </button>
                  </td>
                </tr>
              ) : null}

              {!productsQuery.isLoading &&
              !productsQuery.isError &&
              !page?.items.length ? (
                <tr>
                  <td
                    colSpan={5}
                    className="py-16 text-center"
                  >
                    <Boxes className="mx-auto mb-3 h-8 w-8 text-slate-300" />
                    <p className="font-black text-slate-700">
                      لا توجد منتجات بعد
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      أضف أول منتج أو استورد ملف CSV.
                    </p>
                  </td>
                </tr>
              ) : null}

              {page?.items.map((item) => {
                const editing = editingId === item.id;
                const liveUnit =
                  editing && item.simple_compatible
                    ? derivePreview(
                        priceDraft,
                        String(item.units_per_carton)
                      )
                    : null;

                return (
                  <tr
                    key={item.id}
                    className="bg-white transition hover:bg-slate-50/70"
                  >
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-2">
                        <span className="font-black text-slate-900">
                          {item.name}
                        </span>
                        {item.lifecycle_status === "RETIRING" ? (
                          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[9px] font-black text-amber-800">
                            إيقاف تدريجي
                          </span>
                        ) : null}
                        {!item.simple_compatible ? (
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[9px] font-black text-slate-600">
                            إعداد قديم غير متوافق
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-1 text-[10px] font-mono text-slate-400">
                        {item.code}
                      </div>
                    </td>

                    <td className="px-5 py-4 font-black tabular-nums">
                      {item.units_per_carton}
                    </td>

                    <td className="px-5 py-4">
                      {editing ? (
                        <div className="flex items-center gap-2">
                          <input
                            autoFocus
                            inputMode="decimal"
                            value={priceDraft}
                            onChange={(event) =>
                              setPriceDraft(event.target.value)
                            }
                            className="w-32 rounded-xl border border-slate-300 px-3 py-2 font-black tabular-nums outline-none focus:border-slate-500"
                          />
                          <span className="text-xs font-black text-slate-400">
                            {item.currency_code}
                          </span>
                        </div>
                      ) : (
                        <span className="font-black tabular-nums text-slate-900">
                          {formatMoney(item.carton_price)}{" "}
                          {item.currency_code}
                        </span>
                      )}
                    </td>

                    <td className="px-5 py-4">
                      <span className="font-bold tabular-nums text-slate-600">
                        {editing && liveUnit !== null
                          ? liveUnit.toLocaleString("ar-JO", {
                              minimumFractionDigits: 3,
                              maximumFractionDigits: 6,
                            })
                          : formatMoney(item.unit_price)}{" "}
                        {item.currency_code}
                      </span>
                      <div className="mt-1 text-[10px] text-slate-400">
                        محسوب تلقائيًا
                      </div>
                    </td>

                    <td className="px-5 py-4">
                      {!canManage ||
                      !item.simple_compatible ? (
                        "—"
                      ) : editing ? (
                        <div className="flex gap-2">
                          <button
                            type="button"
                            disabled={priceMutation.isPending}
                            onClick={() =>
                              priceMutation.mutate({
                                id: item.id,
                                price: priceDraft,
                              })
                            }
                            className="rounded-xl bg-slate-950 px-3 py-2 text-xs font-black text-white disabled:opacity-50"
                          >
                            حفظ
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setEditingId(null);
                              setPriceDraft("");
                            }}
                            className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-black text-slate-600"
                          >
                            إلغاء
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            setEditingId(item.id);
                            setPriceDraft(
                              item.carton_price || ""
                            );
                          }}
                          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700 hover:bg-slate-50"
                        >
                          تعديل السعر
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {history.length > 0 || page?.next_cursor ? (
          <div className="flex shrink-0 justify-end gap-2 border-t border-slate-100 bg-slate-50 px-4 py-3">
            <button
              type="button"
              disabled={
                !history.length ||
                productsQuery.isFetching
              }
              onClick={() => {
                const previous =
                  history.at(-1) ?? null;
                setHistory((current) =>
                  current.slice(0, -1)
                );
                setCursor(previous);
              }}
              className="rounded-lg border border-slate-200 bg-white p-2 disabled:opacity-30"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
            <button
              type="button"
              disabled={
                !page?.next_cursor ||
                productsQuery.isFetching
              }
              onClick={() => {
                if (!page?.next_cursor) return;
                setHistory((current) => [
                  ...current,
                  cursor,
                ]);
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
        onClose={() =>
          !createMutation.isPending &&
          setCreateOpen(false)
        }
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
              حفظ المنتج والسعر
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="rounded-2xl bg-emerald-50 p-3 text-xs font-bold leading-6 text-emerald-900">
            أدخل سعر الكرتونة فقط. النظام سيحسب سعر
            الحبة ويعتمده تلقائيًا.
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-black text-slate-600 sm:col-span-2">
              اسم المنتج
              <input
                value={draft.name}
                maxLength={150}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                placeholder="مثال: شيبس لولو"
                className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-bold outline-none focus:border-slate-400"
              />
            </label>

            <label className="text-xs font-black text-slate-600">
              عدد الحبات في الكرتونة
              <input
                inputMode="numeric"
                value={draft.units_per_carton}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    units_per_carton:
                      event.target.value,
                  }))
                }
                className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-bold outline-none focus:border-slate-400"
              />
            </label>

            <label className="text-xs font-black text-slate-600">
              سعر الكرتونة
              <div className="mt-1.5 flex overflow-hidden rounded-xl border border-slate-200 bg-white">
                <input
                  inputMode="decimal"
                  value={draft.carton_price}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      carton_price:
                        event.target.value,
                    }))
                  }
                  placeholder="0.000"
                  className="min-w-0 flex-1 px-3 py-2.5 text-sm font-black outline-none"
                />
                <span className="flex items-center bg-slate-50 px-3 text-xs font-black text-slate-500">
                  {currency}
                </span>
              </div>
            </label>
          </div>

          <div className="rounded-[22px] border border-slate-200 bg-slate-50 p-4">
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs font-black text-slate-500">
                سعر الحبة المحسوب
              </span>
              <strong className="text-lg font-black tabular-nums text-slate-950">
                {previewUnit === null
                  ? "—"
                  : previewUnit.toLocaleString(
                      "ar-JO",
                      {
                        minimumFractionDigits: 3,
                        maximumFractionDigits: 6,
                      }
                    )}{" "}
                {currency}
              </strong>
            </div>
          </div>

          <details className="rounded-2xl border border-slate-200 bg-white p-3">
            <summary className="cursor-pointer text-xs font-black text-slate-600">
              رمز المنتج (اختياري)
            </summary>
            <div className="mt-3">
              <input
                value={draft.code}
                maxLength={100}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    code: event.target.value,
                  }))
                }
                placeholder="اتركه فارغًا لينشئه النظام"
                className="w-full rounded-xl border border-slate-200 p-2.5 text-sm font-bold outline-none"
              />
            </div>
          </details>
        </div>
      </Modal>

      <Modal
        isOpen={csvOpen}
        onClose={() =>
          !csvMutation.isPending &&
          setCsvOpen(false)
        }
        title="استيراد المنتجات من CSV"
        maxWidth="max-w-xl"
        footer={
          <>
            <button
              type="button"
              disabled={csvMutation.isPending}
              onClick={() => setCsvOpen(false)}
              className="px-4 py-2 text-sm font-bold text-slate-600"
            >
              إلغاء
            </button>
            <button
              type="button"
              disabled={
                csvMutation.isPending ||
                !csvText
              }
              onClick={() => csvMutation.mutate()}
              className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-black text-white disabled:opacity-40"
            >
              استيراد المنتجات والأسعار
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="rounded-2xl bg-sky-50 p-3 text-xs font-bold leading-6 text-sky-900">
            كل صف = منتج واحد. أدخل عدد الحبات وسعر
            الكرتونة، والنظام يحسب سعر الحبة تلقائيًا.
          </div>

          <button
            type="button"
            onClick={downloadTemplate}
            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700"
          >
            تحميل نموذج CSV
          </button>

          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(event) =>
              void loadCsv(
                event.target.files?.[0]
              )
            }
          />

          <button
            type="button"
            onClick={() =>
              fileRef.current?.click()
            }
            className="flex min-h-40 w-full flex-col items-center justify-center rounded-[22px] border border-dashed border-slate-300 bg-slate-50 text-center transition hover:border-slate-400 hover:bg-white"
          >
            <Upload className="mb-3 h-7 w-7 text-slate-400" />
            <strong className="text-sm text-slate-700">
              {csvName || "اختر ملف CSV"}
            </strong>
            <span className="mt-1 text-xs text-slate-400">
              حتى 200 منتج في العملية الواحدة
            </span>
          </button>
        </div>
      </Modal>
    </div>
  );
}
