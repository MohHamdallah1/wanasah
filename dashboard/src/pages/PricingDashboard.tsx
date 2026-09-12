import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BadgeDollarSign,
  BookOpen,
  CheckCircle2,
  Layers3,
  Link2,
  Pencil,
  Plus,
  RefreshCw,
  Rocket,
  Search,
  ShieldCheck,
  Trash2,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useTenantIdentity } from "@/features/tenantIdentity/useTenantIdentity";

type Page<T> = {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
};

type PriceBook = {
  id: number;
  code: string;
  name: string;
  currency_code: string;
  status: string;
  applicability_metadata: Record<string, unknown>;
  version: number;
  created_by: number;
  created_at: string | null;
  updated_at: string | null;
};

type PricePublication = {
  id: number;
  price_book_id: number;
  revision: number;
  status:
    | "DRAFT"
    | "PENDING_APPROVAL"
    | "PUBLISHED"
    | "SUPERSEDED"
    | "CANCELLED";
  effective_at: string | null;
  created_by: number;
  approved_by: number | null;
  approved_at: string | null;
  published_at: string | null;
  request_id: string;
  version: number;
  created_at: string | null;
  updated_at: string | null;
};

type PriceEntry = {
  id: number;
  price_book_id: number;
  publication_id: number;
  product_variant_id: number;
  uom_id: number;
  amount: string;
  effective_from: string;
  effective_to: string | null;
  priority: number;
  metadata: Record<string, unknown>;
  is_published: boolean;
  version: number;
};

type PriceAssignment = {
  id: number;
  price_book_id: number;
  scope_type: "CUSTOMER" | "BRANCH" | "COMPANY_DEFAULT";
  scope_id: number | null;
  priority: number;
  effective_from: string;
  effective_to: string | null;
  revision: number;
  version: number;
  created_by: number;
};

type CatalogVariant = {
  id: number;
  product_id: number;
  sku: string;
  name: string;
  base_uom: { id: number; code: string; name: string };
  lifecycle_status: string;
};

type Uom = {
  id: number;
  code: string;
  name: string;
};

type ResolvePreviewResult = {
  price_book_id: number;
  assignment: {
    id: number;
    revision: number;
    scope_type: string;
    priority: number;
  };
  price: {
    entry_id: number;
    publication_id: number;
    publication_revision: number;
    product_variant_id: number;
    uom_id: number;
    amount: string;
    currency_code: string;
  };
  resolved_at: string;
};

type AuthFetch = ReturnType<typeof useAuthFetch>;

const MAX_PAGES = 25;
const PAGE_SIZE = 200;

const requestId = () => crypto.randomUUID();

const toLocalInput = (value: Date = new Date()) => {
  const shifted = new Date(value.getTime() - value.getTimezoneOffset() * 60_000);
  return shifted.toISOString().slice(0, 16);
};

const toIso = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) throw new Error("التاريخ غير صالح.");
  return date.toISOString();
};

const formatDate = (value: string | null) => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : new Intl.DateTimeFormat("ar", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
};

const numericId = (value: string, field: string): number => {
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new Error(`${field} يجب أن يكون رقماً صحيحاً موجباً.`);
  }
  return parsed;
};

async function fetchAll<T>(authFetch: AuthFetch, basePath: string): Promise<T[]> {
  const rows: T[] = [];
  let cursor: string | null = null;

  for (let page = 0; page < MAX_PAGES; page += 1) {
    const separator = basePath.includes("?") ? "&" : "?";
    const path =
      `${basePath}${separator}limit=${PAGE_SIZE}` +
      (cursor ? `&cursor=${encodeURIComponent(cursor)}` : "");
    const response = (await authFetch(path)) as Page<T>;

    if (!response || !Array.isArray(response.items)) {
      throw new Error("عقد صفحة التسعير غير صالح.");
    }
    rows.push(...response.items);

    if (!response.has_more) return rows;
    if (!response.next_cursor) {
      throw new Error("السيرفر أعلن عن صفحة تالية دون cursor.");
    }
    cursor = response.next_cursor;
  }

  throw new Error(
    "عدد سجلات التسعير أكبر من حد شاشة الإدارة الحالية؛ استخدم البحث أو التقسيم قبل المتابعة."
  );
}

const statusLabel: Record<PricePublication["status"], string> = {
  DRAFT: "مسودة",
  PENDING_APPROVAL: "بانتظار الاعتماد",
  PUBLISHED: "منشورة",
  SUPERSEDED: "مستبدلة",
  CANCELLED: "ملغاة",
};

const statusClass: Record<PricePublication["status"], string> = {
  DRAFT: "bg-amber-100 text-amber-800",
  PENDING_APPROVAL: "bg-sky-100 text-sky-800",
  PUBLISHED: "bg-emerald-100 text-emerald-800",
  SUPERSEDED: "bg-slate-200 text-slate-700",
  CANCELLED: "bg-rose-100 text-rose-700",
};

