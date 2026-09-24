import { currentLocale } from "@/i18n";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Building2,
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  LogOut,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";
import { createPlatformCompany, fetchPlatformCompanies } from "@/features/platform/api";
import {
  type CreatePlatformCompanyPayload,
  type PlatformSubscription,
} from "@/features/platform/contracts";
import { clearPlatformSession, readPlatformSession } from "@/features/platform/session";
import { apiErrorStatus } from "@/lib/apiErrors";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const PAGE_SIZE = 20;

const EMPTY_COMPANY_FORM: CreatePlatformCompanyPayload = {
  name: "",
  company_code: "",
  admin_username: "",
  admin_password: "",
  admin_full_name: "",
  currency_code: "JOD",
  subscription_status: "active",
};

const subscriptionLabels: Record<PlatformSubscription, string> = {
  active: "نشط",
  suspended: "معلق",
  expired: "منتهي",
  trial: "تجريبي",
};

function formatCreatedAt(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(currentLocale(), {
    year: "numeric",
    month: "short",
    day: "2-digit",
  }).format(date);
}

export default function PlatformDashboard() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const platformSession = readPlatformSession();
  const [page, setPage] = useState(1);
  const [searchDraft, setSearchDraft] = useState("");
  const [query, setQuery] = useState("");
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [companyForm, setCompanyForm] = useState<CreatePlatformCompanyPayload>(EMPTY_COMPANY_FORM);

  const companiesQuery = useQuery({
    queryKey: ["platform", "companies", page, query],
    queryFn: () => fetchPlatformCompanies(page, PAGE_SIZE, query),
    placeholderData: (previousData) => previousData,
  });

  const createCompanyMutation = useMutation({
    mutationFn: createPlatformCompany,
    onSuccess: async (response) => {
      toast.success(response.message);
      setIsCreateOpen(false);
      setCompanyForm(EMPTY_COMPANY_FORM);
      setPage(1);
      await queryClient.invalidateQueries({ queryKey: ["platform", "companies"] });
    },
    onError: (error) => {
      if (apiErrorStatus(error) === 401) {
        clearPlatformSession();
        navigate("/platform/login", { replace: true });
      }
    },
  });

  useEffect(() => {
    if (apiErrorStatus(companiesQuery.error) === 401) {
      clearPlatformSession();
      navigate("/platform/login", { replace: true });
    }
  }, [companiesQuery.error, navigate]);

  const logout = () => {
    clearPlatformSession();
    navigate("/platform/login", { replace: true });
  };

  const submitSearch = (event: React.FormEvent) => {
    event.preventDefault();
    setPage(1);
    setQuery(searchDraft.trim());
  };

  const submitCompany = (event: React.FormEvent) => {
    event.preventDefault();
    createCompanyMutation.mutate({
      ...companyForm,
      name: companyForm.name.trim(),
      company_code: companyForm.company_code.trim(),
      admin_username: companyForm.admin_username.trim(),
      admin_full_name: companyForm.admin_full_name.trim(),
      currency_code: companyForm.currency_code.trim(),
    });
  };

  const setFormField = <K extends keyof CreatePlatformCompanyPayload>(
    key: K,
    value: CreatePlatformCompanyPayload[K],
  ) => setCompanyForm((current) => ({ ...current, [key]: value }));

  const pageData = companiesQuery.data;
  const activeOnPage = pageData?.items.filter((company) => company.is_active).length ?? 0;
  const trialOnPage = pageData?.items.filter((company) => company.subscription === "trial").length ?? 0;

  return (
    <main className="min-h-screen mesh-gradient-bg p-4 md:p-8" dir="rtl">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="glass-card flex flex-col gap-4 p-5 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="grid h-12 w-12 place-items-center rounded-2xl bg-slate-900 text-amber-400 shadow-lg">
              <ShieldCheck className="h-6 w-6" />
            </div>
            <div>
              <p className="text-xs font-extrabold tracking-wider text-amber-600">PLATFORM ADMIN</p>
              <h1 className="text-2xl font-black text-slate-900">إدارة شركات المنصة</h1>
              <p className="text-sm font-semibold text-slate-500">الحساب: {platformSession?.admin}</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => companiesQuery.refetch()} disabled={companiesQuery.isFetching}>
              <RefreshCw className={companiesQuery.isFetching ? "animate-spin" : ""} /> تحديث
            </Button>
            <Button onClick={() => setIsCreateOpen(true)}>
              <Plus /> تأسيس شركة
            </Button>
            <Button variant="ghost" onClick={logout} className="text-destructive hover:text-destructive">
              <LogOut /> خروج
            </Button>
          </div>
        </header>

        <section className="grid gap-4 md:grid-cols-3">
          <Card className="border-white/70 bg-white/80">
            <CardContent className="flex items-center justify-between p-5">
              <div><p className="text-sm font-bold text-slate-500">إجمالي الشركات</p><strong className="text-3xl font-black">{pageData?.total ?? "—"}</strong></div>
              <Building2 className="h-8 w-8 text-sky-600" />
            </CardContent>
          </Card>
          <Card className="border-white/70 bg-white/80">
            <CardContent className="flex items-center justify-between p-5">
              <div><p className="text-sm font-bold text-slate-500">النشطة في الصفحة</p><strong className="text-3xl font-black">{pageData ? activeOnPage : "—"}</strong></div>
              <CircleCheck className="h-8 w-8 text-emerald-600" />
            </CardContent>
          </Card>
          <Card className="border-white/70 bg-white/80">
            <CardContent className="flex items-center justify-between p-5">
              <div><p className="text-sm font-bold text-slate-500">التجريبية في الصفحة</p><strong className="text-3xl font-black">{pageData ? trialOnPage : "—"}</strong></div>
              <ShieldCheck className="h-8 w-8 text-amber-600" />
            </CardContent>
          </Card>
        </section>

        <Card className="border-white/70 bg-white/85 shadow-xl">
          <CardHeader className="gap-4 md:flex-row md:items-center md:justify-between">
            <CardTitle className="text-xl font-black">سجل الشركات</CardTitle>
            <form onSubmit={submitSearch} className="flex w-full gap-2 md:max-w-md">
              <Input value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder="ابحث بالاسم أو رمز الشركة" maxLength={100} />
              <Button type="submit" variant="outline" aria-label="بحث"><Search /></Button>
            </form>
          </CardHeader>
          <CardContent>
            {companiesQuery.isLoading ? (
              <div className="py-16 text-center text-sm font-bold text-slate-500">جارٍ تحميل الشركات...</div>
            ) : companiesQuery.isError ? (
              <div className="py-16 text-center">
                <p className="font-bold text-destructive">تعذر تحميل سجل الشركات.</p>
                <Button className="mt-4" variant="outline" onClick={() => companiesQuery.refetch()}>إعادة المحاولة</Button>
              </div>
            ) : pageData && pageData.items.length > 0 ? (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-right">الشركة</TableHead>
                      <TableHead className="text-right">الرمز</TableHead>
                      <TableHead className="text-right">الاشتراك</TableHead>
                      <TableHead className="text-right">الحالة</TableHead>
                      <TableHead className="text-right">تاريخ التأسيس</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pageData.items.map((company) => (
                      <TableRow key={company.id}>
                        <TableCell className="font-extrabold text-slate-900">{company.name}</TableCell>
                        <TableCell><code className="rounded bg-slate-100 px-2 py-1 text-xs font-bold">{company.code}</code></TableCell>
                        <TableCell><Badge variant="outline">{subscriptionLabels[company.subscription]}</Badge></TableCell>
                        <TableCell>
                          <Badge className={company.is_active ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700"} variant="outline">
                            {company.is_active ? "مفعلة" : "موقوفة"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-slate-500">{formatCreatedAt(company.created_at)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <div className="mt-5 flex items-center justify-between border-t pt-4">
                  <p className="text-xs font-bold text-slate-500">صفحة {pageData.page} من {pageData.pages} · {pageData.total} شركة</p>
                  <div className="flex gap-2" dir="ltr">
                    <Button size="icon" variant="outline" disabled={page <= 1 || companiesQuery.isFetching} onClick={() => setPage((current) => current - 1)} aria-label="الصفحة السابقة"><ChevronLeft /></Button>
                    <Button size="icon" variant="outline" disabled={page >= pageData.pages || companiesQuery.isFetching} onClick={() => setPage((current) => current + 1)} aria-label="الصفحة التالية"><ChevronRight /></Button>
                  </div>
                </div>
              </>
            ) : (
              <div className="py-16 text-center text-sm font-bold text-slate-500">لا توجد شركات مطابقة.</div>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog open={isCreateOpen} onOpenChange={(open) => !createCompanyMutation.isPending && setIsCreateOpen(open)}>
        <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto" dir="rtl">
          <DialogHeader className="text-right sm:text-right">
            <DialogTitle>تأسيس شركة جديدة</DialogTitle>
            <DialogDescription>ينشئ النظام الشركة وفرعها الرئيسي وحساب مدير الشركة ضمن معاملة واحدة.</DialogDescription>
          </DialogHeader>
          <form onSubmit={submitCompany} className="grid gap-5">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="grid gap-2"><Label htmlFor="platform-company-name">اسم الشركة</Label><Input id="platform-company-name" required maxLength={150} value={companyForm.name} onChange={(event) => setFormField("name", event.target.value)} disabled={createCompanyMutation.isPending} /></div>
              <div className="grid gap-2"><Label htmlFor="platform-company-code">رمز الشركة</Label><Input id="platform-company-code" required maxLength={50} value={companyForm.company_code} onChange={(event) => setFormField("company_code", event.target.value)} disabled={createCompanyMutation.isPending} dir="ltr" /></div>
              <div className="grid gap-2"><Label htmlFor="platform-admin-name">اسم مدير الشركة</Label><Input id="platform-admin-name" required maxLength={120} value={companyForm.admin_full_name} onChange={(event) => setFormField("admin_full_name", event.target.value)} disabled={createCompanyMutation.isPending} /></div>
              <div className="grid gap-2"><Label htmlFor="platform-admin-username">اسم مستخدم المدير</Label><Input id="platform-admin-username" required maxLength={80} autoComplete="off" value={companyForm.admin_username} onChange={(event) => setFormField("admin_username", event.target.value)} disabled={createCompanyMutation.isPending} dir="ltr" /></div>
              <div className="grid gap-2"><Label htmlFor="platform-admin-password">كلمة مرور المدير</Label><Input id="platform-admin-password" required minLength={8} maxLength={72} type="password" autoComplete="new-password" value={companyForm.admin_password} onChange={(event) => setFormField("admin_password", event.target.value)} disabled={createCompanyMutation.isPending} dir="ltr" /><p className="text-xs font-semibold text-slate-500">8 أحرف على الأقل.</p></div>
              <div className="grid gap-2"><Label htmlFor="platform-currency">رمز العملة</Label><Input id="platform-currency" required maxLength={10} value={companyForm.currency_code} onChange={(event) => setFormField("currency_code", event.target.value)} disabled={createCompanyMutation.isPending} dir="ltr" /></div>
              <div className="grid gap-2 md:col-span-2"><Label>حالة الاشتراك الابتدائية</Label><Select value={companyForm.subscription_status} onValueChange={(value: PlatformSubscription) => setFormField("subscription_status", value)} disabled={createCompanyMutation.isPending}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="active">نشط</SelectItem><SelectItem value="trial">تجريبي</SelectItem><SelectItem value="suspended">معلق</SelectItem><SelectItem value="expired">منتهي</SelectItem></SelectContent></Select></div>
            </div>
            <DialogFooter className="gap-2 sm:justify-start">
              <Button type="submit" disabled={createCompanyMutation.isPending}>{createCompanyMutation.isPending ? "جارٍ التأسيس..." : "تأسيس الشركة"}</Button>
              <Button type="button" variant="outline" disabled={createCompanyMutation.isPending} onClick={() => setIsCreateOpen(false)}>إلغاء</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </main>
  );
}
