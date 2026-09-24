import { currentLocale } from "@/i18n";
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

type PricingPolicy = {
  maker_checker_enabled: boolean;
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
  allow_offers: boolean;
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
    allow_offers: boolean;
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
    : new Intl.DateTimeFormat(currentLocale(), {
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
      throw new Error("تعذر قراءة بيانات التسعير.");
    }
    rows.push(...response.items);

    if (!response.has_more) return rows;
    if (!response.next_cursor) {
      throw new Error("الخادم أعلن عن صفحة تالية دون مؤشر متابعة.");
    }
    cursor = response.next_cursor;
  }

  throw new Error(
    "عدد سجلات التسعير أكبر من حد شاشة الإدارة الحالية؛ استخدم البحث أو التقسيم قبل المتابعة."
  );
}

const statusLabel: Record<PricePublication["status"], string> = {
  DRAFT: "مسودة",
  PENDING_APPROVAL: "بانتظار المراجعة",
  PUBLISHED: "معتمد",
  SUPERSEDED: "إصدار سابق",
  CANCELLED: "ملغى",
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
  const [activeWorkspace, setActiveWorkspace] = useState<
    "lists" | "edition" | "assignments" | "preview"
  >("edition");

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
    allow_offers: true,
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

  const policyQuery = useQuery({
    queryKey: ["pricing", "policy"],
    queryFn: async () => {
      const response = (await authFetch("/pricing/policy")) as PricingPolicy;
      if (!response || typeof response.maker_checker_enabled !== "boolean") {
        throw new Error("تعذر تحميل سياسة اعتماد الأسعار.");
      }
      return response;
    },
    retry: false,
  });

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
        throw new Error("تعذر تحميل وحدات القياس.");
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

  const books = useMemo(
  () => booksQuery.data ?? [],
  [booksQuery.data]
);
  const publications = useMemo(
    () => publicationsQuery.data ?? [],
    [publicationsQuery.data]
  );
  const variants = useMemo(
    () => variantsQuery.data ?? [],
    [variantsQuery.data]
  );
  const uoms = useMemo(
    () => uomsQuery.data ?? [],
    [uomsQuery.data]
  );
  const entries = useMemo(
    () => entriesQuery.data ?? [],
    [entriesQuery.data]
  );
  const assignments = useMemo(
    () => assignmentsQuery.data ?? [],
    [assignmentsQuery.data]
  );
  const makerCheckerEnabled = policyQuery.data?.maker_checker_enabled;

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
        throw new Error("رمز واسم قائمة الأسعار مطلوبان.");
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
      toast.success("تم إنشاء قائمة الأسعار.");
      setBookForm((current) => ({ ...current, code: "", name: "" }));
      await invalidateBookContext();
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "تعذر إنشاء قائمة الأسعار."),
  });

  const createPublication = useMutation({
    mutationFn: async () => {
      if (!selectedBook) throw new Error("اختر قائمة أسعار أولًا.");
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
      toast.success("تم إنشاء إصدار أسعار جديد.");
      await invalidateBookContext();
    },
    onError: (error) =>
      toast.error(
        error instanceof Error ? error.message : "تعذر إنشاء إصدار الأسعار."
      ),
  });

  const saveEntry = useMutation({
    mutationFn: async () => {
      if (!selectedPublication) throw new Error("اختر إصدار أسعار أولًا.");
      if (selectedPublication.status !== "DRAFT") {
        throw new Error("يمكن تعديل الأسعار في الإصدار المسودة فقط.");
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
      if (!selectedPublication) throw new Error("إصدار الأسعار غير محدد.");
      if (selectedPublication.status !== "DRAFT") {
        throw new Error("يمكن حذف الأسعار من الإصدار المسودة فقط.");
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
      if (!selectedPublication) throw new Error("إصدار الأسعار غير محدد.");
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
      toast.success("تم تحديث حالة إصدار الأسعار.");
      await invalidateBookContext();
    },
    onError: (error) =>
      toast.error(
        error instanceof Error ? error.message : "تعذر تحديث حالة إصدار الأسعار."
      ),
  });

  const createAssignment = useMutation({
    mutationFn: async () => {
      const priceBookId = numericId(
        assignmentForm.price_book_id,
        "قائمة الأسعار"
      );
      const scopeId =
        assignmentForm.scope_type === "COMPANY_DEFAULT"
          ? null
          : numericId(assignmentForm.scope_id, "رقم الجهة");
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
          allow_offers: assignmentForm.allow_offers,
          priority,
          effective_from: toIso(assignmentForm.effective_from),
          effective_to: assignmentForm.effective_to
            ? toIso(assignmentForm.effective_to)
            : null,
        }),
      });
    },
    onSuccess: async () => {
      toast.success("تم تخصيص قائمة الأسعار.");
      await queryClient.invalidateQueries({
        queryKey: ["pricing", "assignments"],
      });
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "تعذر تخصيص قائمة الأسعار."),
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
          ? numericId(previewForm.customer_id, "رقم العميل")
          : null,
        branch_id: previewForm.branch_id
          ? numericId(previewForm.branch_id, "رقم الفرع")
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
      toast.success("تم تحديد السعر الأساسي.");
    },
    onError: (error) => {
      setPreview(null);
      toast.error(error instanceof Error ? error.message : "تعذر فحص السعر الأساسي.");
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
    policyQuery.isLoading ||
    booksQuery.isLoading ||
    assignmentsQuery.isLoading ||
    variantsQuery.isLoading ||
    uomsQuery.isLoading;

  const isAdvancedWorkspace =
    activeWorkspace === "lists" || activeWorkspace === "assignments";

  const scopeLabel = (
    scope: PriceAssignment["scope_type"] | string
  ): string => {
    if (scope === "CUSTOMER") return "عميل محدد";
    if (scope === "BRANCH") return "فرع محدد";
    return "كل الشركة";
  };

  if (isBusy) {
    return (
      <div className="flex flex-1 items-center justify-center" dir="rtl">
        <div className="rounded-[28px] border border-white/70 bg-white/85 px-9 py-8 text-center shadow-sm backdrop-blur-xl">
          <span className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-[20px] bg-slate-950 text-white shadow-lg shadow-slate-200">
            <BadgeDollarSign className="h-6 w-6 animate-pulse" />
          </span>
          <p className="text-sm font-black text-slate-900">
            جاري تجهيز مركز التسعير...
          </p>
          <p className="mt-1 text-xs text-slate-400">
            يتم تحميل قوائم الأسعار والإصدارات الحالية.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden" dir="rtl">
      <header className="shrink-0 rounded-[24px] border border-white/70 bg-white/85 px-4 py-3 shadow-sm backdrop-blur-xl">
        <div className="flex flex-wrap items-center gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[15px] bg-slate-950 text-white shadow-sm">
            <BadgeDollarSign className="h-4 w-4" />
          </span>

          <div className="min-w-[180px]">
            <h1 className="text-lg font-black tracking-tight text-slate-950">
              التسعير التجاري
            </h1>
            <p className="text-[10px] font-semibold text-slate-400">
              السعر الأساسي للمنتجات — العروض والخصومات تُدار بشكل مستقل.
            </p>
          </div>

          <nav className="flex min-w-0 flex-1 justify-center">
            <div className="flex max-w-full gap-1 overflow-x-auto rounded-[18px] bg-[#0b1f35] p-1.5 shadow-sm">
              <button
                type="button"
                onClick={() => setActiveWorkspace("edition")}
                className={`flex min-w-[150px] items-center justify-center gap-2 rounded-[13px] px-3 py-2 text-[11px] font-black transition ${
                  activeWorkspace === "edition"
                    ? "bg-amber-400 text-slate-950 shadow-sm"
                    : "text-slate-300 hover:bg-white/10 hover:text-white"
                }`}
              >
                <BadgeDollarSign className="h-3.5 w-3.5" />
                أسعار المنتجات
              </button>

              <button
                type="button"
                onClick={() => setActiveWorkspace("lists")}
                className={`flex min-w-[150px] items-center justify-center gap-2 rounded-[13px] px-3 py-2 text-[11px] font-black transition ${
                  isAdvancedWorkspace
                    ? "bg-amber-400 text-slate-950 shadow-sm"
                    : "text-slate-300 hover:bg-white/10 hover:text-white"
                }`}
              >
                <Layers3 className="h-3.5 w-3.5" />
                التسعير المتقدم
              </button>

              <button
                type="button"
                onClick={() => setActiveWorkspace("preview")}
                className={`flex min-w-[130px] items-center justify-center gap-2 rounded-[13px] px-3 py-2 text-[11px] font-black transition ${
                  activeWorkspace === "preview"
                    ? "bg-amber-400 text-slate-950 shadow-sm"
                    : "text-slate-300 hover:bg-white/10 hover:text-white"
                }`}
              >
                <Search className="h-3.5 w-3.5" />
                فحص السعر
              </button>
            </div>
          </nav>

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

      <div className="mt-3 flex min-h-0 flex-1 flex-col overflow-hidden">
        {isAdvancedWorkspace ? (
          <div className="mb-3 flex shrink-0 flex-wrap items-center justify-between gap-3 rounded-[22px] border border-white/70 bg-white/75 px-3 py-2 shadow-sm backdrop-blur-xl">
            <div className="flex items-center gap-1 rounded-[15px] bg-slate-100 p-1">
              <button
                type="button"
                onClick={() => setActiveWorkspace("lists")}
                className={`rounded-[11px] px-3 py-2 text-[11px] font-black transition ${
                  activeWorkspace === "lists"
                    ? "bg-white text-slate-950 shadow-sm"
                    : "text-slate-500 hover:text-slate-800"
                }`}
              >
                قوائم وسياسات السعر
              </button>
              <button
                type="button"
                onClick={() => setActiveWorkspace("assignments")}
                className={`rounded-[11px] px-3 py-2 text-[11px] font-black transition ${
                  activeWorkspace === "assignments"
                    ? "bg-white text-slate-950 shadow-sm"
                    : "text-slate-500 hover:text-slate-800"
                }`}
              >
                أسعار خاصة للجهات
              </button>
            </div>

            <p className="text-[10px] font-semibold text-slate-500">
              استخدم التسعير المتقدم لتغيير <strong className="text-slate-800">السعر الأساسي</strong> لسياسة أو جهة؛
              الخصومات والمكافآت مكانها صفحة العروض.
            </p>
          </div>
        ) : null}

        {activeWorkspace === "lists" ? (
          <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto pb-6">
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
              <section className="rounded-[30px] border border-white/70 bg-white/80 p-5 shadow-sm backdrop-blur-xl">
                <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
                  <div>
                    <p className="text-[11px] font-black text-amber-600">
                      إعداد متقدم
                    </p>
                    <h2 className="mt-1 text-xl font-black text-slate-950">
                      قوائم وسياسات السعر الأساسي
                    </h2>
                    <p className="mt-1 max-w-2xl text-xs leading-6 text-slate-500">
                      أنشئ أكثر من قائمة فقط عندما تحتاج سياسة سعر أساسي مختلفة
                      فعليًا، مثل سوق أو عملة أو فئة تعاقدية مختلفة. لا تستخدم
                      القوائم لإنشاء خصم أو عرض ترويجي.
                    </p>
                  </div>

                  <span className="rounded-full bg-slate-100 px-3 py-1.5 text-[11px] font-black text-slate-500">
                    {books.length} قائمة
                  </span>
                </div>

                {books.length ? (
                  <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
                    {books.map((book) => {
                      const selected = selectedBookId === book.id;

                      return (
                        <button
                          key={book.id}
                          type="button"
                          onClick={() => setSelectedBookId(book.id)}
                          className={`group rounded-[26px] border p-4 text-right transition-all duration-200 ${
                            selected
                              ? "border-slate-950 bg-slate-950 text-white shadow-lg shadow-slate-200"
                              : "border-slate-200 bg-white hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md"
                          }`}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <span
                              className={`flex h-10 w-10 items-center justify-center rounded-2xl ${
                                selected
                                  ? "bg-white/10 text-white"
                                  : "bg-slate-100 text-slate-600"
                              }`}
                            >
                              <BookOpen className="h-4 w-4" />
                            </span>

                            {selected ? (
                              <span className="rounded-full bg-amber-400 px-2.5 py-1 text-[10px] font-black text-slate-950">
                                القائمة الحالية
                              </span>
                            ) : null}
                          </div>

                          <h3 className="mt-4 truncate text-base font-black">
                            {book.name}
                          </h3>
                          <p
                            className={`mt-1 text-xs ${
                              selected ? "text-slate-300" : "text-slate-500"
                            }`}
                          >
                            الرمز: {book.code}
                          </p>

                          <div
                            className={`mt-4 flex items-center justify-between border-t pt-3 text-xs ${
                              selected
                                ? "border-white/10 text-slate-300"
                                : "border-slate-100 text-slate-500"
                            }`}
                          >
                            <span>العملة</span>
                            <strong
                              className={
                                selected ? "text-white" : "text-slate-900"
                              }
                            >
                              {book.currency_code}
                            </strong>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <div className="flex min-h-64 flex-col items-center justify-center rounded-[26px] border border-dashed border-slate-200 bg-slate-50/60 p-8 text-center">
                    <BookOpen className="mb-3 h-8 w-8 text-slate-300" />
                    <strong className="text-sm text-slate-700">
                      لا توجد قوائم أسعار حتى الآن
                    </strong>
                    <p className="mt-1 max-w-sm text-xs leading-5 text-slate-500">
                      أنشئ أول قائمة أسعار من النموذج المجاور.
                    </p>
                  </div>
                )}

                {selectedBook ? (
                  <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3">
                    <div>
                      <p className="text-[10px] font-black text-slate-400">
                        اخترت
                      </p>
                      <p className="mt-0.5 text-sm font-black text-slate-900">
                        {selectedBook.name}
                      </p>
                    </div>

                    <button
                      type="button"
                      className={primaryButton}
                      onClick={() => setActiveWorkspace("edition")}
                    >
                      فتح أسعار هذه القائمة
                    </button>
                  </div>
                ) : null}
              </section>

              <aside className="rounded-[30px] border border-white/70 bg-white/80 p-5 shadow-sm backdrop-blur-xl">
                <span className="flex h-11 w-11 items-center justify-center rounded-[17px] bg-amber-400 text-slate-950 shadow-sm">
                  <Plus className="h-5 w-5" />
                </span>
                <h2 className="mt-4 text-lg font-black text-slate-950">
                  قائمة أسعار جديدة
                </h2>
                <p className="mt-1 text-xs leading-6 text-slate-500">
                  أدخل اسمًا واضحًا للقائمة ورمزًا مختصرًا وحدد عملتها.
                </p>

                {canManage ? (
                  <div className="mt-5 space-y-3">
                    <Field label="رمز القائمة">
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
                        placeholder="مثال: RETAIL-JO"
                      />
                    </Field>

                    <Field label="اسم القائمة">
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
                        placeholder="مثال: أسعار التجزئة"
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

                    <button
                      className={`${primaryButton} mt-2 w-full`}
                      disabled={createBook.isPending}
                      onClick={() => createBook.mutate()}
                    >
                      <Plus className="h-4 w-4" />
                      إنشاء قائمة الأسعار
                    </button>
                  </div>
                ) : (
                  <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-xs font-bold text-slate-500">
                    لديك صلاحية مشاهدة التسعير فقط.
                  </div>
                )}
              </aside>
            </div>
          </div>
        ) : null}

        {activeWorkspace === "edition" ? (
          <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[330px_minmax(0,1fr)]">
            <aside className="flex min-h-0 flex-col overflow-hidden rounded-[30px] border border-white/70 bg-white/80 shadow-sm backdrop-blur-xl">
              <div className="shrink-0 border-b border-slate-100 p-4">
                <p className="text-[10px] font-black text-amber-600">
                  مصدر السعر الأساسي
                </p>
                <div className="mt-1 flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="truncate text-base font-black text-slate-950">
                      {selectedBook?.name ?? "اختر قائمة أسعار"}
                    </h2>
                    <p className="mt-1 text-[11px] text-slate-500">
                      {selectedBook
                        ? `${selectedBook.code} · ${selectedBook.currency_code}`
                        : "اختر أو أنشئ قائمة من التسعير المتقدم"}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="shrink-0 rounded-xl border border-slate-200 bg-white px-2.5 py-1.5 text-[10px] font-black text-slate-600"
                    onClick={() => setActiveWorkspace("lists")}
                  >
                    اختيار القائمة
                  </button>
                </div>
              </div>

              <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-black text-slate-900">
                      سجل تغييرات الأسعار
                    </h3>
                    <p className="mt-0.5 text-[10px] text-slate-400">
                      اختر سجلًا لمراجعة أسعاره أو تعديل المسودة
                    </p>
                  </div>
                  <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-black text-slate-500">
                    {publications.length}
                  </span>
                </div>

                {publications.length ? (
                  <div className="space-y-2">
                    {publications
                      .slice()
                      .reverse()
                      .map((publication) => {
                        const selected =
                          selectedPublicationId === publication.id;

                        return (
                          <button
                            key={publication.id}
                            type="button"
                            onClick={() =>
                              setSelectedPublicationId(publication.id)
                            }
                            className={`w-full rounded-[20px] border p-3 text-right transition ${
                              selected
                                ? "border-slate-950 bg-slate-950 text-white"
                                : "border-slate-200 bg-white hover:border-slate-300"
                            }`}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <strong className="text-sm">
                                تحديث الأسعار {publication.revision}
                              </strong>
                              <span
                                className={`rounded-full px-2 py-1 text-[9px] font-black ${
                                  selected
                                    ? "bg-white/10 text-white"
                                    : statusClass[publication.status]
                                }`}
                              >
                                {statusLabel[publication.status]}
                              </span>
                            </div>
                            <p
                              className={`mt-2 text-[10px] ${
                                selected
                                  ? "text-slate-300"
                                  : "text-slate-500"
                              }`}
                            >
                              يبدأ {formatDate(publication.effective_at)}
                            </p>
                          </button>
                        );
                      })}
                  </div>
                ) : (
                  <div className="rounded-[20px] border border-dashed border-slate-200 bg-slate-50 p-5 text-center">
                    <p className="text-xs font-bold text-slate-500">
                      لا توجد إصدارات بعد
                    </p>
                  </div>
                )}

                {canManage && selectedBook ? (
                  <div className="mt-4 rounded-[22px] border border-amber-200 bg-amber-50/70 p-3">
                    <p className="text-xs font-black text-slate-900">
                      بدء تعديل أسعار جديد
                    </p>
                    <p className="mt-1 text-[10px] leading-5 text-slate-500">
                      أنشئ مجموعة تغييرات جديدة؛ بعد اعتمادها تبقى الأسعار السابقة محفوظة تاريخيًا.
                    </p>
                    <div className="mt-3">
                      <Field label="بداية تطبيق الأسعار">
                        <input
                          className={inputClass}
                          type="datetime-local"
                          value={publicationEffectiveAt}
                          onChange={(event) =>
                            setPublicationEffectiveAt(event.target.value)
                          }
                        />
                      </Field>
                    </div>
                    <button
                      className={`${primaryButton} mt-3 w-full`}
                      disabled={createPublication.isPending}
                      onClick={() => createPublication.mutate()}
                    >
                      <Plus className="h-4 w-4" />
                      بدء تعديل الأسعار
                    </button>
                  </div>
                ) : null}
              </div>
            </aside>

            <main className="flex min-h-0 flex-col overflow-hidden rounded-[30px] border border-white/70 bg-white/80 shadow-sm backdrop-blur-xl">
              <div className="shrink-0 border-b border-slate-100 bg-slate-50/70 px-5 py-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-black text-slate-950">
                      أسعار المنتجات
                    </h2>
                    <p className="mt-0.5 text-[10px] leading-5 text-slate-500">
                      هنا تحدد السعر الأساسي للصنف. الخصم، الهدية، وشروط الكمية
                      لا تُنشأ هنا؛ مكانها صفحة العروض.
                    </p>
                  </div>
                  <span className="rounded-full border border-sky-200 bg-sky-50 px-3 py-1.5 text-[10px] font-black text-sky-800">
                    التسعير = السعر الأساسي فقط
                  </span>
                </div>
              </div>

              {!selectedPublication ? (
                <div className="flex h-full items-center justify-center p-8">
                  <div className="max-w-md text-center">
                    <span className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-[24px] bg-slate-100 text-slate-400">
                      <Layers3 className="h-7 w-7" />
                    </span>
                    <h2 className="text-lg font-black text-slate-900">
                      اختر سجل أسعار
                    </h2>
                    <p className="mt-2 text-sm leading-7 text-slate-500">
                      بعد اختيار السجل ستظهر الأسعار وحالة التعديل وإجراءات الاعتماد في
                      هذه المساحة.
                    </p>
                  </div>
                </div>
              ) : (
                <>
                  <div className="shrink-0 border-b border-slate-100 p-5">
                    <div className="flex flex-wrap items-center justify-between gap-4">
                      <div>
                        <div className="flex items-center gap-2">
                          <span
                            className={`rounded-full px-3 py-1 text-[10px] font-black ${statusClass[selectedPublication.status]}`}
                          >
                            {statusLabel[selectedPublication.status]}
                          </span>
                          <span className="text-[10px] font-bold text-slate-400">
                            سجل التغيير {selectedPublication.revision}
                          </span>
                        </div>
                        <h2 className="mt-2 text-xl font-black text-slate-950">
                          أسعار {selectedBook?.name}
                        </h2>
                        <p className="mt-1 text-xs text-slate-500">
                          {selectedPublication.status === "DRAFT"
                            ? "هذه تغييرات غير معتمدة؛ يمكنك إضافة الأسعار وتعديلها قبل الاعتماد."
                            : "هذه الأسعار محفوظة للقراءة؛ أي تغيير جديد يبدأ كسجل تعديل مستقل."}
                        </p>
                      </div>

                      <div className="flex flex-wrap gap-2">
                        {canManage &&
                        selectedPublication.status === "DRAFT" ? (
                          <>
                            {makerCheckerEnabled === true ? (
                              <button
                                className={softButton}
                                disabled={publicationCommand.isPending}
                                onClick={() =>
                                  publicationCommand.mutate({
                                    action: "submit",
                                    reason:
                                      "إرسال إصدار الأسعار للمراجعة من لوحة التسعير",
                                  })
                                }
                              >
                                <ShieldCheck className="h-4 w-4" />
                                إرسال للمراجعة
                              </button>
                            ) : null}

                            {makerCheckerEnabled === false ? (
                              <button
                                className={primaryButton}
                                disabled={publicationCommand.isPending}
                                onClick={() =>
                                  publicationCommand.mutate({
                                    action: "publish",
                                    reason:
                                      "اعتماد إصدار الأسعار مباشرة من لوحة التسعير",
                                  })
                                }
                              >
                                <Rocket className="h-4 w-4" />
                                اعتماد الأسعار
                              </button>
                            ) : null}

                            <button
                              className={softButton}
                              disabled={publicationCommand.isPending}
                              onClick={() =>
                                publicationCommand.mutate({
                                  action: "cancel",
                                  reason:
                                    "إلغاء مسودة إصدار الأسعار من لوحة التسعير",
                                })
                              }
                            >
                              <XCircle className="h-4 w-4" />
                              إلغاء التغييرات
                            </button>
                          </>
                        ) : null}

                        {canApprove &&
                        makerCheckerEnabled === true &&
                        selectedPublication.status === "PENDING_APPROVAL" ? (
                          <button
                            className={primaryButton}
                            disabled={publicationCommand.isPending}
                            onClick={() =>
                              publicationCommand.mutate({
                                action: "approve",
                                reason:
                                  "اعتماد إصدار الأسعار من لوحة التسعير",
                              })
                            }
                          >
                            <CheckCircle2 className="h-4 w-4" />
                            اعتماد الأسعار
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
                                reason:
                                  "إلغاء إصدار الأسعار بانتظار المراجعة",
                              })
                            }
                          >
                            <XCircle className="h-4 w-4" />
                            إلغاء
                          </button>
                        ) : null}
                      </div>
                    </div>
                  </div>

                  {canManage &&
                  selectedPublication.status === "DRAFT" ? (
                    <div className="shrink-0 border-b border-slate-100 bg-slate-50/60 p-4">
                      <div className="mb-3 flex items-center justify-between">
                        <div>
                          <h3 className="text-sm font-black text-slate-900">
                            {editingEntryId
                              ? "تعديل السعر"
                              : "إضافة سعر للصنف"}
                          </h3>
                          <p className="mt-0.5 text-[10px] text-slate-500">
                            اختر الصنف والوحدة ثم حدد السعر ومدة تطبيقه.
                          </p>
                        </div>
                      </div>

                      <div className="grid gap-3 md:grid-cols-3 2xl:grid-cols-6">
                        <Field label="الصنف">
                          <select
                            className={inputClass}
                            value={entryForm.product_variant_id}
                            disabled={editingEntryId !== null}
                            onChange={(event) => {
                              const variant = variantMap.get(
                                Number(event.target.value)
                              );
                              setEntryForm((current) => ({
                                ...current,
                                product_variant_id: event.target.value,
                                uom_id: variant
                                  ? String(variant.base_uom.id)
                                  : "",
                              }));
                            }}
                          >
                            <option value="">اختر الصنف</option>
                            {variants
                              .filter((item) =>
                                ["ACTIVE", "RETIRING"].includes(
                                  item.lifecycle_status
                                )
                              )
                              .map((variant) => (
                                <option key={variant.id} value={variant.id}>
                                  {variant.sku} — {variant.name}
                                </option>
                              ))}
                          </select>
                        </Field>

                        <Field label="الوحدة">
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

                        <Field label="يبدأ من">
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

                        <Field label="ينتهي في (اختياري)">
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
                      </div>

                      <div className="mt-3 flex justify-end gap-2">
                        {editingEntryId ? (
                          <button
                            className={softButton}
                            onClick={resetEntryEditor}
                          >
                            إلغاء التعديل
                          </button>
                        ) : null}

                        <button
                          className={primaryButton}
                          disabled={saveEntry.isPending}
                          onClick={() => saveEntry.mutate()}
                        >
                          {editingEntryId ? (
                            <Pencil className="h-4 w-4" />
                          ) : (
                            <Plus className="h-4 w-4" />
                          )}
                          {editingEntryId
                            ? "حفظ التعديل"
                            : "إضافة السعر"}
                        </button>
                      </div>
                    </div>
                  ) : null}

                  <div className="custom-scrollbar min-h-0 flex-1 overflow-auto p-4">
                    <div className="overflow-hidden rounded-[24px] border border-slate-200 bg-white">
                      <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
                        <div>
                          <h3 className="text-sm font-black text-slate-900">
                            أسعار الأصناف
                          </h3>
                          <p className="mt-0.5 text-[10px] text-slate-500">
                            {entries.length} سعر في الإصدار المحدد
                          </p>
                        </div>
                      </div>

                      <div className="overflow-x-auto">
                        <table className="w-full min-w-[900px] text-right text-sm">
                          <thead className="bg-slate-50 text-xs font-black text-slate-500">
                            <tr>
                              <th className="px-4 py-3">الصنف</th>
                              <th className="px-4 py-3">الوحدة</th>
                              <th className="px-4 py-3">السعر</th>
                              <th className="px-4 py-3">مدة التطبيق</th>
                              <th className="px-4 py-3">الأولوية</th>
                              <th className="px-4 py-3">الحالة</th>
                              <th className="px-4 py-3">الإجراء</th>
                            </tr>
                          </thead>

                          <tbody>
                            {entries.map((entry) => {
                              const variant = variantMap.get(
                                entry.product_variant_id
                              );
                              const uom = uomMap.get(entry.uom_id);

                              return (
                                <tr
                                  key={entry.id}
                                  className="border-t border-slate-100 transition hover:bg-slate-50/70"
                                >
                                  <td className="px-4 py-3 font-bold text-slate-800">
                                    {variant
                                      ? `${variant.sku} — ${variant.name}`
                                      : `#${entry.product_variant_id}`}
                                  </td>
                                  <td className="px-4 py-3">
                                    {uom
                                      ? `${uom.code} — ${uom.name}`
                                      : `#${entry.uom_id}`}
                                  </td>
                                  <td className="px-4 py-3 font-black tabular-nums">
                                    {entry.amount}{" "}
                                    {selectedBook?.currency_code ?? ""}
                                  </td>
                                  <td className="px-4 py-3 text-xs text-slate-500">
                                    {formatDate(entry.effective_from)}
                                    <br />
                                    إلى {formatDate(entry.effective_to)}
                                  </td>
                                  <td className="px-4 py-3">
                                    {entry.priority}
                                  </td>
                                  <td className="px-4 py-3">
                                    {entry.is_published
                                      ? "معتمد"
                                      : "مسودة"}
                                  </td>
                                  <td className="px-4 py-3">
                                    {!entry.is_published &&
                                    selectedPublication.status === "DRAFT" &&
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
                                          onClick={() =>
                                            deleteEntry.mutate(entry)
                                          }
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
                                  className="px-4 py-14 text-center text-sm font-bold text-slate-400"
                                >
                                  لا توجد أسعار في هذا الإصدار حتى الآن.
                                </td>
                              </tr>
                            ) : null}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </div>
                </>
              )}
            </main>
          </div>
        ) : null}

        {activeWorkspace === "assignments" ? (
          <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto pb-6">
            <div className="grid gap-4 xl:grid-cols-[400px_minmax(0,1fr)]">
              <section className="rounded-[30px] border border-white/70 bg-white/80 p-5 shadow-sm backdrop-blur-xl">
                <p className="text-[11px] font-black text-amber-600">
                  تسعير متقدم
                </p>
                <h2 className="mt-1 text-xl font-black text-slate-950">
                  سعر أساسي خاص لجهة معينة
                </h2>
                <p className="mt-1 text-xs leading-6 text-slate-500">
                  التسعير المتقدم يحدد سعرًا أساسيًا مختلفًا لجهة معينة. أما
                  الخصومات والمكافآت وشروط الكمية فمكانها صفحة العروض.
                </p>
                <div className="mt-3 rounded-[20px] border border-sky-200 bg-sky-50/80 p-3 text-[11px] font-semibold leading-6 text-sky-900">
                  إذا اجتمع سعر متقدم مع عرض، يبدأ النظام بالسعر المتقدم ثم يطبق
                  العرض فقط إذا سمحت بذلك في خيار «العروض فوق هذا السعر» أدناه.
                </div>

                {canManage ? (
                  <div className="mt-5 space-y-3">
                    <Field label="قائمة الأسعار">
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
                        <option value="">اختر قائمة الأسعار</option>
                        {books.map((book) => (
                          <option key={book.id} value={book.id}>
                            {book.code} — {book.name}
                          </option>
                        ))}
                      </select>
                    </Field>

                    <Field label="جهة التطبيق">
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
                        <option value="COMPANY_DEFAULT">كل الشركة</option>
                        <option value="BRANCH">فرع محدد</option>
                        <option value="CUSTOMER">عميل محدد</option>
                      </select>
                    </Field>

                    {assignmentForm.scope_type !== "COMPANY_DEFAULT" ? (
                      <Field
                        label={
                          assignmentForm.scope_type === "CUSTOMER"
                            ? "رقم العميل"
                            : "رقم الفرع"
                        }
                      >
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

                    <Field label="أولوية التطبيق">
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

                    <div className="rounded-[22px] border border-slate-200 bg-white p-3">
                      <div className="mb-3">
                        <p className="text-xs font-black text-slate-900">
                          العروض فوق هذا السعر
                        </p>
                        <p className="mt-1 text-[10px] leading-5 text-slate-500">
                          هل تسمح للخصومات والعروض بتعديل السعر الأساسي الناتج من
                          هذا التخصيص؟
                        </p>
                      </div>

                      <div className="grid gap-2 sm:grid-cols-2">
                        <button
                          type="button"
                          onClick={() =>
                            setAssignmentForm((current) => ({
                              ...current,
                              allow_offers: true,
                            }))
                          }
                          className={`rounded-[18px] border p-3 text-right transition ${
                            assignmentForm.allow_offers
                              ? "border-emerald-500 bg-emerald-50 ring-2 ring-emerald-100"
                              : "border-slate-200 bg-white hover:bg-slate-50"
                          }`}
                        >
                          <strong className="block text-xs text-slate-900">
                            نعم، تسمح بالعروض
                          </strong>
                          <span className="mt-1 block text-[10px] leading-5 text-slate-500">
                            السعر هو نقطة البداية ويمكن للعروض المؤهلة تعديله.
                          </span>
                        </button>

                        <button
                          type="button"
                          onClick={() =>
                            setAssignmentForm((current) => ({
                              ...current,
                              allow_offers: false,
                            }))
                          }
                          className={`rounded-[18px] border p-3 text-right transition ${
                            !assignmentForm.allow_offers
                              ? "border-amber-500 bg-amber-50 ring-2 ring-amber-100"
                              : "border-slate-200 bg-white hover:bg-slate-50"
                          }`}
                        >
                          <strong className="block text-xs text-slate-900">
                            لا، السعر نهائي
                          </strong>
                          <span className="mt-1 block text-[10px] leading-5 text-slate-500">
                            إذا انطبق هذا التخصيص فلن تُطبق فوقه أي عروض.
                          </span>
                        </button>
                      </div>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2">
                      <Field label="يبدأ من">
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

                      <Field label="ينتهي في (اختياري)">
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
                    </div>

                    <button
                      className={`${primaryButton} mt-2 w-full`}
                      disabled={createAssignment.isPending}
                      onClick={() => createAssignment.mutate()}
                    >
                      <Plus className="h-4 w-4" />
                      حفظ التخصيص
                    </button>
                  </div>
                ) : (
                  <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-xs font-bold text-slate-500">
                    لديك صلاحية مشاهدة التخصيصات فقط.
                  </div>
                )}
              </section>

              <section className="rounded-[30px] border border-white/70 bg-white/80 p-5 shadow-sm backdrop-blur-xl">
                <div className="mb-5 flex items-end justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-black text-slate-950">
                      التخصيصات الحالية
                    </h2>
                    <p className="mt-1 text-xs text-slate-500">
                      القوائم المطبقة حاليًا والجهة التي تستفيد منها.
                    </p>
                  </div>
                  <span className="rounded-full bg-slate-100 px-3 py-1.5 text-[11px] font-black text-slate-500">
                    {assignments.length} تخصيص
                  </span>
                </div>

                {assignments.length ? (
                  <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
                    {assignments
                      .slice()
                      .reverse()
                      .map((assignment) => {
                        const book = books.find(
                          (item) => item.id === assignment.price_book_id
                        );

                        return (
                          <div
                            key={assignment.id}
                            className="rounded-[24px] border border-slate-200 bg-white p-4 transition hover:-translate-y-0.5 hover:shadow-md"
                          >
                            <div className="flex items-start justify-between gap-3">
                              <span className="flex h-9 w-9 items-center justify-center rounded-2xl bg-slate-100 text-slate-600">
                                <Link2 className="h-4 w-4" />
                              </span>
                              <div className="flex flex-col items-end gap-1.5">
                                <span className="rounded-full bg-amber-100 px-2.5 py-1 text-[10px] font-black text-amber-800">
                                  أولوية {assignment.priority}
                                </span>
                                <span
                                  className={`rounded-full px-2.5 py-1 text-[9px] font-black ${
                                    assignment.allow_offers
                                      ? "bg-emerald-100 text-emerald-700"
                                      : "bg-slate-900 text-white"
                                  }`}
                                >
                                  {assignment.allow_offers
                                    ? "يقبل العروض"
                                    : "سعر نهائي — بدون عروض"}
                                </span>
                              </div>
                            </div>

                            <h3 className="mt-4 text-sm font-black text-slate-900">
                              {book?.name ??
                                `قائمة #${assignment.price_book_id}`}
                            </h3>
                            <p className="mt-1 text-xs text-slate-500">
                              {scopeLabel(assignment.scope_type)}
                              {assignment.scope_id
                                ? ` — رقم ${assignment.scope_id}`
                                : ""}
                            </p>

                            <div className="mt-4 border-t border-slate-100 pt-3 text-[10px] leading-5 text-slate-500">
                              يبدأ: {formatDate(assignment.effective_from)}
                              <br />
                              ينتهي: {formatDate(assignment.effective_to)}
                            </div>
                          </div>
                        );
                      })}
                  </div>
                ) : (
                  <div className="flex min-h-64 flex-col items-center justify-center rounded-[26px] border border-dashed border-slate-200 bg-slate-50/60 p-8 text-center">
                    <Link2 className="mb-3 h-8 w-8 text-slate-300" />
                    <strong className="text-sm text-slate-700">
                      لا توجد تخصيصات أسعار حتى الآن
                    </strong>
                  </div>
                )}
              </section>
            </div>
          </div>
        ) : null}

        {activeWorkspace === "preview" ? (
          <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto pb-6">
            <div className="grid gap-4 xl:grid-cols-[410px_minmax(0,1fr)]">
              <section className="rounded-[30px] border border-white/70 bg-white/80 p-5 shadow-sm backdrop-blur-xl">
                <p className="text-[11px] font-black text-amber-600">
                  أداة تحقق
                </p>
                <h2 className="mt-1 text-xl font-black text-slate-950">
                  ما السعر الأساسي الذي سيختاره النظام؟
                </h2>
                <p className="mt-1 text-xs leading-6 text-slate-500">
                  اختر الصنف والوحدة، ويمكنك تحديد عميل أو فرع لمعرفة السعر
                  الأساسي ومصدره قبل تطبيق أي عروض.
                </p>

                <div className="mt-5 space-y-3">
                  <Field label="الصنف">
                    <select
                      className={inputClass}
                      value={previewForm.product_variant_id}
                      onChange={(event) => {
                        const variant = variantMap.get(
                          Number(event.target.value)
                        );
                        setPreviewForm((current) => ({
                          ...current,
                          product_variant_id: event.target.value,
                          uom_id: variant
                            ? String(variant.base_uom.id)
                            : "",
                        }));
                      }}
                    >
                      <option value="">اختر الصنف</option>
                      {variants.map((variant) => (
                        <option key={variant.id} value={variant.id}>
                          {variant.sku} — {variant.name}
                        </option>
                      ))}
                    </select>
                  </Field>

                  <Field label="الوحدة">
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

                  <Field label="رقم العميل (اختياري)">
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

                  <Field label="رقم الفرع (اختياري)">
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

                  <button
                    className={`${primaryButton} mt-2 w-full`}
                    disabled={resolvePreview.isPending}
                    onClick={() => resolvePreview.mutate()}
                  >
                    <Search className="h-4 w-4" />
                    فحص السعر الأساسي
                  </button>
                </div>
              </section>

              <section className="flex min-h-[420px] items-center justify-center overflow-hidden rounded-[30px] border border-white/70 bg-white/80 p-6 shadow-sm backdrop-blur-xl">
                {preview ? (
                  <div className="w-full max-w-2xl">
                    <div className="relative overflow-hidden rounded-[32px] bg-[#0b1f35] p-7 text-white shadow-xl">
                      <div className="pointer-events-none absolute -left-16 -top-20 h-52 w-52 rounded-full bg-amber-400/20 blur-3xl" />
                      <div className="relative">
                        <span className="flex h-12 w-12 items-center justify-center rounded-[18px] bg-amber-400 text-slate-950">
                          <CheckCircle2 className="h-5 w-5" />
                        </span>
                        <p className="mt-6 text-xs font-black text-slate-400">
                          السعر الأساسي المختار
                        </p>
                        <p className="mt-2 text-5xl font-black tabular-nums">
                          {preview.price.amount}
                          <span className="mr-2 text-xl text-amber-300">
                            {preview.price.currency_code}
                          </span>
                        </p>

                        <div className="mt-7 grid gap-3 sm:grid-cols-3">
                          <div className="rounded-[20px] border border-white/10 bg-white/5 p-4">
                            <p className="text-[10px] font-black text-slate-400">
                              قائمة الأسعار
                            </p>
                            <p className="mt-1 text-sm font-black">
                              {books.find(
                                (book) =>
                                  book.id === preview.price_book_id
                              )?.name ?? `#${preview.price_book_id}`}
                            </p>
                          </div>

                          <div className="rounded-[20px] border border-white/10 bg-white/5 p-4">
                            <p className="text-[10px] font-black text-slate-400">
                              جهة التطبيق
                            </p>
                            <p className="mt-1 text-sm font-black">
                              {scopeLabel(preview.assignment.scope_type)}
                            </p>
                          </div>

                          <div className="rounded-[20px] border border-white/10 bg-white/5 p-4">
                            <p className="text-[10px] font-black text-slate-400">
                              إصدار الأسعار
                            </p>
                            <p className="mt-1 text-sm font-black">
                              الإصدار{" "}
                              {preview.price.publication_revision}
                            </p>
                          </div>

                          <div className="rounded-[20px] border border-white/10 bg-white/5 p-4">
                            <p className="text-[10px] font-black text-slate-400">
                              العروض فوق السعر
                            </p>
                            <p className="mt-1 text-sm font-black">
                              {preview.assignment.allow_offers
                                ? "مسموحة"
                                : "غير مسموحة — السعر نهائي"}
                            </p>
                          </div>
                        </div>

                        <p className="mt-4 text-[10px] text-slate-500">
                          تمت المعاينة: {formatDate(preview.resolved_at)}
                        </p>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="max-w-md text-center">
                    <span className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-[24px] bg-slate-100 text-slate-400">
                      <Search className="h-7 w-7" />
                    </span>
                    <h3 className="text-lg font-black text-slate-900">
                      تحقق من السعر الأساسي
                    </h3>
                    <p className="mt-2 text-sm leading-7 text-slate-500">
                      أدخل بيانات الصنف من النموذج، وسيعرض النظام السعر الأساسي
                      وقائمة الأسعار التي جاء منها قبل تطبيق أي عروض.
                    </p>
                  </div>
                )}
              </section>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