function Panel({
  title,
  subtitle,
  icon: Icon,
  children,
}: {
  title: string;
  subtitle?: string;
  icon: typeof BookOpen;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-3xl border border-white/60 bg-white/70 p-5 shadow-sm backdrop-blur-xl">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-black text-slate-900">
            <span className="rounded-xl bg-slate-900 p-2 text-white">
              <Icon className="h-4 w-4" />
            </span>
            {title}
          </h2>
          {subtitle ? (
            <p className="mt-1 text-xs font-medium text-slate-500">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {children}
    </section>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1.5 text-xs font-bold text-slate-600">
      {label}
      {children}
    </label>
  );
}

const inputClass =
  "h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200";
const primaryButton =
  "inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-slate-900 px-4 text-sm font-black text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40";
const softButton =
  "inline-flex h-9 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-xs font-black text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40";

export default function PricingDashboard() {
  const authFetch = useAuthFetch();
  const queryClient = useQueryClient();
  const access = useInventoryAccess();
  const tenantIdentity = useTenantIdentity();
  const canManage = access.isCompanyAdmin || access.canAny("pricing.manage");
  const canApprove = access.isCompanyAdmin || access.canAny("pricing.approve");

  const [selectedBookId, setSelectedBookId] = useState<number | null>(null);
  const [selectedPublicationId, setSelectedPublicationId] = useState<number | null>(
    null
  );

  const [bookForm, setBookForm] = useState({
    code: "",
    name: "",
    currency_code: "",
  });
  const [publicationEffectiveAt, setPublicationEffectiveAt] = useState(
    toLocalInput()
  );
  const [entryForm, setEntryForm] = useState({
    product_variant_id: "",
    uom_id: "",
    amount: "",
    effective_from: toLocalInput(),
    effective_to: "",
    priority: "0",
  });
  const [editingEntryId, setEditingEntryId] = useState<number | null>(null);
  const [assignmentForm, setAssignmentForm] = useState({
    price_book_id: "",
    scope_type: "COMPANY_DEFAULT" as
      | "CUSTOMER"
      | "BRANCH"
      | "COMPANY_DEFAULT",
    scope_id: "",
    priority: "0",
    effective_from: toLocalInput(),
    effective_to: "",
  });
  const [previewForm, setPreviewForm] = useState({
    product_variant_id: "",
    uom_id: "",
    customer_id: "",
    branch_id: "",
  });
  const [preview, setPreview] = useState<ResolvePreviewResult | null>(null);

  const booksQuery = useQuery({
    queryKey: ["pricing", "books"],
    queryFn: () => fetchAll<PriceBook>(authFetch, "/pricing/books"),
    retry: false,
  });
  const assignmentsQuery = useQuery({
    queryKey: ["pricing", "assignments"],
    queryFn: () =>
      fetchAll<PriceAssignment>(authFetch, "/pricing/assignments"),
    retry: false,
  });
  const variantsQuery = useQuery({
    queryKey: ["pricing", "catalog-variants"],
    queryFn: () =>
      fetchAll<CatalogVariant>(authFetch, "/catalog/variants"),
    retry: false,
  });
  const uomsQuery = useQuery({
    queryKey: ["pricing", "uoms"],
    queryFn: async () => {
      const response = (await authFetch("/catalog/uoms")) as { items: Uom[] };
      if (!response || !Array.isArray(response.items)) {
        throw new Error("عقد وحدات القياس غير صالح.");
      }
      return response.items;
    },
    retry: false,
  });

  const publicationsQuery = useQuery({
    queryKey: ["pricing", "publications", selectedBookId],
    enabled: selectedBookId !== null,
    queryFn: () =>
      fetchAll<PricePublication>(
        authFetch,
        `/pricing/books/${selectedBookId}/publications`
      ),
    retry: false,
  });

  const entriesQuery = useQuery({
    queryKey: ["pricing", "entries", selectedPublicationId],
    enabled: selectedPublicationId !== null,
    queryFn: () =>
      fetchAll<PriceEntry>(
        authFetch,
        `/pricing/publications/${selectedPublicationId}/entries`
      ),
    retry: false,
  });

  const books = booksQuery.data ?? [];
  const publications = publicationsQuery.data ?? [];
  const entries = entriesQuery.data ?? [];
  const assignments = assignmentsQuery.data ?? [];
  const variants = variantsQuery.data ?? [];
  const uoms = uomsQuery.data ?? [];

  const selectedBook =
    books.find((item) => item.id === selectedBookId) ?? null;
  const selectedPublication =
    publications.find((item) => item.id === selectedPublicationId) ?? null;

  const variantMap = useMemo(
    () => new Map(variants.map((item) => [item.id, item])),
    [variants]
  );
  const uomMap = useMemo(
    () => new Map(uoms.map((item) => [item.id, item])),
    [uoms]
  );

  useEffect(() => {
    if (!bookForm.currency_code && tenantIdentity.data?.currency_code) {
      setBookForm((current) => ({
        ...current,
        currency_code: tenantIdentity.data?.currency_code ?? "",
      }));
    }
  }, [bookForm.currency_code, tenantIdentity.data?.currency_code]);

  useEffect(() => {
    if (books.length === 0) {
      setSelectedBookId(null);
      return;
    }
    if (!selectedBookId || !books.some((item) => item.id === selectedBookId)) {
      setSelectedBookId(books[0].id);
    }
  }, [books, selectedBookId]);

  useEffect(() => {
    if (publications.length === 0) {
      setSelectedPublicationId(null);
      return;
    }
    if (
      !selectedPublicationId ||
      !publications.some((item) => item.id === selectedPublicationId)
    ) {
      setSelectedPublicationId(publications[publications.length - 1].id);
    }
  }, [publications, selectedPublicationId]);

  useEffect(() => {
    if (!selectedPublication?.effective_at) return;
    const date = new Date(selectedPublication.effective_at);
    if (Number.isNaN(date.getTime())) return;
    setEntryForm((current) => ({
      ...current,
      effective_from: toLocalInput(date),
    }));
  }, [selectedPublication?.id, selectedPublication?.effective_at]);

  useEffect(() => {
    if (!selectedBookId) return;
    setAssignmentForm((current) => ({
      ...current,
      price_book_id: String(selectedBookId),
    }));
  }, [selectedBookId]);

  const invalidateBookContext = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["pricing", "books"] }),
      queryClient.invalidateQueries({ queryKey: ["pricing", "publications"] }),
      queryClient.invalidateQueries({ queryKey: ["pricing", "entries"] }),
      queryClient.invalidateQueries({ queryKey: ["pricing", "assignments"] }),
    ]);
  };

  const createBook = useMutation({
    mutationFn: async () => {
      if (!bookForm.code.trim() || !bookForm.name.trim()) {
        throw new Error("كود واسم دفتر الأسعار مطلوبان.");
      }
      const currency = bookForm.currency_code.trim().toUpperCase();
      if (currency.length < 3) throw new Error("رمز العملة غير صالح.");
      return authFetch("/pricing/books", {
        method: "POST",
        body: JSON.stringify({
          request_id: requestId(),
          code: bookForm.code.trim().toUpperCase(),
          name: bookForm.name.trim(),
          currency_code: currency,
          applicability_metadata: {},
        }),
      });
    },
    onSuccess: async () => {
      toast.success("تم إنشاء دفتر الأسعار.");
      setBookForm((current) => ({ ...current, code: "", name: "" }));
      await invalidateBookContext();
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "تعذر إنشاء الدفتر."),
  });

  const createPublication = useMutation({
    mutationFn: async () => {
      if (!selectedBook) throw new Error("اختر دفتر أسعار أولاً.");
      return authFetch(`/pricing/books/${selectedBook.id}/publications`, {
        method: "POST",
        body: JSON.stringify({
          request_id: requestId(),
          expected_book_version: selectedBook.version,
          effective_at: toIso(publicationEffectiveAt),
        }),
      });
    },
    onSuccess: async () => {
      toast.success("تم إنشاء نسخة نشر جديدة.");
      await invalidateBookContext();
    },
    onError: (error) =>
      toast.error(
        error instanceof Error ? error.message : "تعذر إنشاء نسخة النشر."
      ),
  });

  const saveEntry = useMutation({
    mutationFn: async () => {
      if (!selectedPublication) throw new Error("اختر نسخة نشر أولاً.");
      if (selectedPublication.status !== "DRAFT") {
        throw new Error("يمكن تعديل إدخالات نسخة DRAFT فقط.");
      }
      const productVariantId = numericId(
        entryForm.product_variant_id,
        "الصنف"
      );
      const uomId = numericId(entryForm.uom_id, "وحدة القياس");
      const priority = Number(entryForm.priority || "0");
      if (!Number.isSafeInteger(priority) || priority < 0) {
        throw new Error("الأولوية يجب أن تكون عدداً صحيحاً غير سالب.");
      }
      if (!entryForm.amount.trim()) throw new Error("السعر مطلوب.");

      const common = {
        request_id: requestId(),
        expected_publication_version: selectedPublication.version,
        amount: entryForm.amount.trim(),
        effective_from: toIso(entryForm.effective_from),
        effective_to: entryForm.effective_to
          ? toIso(entryForm.effective_to)
          : null,
        priority,
        metadata: {},
      };

      if (editingEntryId !== null) {
        const current = entries.find((item) => item.id === editingEntryId);
        if (!current) throw new Error("إدخال السعر المراد تعديله غير موجود.");
        return authFetch(`/pricing/entries/${editingEntryId}`, {
          method: "PATCH",
          body: JSON.stringify({
            ...common,
            expected_entry_version: current.version,
          }),
        });
      }

      return authFetch(
        `/pricing/publications/${selectedPublication.id}/entries`,
        {
          method: "POST",
          body: JSON.stringify({
            ...common,
            product_variant_id: productVariantId,
            uom_id: uomId,
          }),
        }
      );
    },
    onSuccess: async () => {
      toast.success(editingEntryId ? "تم تحديث السعر." : "تمت إضافة السعر.");
      setEditingEntryId(null);
      setEntryForm((current) => ({
        ...current,
        amount: "",
        effective_to: "",
        priority: "0",
      }));
      await invalidateBookContext();
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "تعذر حفظ السعر."),
  });

  const deleteEntry = useMutation({
    mutationFn: async (entry: PriceEntry) => {
      if (!selectedPublication) throw new Error("نسخة النشر غير محددة.");
      if (selectedPublication.status !== "DRAFT") {
        throw new Error("يمكن حذف إدخالات DRAFT فقط.");
      }
      return authFetch(`/pricing/entries/${entry.id}`, {
        method: "DELETE",
        body: JSON.stringify({
          request_id: requestId(),
          expected_entry_version: entry.version,
          expected_publication_version: selectedPublication.version,
          reason: "حذف إدخال سعر من لوحة التسعير",
        }),
      });
    },
    onSuccess: async () => {
      toast.success("تم حذف إدخال السعر.");
      await invalidateBookContext();
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "تعذر حذف السعر."),
  });

  const publicationCommand = useMutation({
    mutationFn: async ({
      action,
      reason,
    }: {
      action: "submit" | "approve" | "publish" | "cancel";
      reason: string;
    }) => {
      if (!selectedPublication) throw new Error("نسخة النشر غير محددة.");
      return authFetch(
        `/pricing/publications/${selectedPublication.id}/${action}`,
        {
          method: "POST",
          body: JSON.stringify({
            request_id: requestId(),
            expected_version: selectedPublication.version,
            reason,
          }),
        }
      );
    },
    onSuccess: async () => {
      toast.success("تم تنفيذ أمر نسخة النشر.");
      await invalidateBookContext();
    },
    onError: (error) =>
      toast.error(
        error instanceof Error ? error.message : "تعذر تنفيذ أمر النشر."
      ),
  });

  const createAssignment = useMutation({
    mutationFn: async () => {
      const priceBookId = numericId(
        assignmentForm.price_book_id,
        "دفتر الأسعار"
      );
      const scopeId =
        assignmentForm.scope_type === "COMPANY_DEFAULT"
          ? null
          : numericId(assignmentForm.scope_id, "scope_id");
      const priority = Number(assignmentForm.priority || "0");
      if (!Number.isSafeInteger(priority) || priority < 0) {
        throw new Error("الأولوية يجب أن تكون عدداً صحيحاً غير سالب.");
      }
      return authFetch("/pricing/assignments", {
        method: "POST",
        body: JSON.stringify({
          request_id: requestId(),
          price_book_id: priceBookId,
          scope_type: assignmentForm.scope_type,
          scope_id: scopeId,
          priority,
          effective_from: toIso(assignmentForm.effective_from),
          effective_to: assignmentForm.effective_to
            ? toIso(assignmentForm.effective_to)
            : null,
        }),
      });
    },
    onSuccess: async () => {
      toast.success("تم إنشاء ربط دفتر الأسعار.");
      await queryClient.invalidateQueries({
        queryKey: ["pricing", "assignments"],
      });
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "تعذر إنشاء الربط."),
  });

  const resolvePreview = useMutation({
    mutationFn: async () => {
      const payload = {
        product_variant_id: numericId(
          previewForm.product_variant_id,
          "الصنف"
        ),
        uom_id: numericId(previewForm.uom_id, "وحدة القياس"),
        customer_id: previewForm.customer_id
          ? numericId(previewForm.customer_id, "customer_id")
          : null,
        branch_id: previewForm.branch_id
          ? numericId(previewForm.branch_id, "branch_id")
          : null,
        as_of: null,
        price_publication_revision: null,
        assignment_revision: null,
      };
      return (await authFetch("/pricing/resolve-preview", {
        method: "POST",
        body: JSON.stringify(payload),
      })) as ResolvePreviewResult;
    },
    onSuccess: (result) => {
      setPreview(result);
      toast.success("تم حل السعر حسب الأولوية التجارية.");
    },
    onError: (error) => {
      setPreview(null);
      toast.error(error instanceof Error ? error.message : "تعذر حل السعر.");
    },
  });

  const startEdit = (entry: PriceEntry) => {
    const from = new Date(entry.effective_from);
    const to = entry.effective_to ? new Date(entry.effective_to) : null;
    setEditingEntryId(entry.id);
    setEntryForm({
      product_variant_id: String(entry.product_variant_id),
      uom_id: String(entry.uom_id),
      amount: entry.amount,
      effective_from: Number.isNaN(from.getTime())
        ? toLocalInput()
        : toLocalInput(from),
      effective_to:
        to && !Number.isNaN(to.getTime()) ? toLocalInput(to) : "",
      priority: String(entry.priority),
    });
  };

  const resetEntryEditor = () => {
    setEditingEntryId(null);
    setEntryForm((current) => ({
      ...current,
      amount: "",
      effective_to: "",
      priority: "0",
    }));
  };

  const isBusy =
    booksQuery.isLoading ||
    assignmentsQuery.isLoading ||
    variantsQuery.isLoading ||
    uomsQuery.isLoading;

  if (isBusy) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm font-bold text-slate-500">
        جاري تحميل سلطة التسعير...
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden" dir="rtl">
      <header className="mb-4 rounded-3xl border border-white/60 bg-white/70 p-5 shadow-sm backdrop-blur-xl">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="mb-1 text-xs font-black tracking-wide text-slate-500">
              COMMERCIAL PRICING
            </p>
            <h1 className="flex items-center gap-3 text-2xl font-black text-slate-950">
              <span className="rounded-2xl bg-slate-950 p-3 text-white shadow-lg">
                <BadgeDollarSign className="h-6 w-6" />
              </span>
              التسعير التجاري
            </h1>
            <p className="mt-2 max-w-2xl text-sm font-medium text-slate-500">
              إدارة دفاتر الأسعار، نسخ النشر الزمنية، الربط التجاري ومعاينة
              السعر الفعلي بدون أي اعتماد على سعر حي داخل المنتج.
            </p>
          </div>
          <button
            className={softButton}
            onClick={() => {
              void queryClient.invalidateQueries({ queryKey: ["pricing"] });
            }}
          >
            <RefreshCw className="h-4 w-4" />
            تحديث
          </button>
        </div>
      </header>

      <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto pb-8">
        <div className="grid gap-4 xl:grid-cols-2">
          <Panel
            title="دفاتر الأسعار"
            subtitle="العملة تأتي من PriceBook ولا تُستنتج من المنتج."
            icon={BookOpen}
          >
            <div className="grid gap-3 md:grid-cols-3">
              <Field label="الدفتر الحالي">
                <select
                  className={inputClass}
                  value={selectedBookId ?? ""}
                  onChange={(event) =>
                    setSelectedBookId(
                      event.target.value ? Number(event.target.value) : null
                    )
                  }
                >
                  <option value="">اختر دفتر الأسعار</option>
                  {books.map((book) => (
                    <option key={book.id} value={book.id}>
                      {book.code} — {book.name}
                    </option>
                  ))}
                </select>
              </Field>
              <div className="rounded-2xl bg-slate-50 p-3">
                <p className="text-[11px] font-bold text-slate-400">العملة</p>
                <p className="mt-1 text-sm font-black text-slate-800">
                  {selectedBook?.currency_code ?? "—"}
                </p>
              </div>
              <div className="rounded-2xl bg-slate-50 p-3">
                <p className="text-[11px] font-bold text-slate-400">Version</p>
                <p className="mt-1 text-sm font-black text-slate-800">
                  {selectedBook?.version ?? "—"}
                </p>
              </div>
            </div>

            {canManage ? (
              <div className="mt-4 grid gap-3 rounded-2xl border border-slate-100 bg-slate-50/70 p-4 md:grid-cols-4">
                <Field label="الكود">
                  <input
                    className={inputClass}
                    value={bookForm.code}
                    maxLength={100}
                    onChange={(event) =>
                      setBookForm((current) => ({
                        ...current,
                        code: event.target.value,
                      }))
                    }
                    placeholder="RETAIL-JO"
                  />
                </Field>
                <Field label="الاسم">
                  <input
                    className={inputClass}
                    value={bookForm.name}
                    maxLength={150}
                    onChange={(event) =>
                      setBookForm((current) => ({
                        ...current,
                        name: event.target.value,
                      }))
                    }
                    placeholder="أسعار التجزئة"
                  />
                </Field>
                <Field label="العملة">
                  <input
                    className={inputClass}
                    value={bookForm.currency_code}
                    maxLength={10}
                    onChange={(event) =>
                      setBookForm((current) => ({
                        ...current,
                        currency_code: event.target.value.toUpperCase(),
                      }))
                    }
                    placeholder="JOD"
                  />
                </Field>
                <div className="flex items-end">
                  <button
                    className={`${primaryButton} w-full`}
                    disabled={createBook.isPending}
                    onClick={() => createBook.mutate()}
                  >
                    <Plus className="h-4 w-4" />
                    دفتر جديد
                  </button>
                </div>
              </div>
            ) : null}
          </Panel>

          <Panel
            title="نسخ النشر"
            subtitle="النسخة المنشورة immutable؛ التغيير يتم بنسخة لاحقة."
            icon={Layers3}
          >
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="نسخة النشر">
                <select
                  className={inputClass}
                  value={selectedPublicationId ?? ""}
                  onChange={(event) =>
                    setSelectedPublicationId(
                      event.target.value ? Number(event.target.value) : null
                    )
                  }
                  disabled={!selectedBook}
                >
                  <option value="">اختر النسخة</option>
                  {publications.map((publication) => (
                    <option key={publication.id} value={publication.id}>
                      #{publication.revision} — {statusLabel[publication.status]}
                    </option>
                  ))}
                </select>
              </Field>
              <div className="flex items-end gap-2">
                {selectedPublication ? (
                  <span
                    className={`inline-flex h-10 items-center rounded-xl px-3 text-xs font-black ${statusClass[selectedPublication.status]}`}
                  >
                    {statusLabel[selectedPublication.status]}
                  </span>
                ) : null}
                <span className="inline-flex h-10 items-center rounded-xl bg-slate-100 px-3 text-xs font-bold text-slate-500">
                  {selectedPublication
                    ? `rev ${selectedPublication.revision} / v${selectedPublication.version}`
                    : "—"}
                </span>
              </div>
            </div>

            {canManage && selectedBook ? (
              <div className="mt-4 flex flex-wrap items-end gap-2 rounded-2xl border border-slate-100 bg-slate-50/70 p-4">
                <Field label="سريان النسخة">
                  <input
                    className={inputClass}
                    type="datetime-local"
                    value={publicationEffectiveAt}
                    onChange={(event) =>
                      setPublicationEffectiveAt(event.target.value)
                    }
                  />
                </Field>
                <button
                  className={primaryButton}
                  disabled={createPublication.isPending}
                  onClick={() => createPublication.mutate()}
                >
                  <Plus className="h-4 w-4" />
                  إنشاء DRAFT
                </button>
              </div>
            ) : null}

            {selectedPublication ? (
              <div className="mt-4 flex flex-wrap gap-2">
                {canManage && selectedPublication.status === "DRAFT" ? (
                  <>
                    <button
                      className={softButton}
                      disabled={publicationCommand.isPending}
                      onClick={() =>
                        publicationCommand.mutate({
                          action: "submit",
                          reason: "إرسال نسخة الأسعار للاعتماد من لوحة التسعير",
                        })
                      }
                    >
                      <ShieldCheck className="h-4 w-4" />
                      إرسال للموافقة
                    </button>
                    <button
                      className={primaryButton}
                      disabled={publicationCommand.isPending}
                      onClick={() =>
                        publicationCommand.mutate({
                          action: "publish",
                          reason: "نشر مباشر من لوحة التسعير",
                        })
                      }
                    >
                      <Rocket className="h-4 w-4" />
                      نشر مباشر
                    </button>
                    <button
                      className={softButton}
                      disabled={publicationCommand.isPending}
                      onClick={() =>
                        publicationCommand.mutate({
                          action: "cancel",
                          reason: "إلغاء نسخة DRAFT من لوحة التسعير",
                        })
                      }
                    >
                      <XCircle className="h-4 w-4" />
                      إلغاء
                    </button>
                  </>
                ) : null}
                {canApprove &&
                selectedPublication.status === "PENDING_APPROVAL" ? (
                  <button
                    className={primaryButton}
                    disabled={publicationCommand.isPending}
                    onClick={() =>
                      publicationCommand.mutate({
                        action: "approve",
                        reason: "اعتماد نسخة الأسعار من لوحة التسعير",
                      })
                    }
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    اعتماد ونشر
                  </button>
                ) : null}
                {canManage &&
                selectedPublication.status === "PENDING_APPROVAL" ? (
                  <button
                    className={softButton}
                    disabled={publicationCommand.isPending}
                    onClick={() =>
                      publicationCommand.mutate({
                        action: "cancel",
                        reason: "إلغاء نسخة بانتظار الاعتماد من لوحة التسعير",
                      })
                    }
                  >
                    <XCircle className="h-4 w-4" />
                    إلغاء
                  </button>
                ) : null}
              </div>
            ) : null}
          </Panel>
        </div>

        <div className="mt-4">
          <Panel
            title="إدخالات الأسعار"
            subtitle="كل SKU/UOM له سعر زمني مستقل داخل نسخة النشر."
            icon={BadgeDollarSign}
          >
            {canManage && selectedPublication?.status === "DRAFT" ? (
              <div className="grid gap-3 rounded-2xl border border-slate-100 bg-slate-50/70 p-4 md:grid-cols-3 xl:grid-cols-7">
                <Field label="الصنف">
                  <select
                    className={inputClass}
                    value={entryForm.product_variant_id}
                    disabled={editingEntryId !== null}
                    onChange={(event) => {
                      const variant = variantMap.get(Number(event.target.value));
                      setEntryForm((current) => ({
                        ...current,
                        product_variant_id: event.target.value,
                        uom_id: variant ? String(variant.base_uom.id) : "",
                      }));
                    }}
                  >
                    <option value="">اختر SKU</option>
                    {variants
                      .filter((item) =>
                        ["ACTIVE", "RETIRING"].includes(item.lifecycle_status)
                      )
                      .map((variant) => (
                        <option key={variant.id} value={variant.id}>
                          {variant.sku} — {variant.name}
                        </option>
                      ))}
                  </select>
                </Field>
                <Field label="UOM">
                  <select
                    className={inputClass}
                    value={entryForm.uom_id}
                    disabled={editingEntryId !== null}
                    onChange={(event) =>
                      setEntryForm((current) => ({
                        ...current,
                        uom_id: event.target.value,
                      }))
                    }
                  >
                    <option value="">اختر الوحدة</option>
                    {uoms.map((uom) => (
                      <option key={uom.id} value={uom.id}>
                        {uom.code} — {uom.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="السعر">
                  <input
                    className={inputClass}
                    inputMode="decimal"
                    value={entryForm.amount}
                    onChange={(event) =>
                      setEntryForm((current) => ({
                        ...current,
                        amount: event.target.value,
                      }))
                    }
                    placeholder="0.000000"
                  />
                </Field>
                <Field label="يبدأ">
                  <input
                    className={inputClass}
                    type="datetime-local"
                    value={entryForm.effective_from}
                    onChange={(event) =>
                      setEntryForm((current) => ({
                        ...current,
                        effective_from: event.target.value,
                      }))
                    }
                  />
                </Field>
                <Field label="ينتهي (اختياري)">
                  <input
                    className={inputClass}
                    type="datetime-local"
                    value={entryForm.effective_to}
                    onChange={(event) =>
                      setEntryForm((current) => ({
                        ...current,
                        effective_to: event.target.value,
                      }))
                    }
                  />
                </Field>
                <Field label="الأولوية">
                  <input
                    className={inputClass}
                    inputMode="numeric"
                    value={entryForm.priority}
                    onChange={(event) =>
                      setEntryForm((current) => ({
                        ...current,
                        priority: event.target.value,
                      }))
                    }
                  />
                </Field>
                <div className="flex items-end gap-2">
                  <button
                    className={`${primaryButton} flex-1`}
                    disabled={saveEntry.isPending}
                    onClick={() => saveEntry.mutate()}
                  >
                    {editingEntryId ? (
                      <Pencil className="h-4 w-4" />
                    ) : (
                      <Plus className="h-4 w-4" />
                    )}
                    {editingEntryId ? "حفظ" : "إضافة"}
                  </button>
                  {editingEntryId ? (
                    <button
                      className={softButton}
                      onClick={resetEntryEditor}
                    >
                      إلغاء
                    </button>
                  ) : null}
                </div>
              </div>
            ) : null}

            <div className="mt-4 overflow-x-auto rounded-2xl border border-slate-100">
              <table className="w-full min-w-[900px] text-right text-sm">
                <thead className="bg-slate-50 text-xs font-black text-slate-500">
                  <tr>
                    <th className="px-4 py-3">SKU</th>
                    <th className="px-4 py-3">UOM</th>
                    <th className="px-4 py-3">السعر</th>
                    <th className="px-4 py-3">السريان</th>
                    <th className="px-4 py-3">الأولوية</th>
                    <th className="px-4 py-3">الحالة</th>
                    <th className="px-4 py-3">إجراء</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((entry) => {
                    const variant = variantMap.get(entry.product_variant_id);
                    const uom = uomMap.get(entry.uom_id);
                    return (
                      <tr
                        key={entry.id}
                        className="border-t border-slate-100 bg-white/80"
                      >
                        <td className="px-4 py-3 font-bold text-slate-800">
                          {variant
                            ? `${variant.sku} — ${variant.name}`
                            : `#${entry.product_variant_id}`}
                        </td>
                        <td className="px-4 py-3">
                          {uom ? `${uom.code} — ${uom.name}` : `#${entry.uom_id}`}
                        </td>
                        <td className="px-4 py-3 font-black tabular-nums">
                          {entry.amount} {selectedBook?.currency_code ?? ""}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500">
                          {formatDate(entry.effective_from)}
                          <br />
                          إلى {formatDate(entry.effective_to)}
                        </td>
                        <td className="px-4 py-3">{entry.priority}</td>
                        <td className="px-4 py-3">
                          {entry.is_published ? "منشور" : "DRAFT"}
                        </td>
                        <td className="px-4 py-3">
                          {!entry.is_published &&
                          selectedPublication?.status === "DRAFT" &&
                          canManage ? (
                            <div className="flex gap-2">
                              <button
                                className={softButton}
                                onClick={() => startEdit(entry)}
                              >
                                <Pencil className="h-3.5 w-3.5" />
                                تعديل
                              </button>
                              <button
                                className={`${softButton} text-rose-700`}
                                disabled={deleteEntry.isPending}
                                onClick={() => deleteEntry.mutate(entry)}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                                حذف
                              </button>
                            </div>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  {entries.length === 0 ? (
                    <tr>
                      <td
                        colSpan={7}
                        className="px-4 py-10 text-center text-sm font-bold text-slate-400"
                      >
                        لا توجد إدخالات في النسخة المحددة.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>

        <div className="mt-4 grid gap-4 xl:grid-cols-2">
          <Panel
            title="ربط دفتر الأسعار"
            subtitle="CUSTOMER أعلى من BRANCH ثم COMPANY_DEFAULT؛ التعادل غير المحسوم مرفوض."
            icon={Link2}
          >
            {canManage ? (
              <div className="grid gap-3 md:grid-cols-2">
                <Field label="دفتر الأسعار">
                  <select
                    className={inputClass}
                    value={assignmentForm.price_book_id}
                    onChange={(event) =>
                      setAssignmentForm((current) => ({
                        ...current,
                        price_book_id: event.target.value,
                      }))
                    }
                  >
                    <option value="">اختر الدفتر</option>
                    {books.map((book) => (
                      <option key={book.id} value={book.id}>
                        {book.code} — {book.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="النطاق">
                  <select
                    className={inputClass}
                    value={assignmentForm.scope_type}
                    onChange={(event) =>
                      setAssignmentForm((current) => ({
                        ...current,
                        scope_type: event.target.value as
                          | "CUSTOMER"
                          | "BRANCH"
                          | "COMPANY_DEFAULT",
                        scope_id:
                          event.target.value === "COMPANY_DEFAULT"
                            ? ""
                            : current.scope_id,
                      }))
                    }
                  >
                    <option value="COMPANY_DEFAULT">Company Default</option>
                    <option value="BRANCH">Branch</option>
                    <option value="CUSTOMER">Customer</option>
                  </select>
                </Field>
                {assignmentForm.scope_type !== "COMPANY_DEFAULT" ? (
                  <Field label="Scope ID">
                    <input
                      className={inputClass}
                      inputMode="numeric"
                      value={assignmentForm.scope_id}
                      onChange={(event) =>
                        setAssignmentForm((current) => ({
                          ...current,
                          scope_id: event.target.value,
                        }))
                      }
                    />
                  </Field>
                ) : null}
                <Field label="الأولوية داخل النطاق">
                  <input
                    className={inputClass}
                    inputMode="numeric"
                    value={assignmentForm.priority}
                    onChange={(event) =>
                      setAssignmentForm((current) => ({
                        ...current,
                        priority: event.target.value,
                      }))
                    }
                  />
                </Field>
                <Field label="يبدأ">
                  <input
                    className={inputClass}
                    type="datetime-local"
                    value={assignmentForm.effective_from}
                    onChange={(event) =>
                      setAssignmentForm((current) => ({
                        ...current,
                        effective_from: event.target.value,
                      }))
                    }
                  />
                </Field>
                <Field label="ينتهي (اختياري)">
                  <input
                    className={inputClass}
                    type="datetime-local"
                    value={assignmentForm.effective_to}
                    onChange={(event) =>
                      setAssignmentForm((current) => ({
                        ...current,
                        effective_to: event.target.value,
                      }))
                    }
                  />
                </Field>
                <div className="flex items-end md:col-span-2">
                  <button
                    className={`${primaryButton} w-full`}
                    disabled={createAssignment.isPending}
                    onClick={() => createAssignment.mutate()}
                  >
                    <Plus className="h-4 w-4" />
                    إنشاء Assignment
                  </button>
                </div>
              </div>
            ) : null}

            <div className="mt-4 space-y-2">
              {assignments
                .slice()
                .reverse()
                .slice(0, 8)
                .map((assignment) => {
                  const book = books.find(
                    (item) => item.id === assignment.price_book_id
                  );
                  return (
                    <div
                      key={assignment.id}
                      className="flex items-center justify-between gap-3 rounded-2xl border border-slate-100 bg-white p-3"
                    >
                      <div>
                        <p className="text-sm font-black text-slate-800">
                          {book?.code ?? `Book #${assignment.price_book_id}`}
                        </p>
                        <p className="mt-0.5 text-xs font-medium text-slate-500">
                          {assignment.scope_type}
                          {assignment.scope_id
                            ? ` #${assignment.scope_id}`
                            : ""}{" "}
                          · rev {assignment.revision}
                        </p>
                      </div>
                      <span className="rounded-xl bg-slate-100 px-2.5 py-1 text-xs font-black text-slate-600">
                        P{assignment.priority}
                      </span>
                    </div>
                  );
                })}
            </div>
          </Panel>

          <Panel
            title="معاينة حل السعر"
            subtitle="تشغّل نفس resolver الحتمي قبل الاعتماد على السعر في التشغيل."
            icon={Search}
          >
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="الصنف">
                <select
                  className={inputClass}
                  value={previewForm.product_variant_id}
                  onChange={(event) => {
                    const variant = variantMap.get(Number(event.target.value));
                    setPreviewForm((current) => ({
                      ...current,
                      product_variant_id: event.target.value,
                      uom_id: variant ? String(variant.base_uom.id) : "",
                    }));
                  }}
                >
                  <option value="">اختر SKU</option>
                  {variants.map((variant) => (
                    <option key={variant.id} value={variant.id}>
                      {variant.sku} — {variant.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="UOM">
                <select
                  className={inputClass}
                  value={previewForm.uom_id}
                  onChange={(event) =>
                    setPreviewForm((current) => ({
                      ...current,
                      uom_id: event.target.value,
                    }))
                  }
                >
                  <option value="">اختر الوحدة</option>
                  {uoms.map((uom) => (
                    <option key={uom.id} value={uom.id}>
                      {uom.code} — {uom.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Customer ID (اختياري)">
                <input
                  className={inputClass}
                  inputMode="numeric"
                  value={previewForm.customer_id}
                  onChange={(event) =>
                    setPreviewForm((current) => ({
                      ...current,
                      customer_id: event.target.value,
                    }))
                  }
                />
              </Field>
              <Field label="Branch ID (اختياري)">
                <input
                  className={inputClass}
                  inputMode="numeric"
                  value={previewForm.branch_id}
                  onChange={(event) =>
                    setPreviewForm((current) => ({
                      ...current,
                      branch_id: event.target.value,
                    }))
                  }
                />
              </Field>
              <div className="md:col-span-2">
                <button
                  className={`${primaryButton} w-full`}
                  disabled={resolvePreview.isPending}
                  onClick={() => resolvePreview.mutate()}
                >
                  <Search className="h-4 w-4" />
                  حل السعر الآن
                </button>
              </div>
            </div>

            {preview ? (
              <div className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
                <div className="flex items-center gap-2 text-emerald-800">
                  <CheckCircle2 className="h-5 w-5" />
                  <strong className="text-sm">PRICE_RESOLVED</strong>
                </div>
                <p className="mt-3 text-2xl font-black tabular-nums text-slate-950">
                  {preview.price.amount} {preview.price.currency_code}
                </p>
                <p className="mt-2 text-xs font-bold text-slate-600">
                  {preview.assignment.scope_type} · Assignment #
                  {preview.assignment.id} rev {preview.assignment.revision} ·
                  Publication rev {preview.price.publication_revision}
                </p>
              </div>
            ) : null}
          </Panel>
        </div>
      </div>
    </div>
  );
}
