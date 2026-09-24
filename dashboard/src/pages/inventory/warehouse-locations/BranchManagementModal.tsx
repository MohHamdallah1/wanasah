import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, ChevronRight, Pencil, Plus, Power, PowerOff, RefreshCcw, Search } from "lucide-react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { resolveI18nLocale } from "@/lib/locale";
import { parseBranchMutation, parseBranchPage, type BranchItem } from "./branchContracts";

interface BranchManagementModalProps {
  isOpen: boolean;
  onClose: () => void;
  onBranchesChanged: () => void | Promise<void>;
}

type View = "list" | "form" | "state";
type FormMode = "create" | "edit";

const BRANCH_CODE_RE = /^[A-Z0-9][A-Z0-9_-]*$/;

export function BranchManagementModal({ isOpen, onClose, onBranchesChanged }: BranchManagementModalProps) {
  const authenticatedFetch = useAuthFetch();
  const { i18n } = useTranslation();
  const locale = resolveI18nLocale(i18n);
  const requestSeq = useRef(0);
  const [view, setView] = useState<View>("list");
  const [items, setItems] = useState<BranchItem[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [formMode, setFormMode] = useState<FormMode>("create");
  const [selected, setSelected] = useState<BranchItem | null>(null);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [reason, setReason] = useState("");
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      const clean = searchInput.trim();
      setSearch(clean.length >= 2 ? clean : "");
      setCursor(null);
      setCursorHistory([]);
      setNextCursor(null);
    }, 300);
    return () => window.clearTimeout(timeoutId);
  }, [searchInput]);

  const fetchPage = useCallback(async () => {
    if (!isOpen || view !== "list") return;
    const seq = ++requestSeq.current;
    setLoading(true);
    try {
      const params = new URLSearchParams({ include_inactive: "true", limit: "50" });
      if (search) params.set("search", search);
      if (cursor) params.set("cursor", cursor);
      const page = parseBranchPage(
        await authenticatedFetch(`/warehouse/branches/manage?${params.toString()}`),
      );
      if (seq !== requestSeq.current) return;
      setItems(page.items);
      setNextCursor(page.next_cursor);
      if (page.total !== null) setTotal(page.total);
    } catch (error) {
      if (seq !== requestSeq.current) return;
      setItems([]);
      setNextCursor(null);
      toast.error(error instanceof Error ? error.message : "تعذر جلب الفروع.");
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [authenticatedFetch, cursor, isOpen, search, view]);

  useEffect(() => { void fetchPage(); }, [fetchPage, refreshKey]);

  useEffect(() => {
    if (!isOpen) return;
    setView("list");
    setCursor(null);
    setCursorHistory([]);
    setNextCursor(null);
  }, [isOpen]);

  const resetList = () => {
    setView("list");
    setCursor(null);
    setCursorHistory([]);
    setNextCursor(null);
    setRefreshKey((value) => value + 1);
  };

  const openCreate = () => {
    setFormMode("create");
    setSelected(null);
    setName("");
    setCode("");
    setRequestId(crypto.randomUUID());
    setView("form");
  };

  const openEdit = (branch: BranchItem) => {
    setFormMode("edit");
    setSelected(branch);
    setName(branch.name);
    setCode(branch.code);
    setRequestId(crypto.randomUUID());
    setView("form");
  };

  const openState = (branch: BranchItem) => {
    setSelected(branch);
    setReason("");
    setRequestId(crypto.randomUUID());
    setView("state");
  };

  const saveForm = async () => {
    const cleanName = name.trim();
    const cleanCode = code.trim().toUpperCase();
    if (!cleanName || cleanName.length > 150) {
      toast.error("اسم الفرع مطلوب وبحد أقصى 150 حرفاً.");
      return;
    }
    if (!cleanCode || cleanCode.length > 50 || !BRANCH_CODE_RE.test(cleanCode)) {
      toast.error("كود الفرع يجب أن يبدأ بحرف/رقم ويحتوي فقط A-Z و0-9 و _ و -.");
      return;
    }
    if (formMode === "edit" && selected?.name === cleanName && selected.code === cleanCode) {
      toast.info("لا توجد تغييرات لحفظها.");
      return;
    }

    setSubmitting(true);
    try {
      const result = parseBranchMutation(await authenticatedFetch(
        formMode === "create" ? "/warehouse/branches" : `/warehouse/branches/${selected?.id}`,
        {
          method: formMode === "create" ? "POST" : "PATCH",
          body: JSON.stringify({ request_id: requestId, name: cleanName, code: cleanCode }),
        },
      ));
      toast.success(result.message);
      resetList();
      await onBranchesChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "تعذر حفظ الفرع.");
    } finally {
      setSubmitting(false);
    }
  };

  const changeState = async () => {
    if (!selected) return;
    const activating = !selected.is_active;
    const cleanReason = reason.trim();
    if (!activating && !cleanReason) {
      toast.error("سبب تعطيل الفرع مطلوب للتدقيق.");
      return;
    }
    setSubmitting(true);
    try {
      const result = parseBranchMutation(await authenticatedFetch(
        `/warehouse/branches/${selected.id}/${activating ? "activate" : "deactivate"}`,
        {
          method: "POST",
          body: JSON.stringify({ request_id: requestId, reason: cleanReason || null }),
        },
      ));
      toast.success(result.message);
      resetList();
      await onBranchesChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "تعذر تغيير حالة الفرع.");
    } finally {
      setSubmitting(false);
    }
  };

  const title = view === "list" ? "إدارة الفروع" : view === "form"
    ? (formMode === "create" ? "إضافة فرع" : "تعديل الفرع")
    : (selected?.is_active ? "تعطيل الفرع" : "تفعيل الفرع");

  return (
    <Modal isOpen={isOpen} onClose={() => !submitting && onClose()} title={title} maxWidth="max-w-4xl">
      {view === "list" && (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative flex-1">
              <Search className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                maxLength={100}
                placeholder="بحث بالاسم أو الكود"
                className="w-full rounded-xl border border-slate-200 py-2.5 pl-3 pr-10 text-sm outline-none"
              />
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setRefreshKey((value) => value + 1)}
                disabled={loading}
                className="rounded-xl border border-slate-200 p-2.5 text-slate-600 disabled:opacity-50"
                title="تحديث"
              >
                <RefreshCcw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              </button>
              <button
                type="button"
                onClick={openCreate}
                className="flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-bold text-white"
              >
                <Plus className="h-4 w-4" />
                فرع جديد
              </button>
            </div>
          </div>
          <div className="overflow-auto rounded-xl border border-slate-200">
            <table className="w-full min-w-[620px] text-right text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="p-3">الفرع</th>
                  <th className="p-3">الكود</th>
                  <th className="p-3">الحالة</th>
                  <th className="p-3">تاريخ الإنشاء</th>
                  <th className="p-3 text-center">إجراءات</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((branch) => (
                  <tr key={branch.id}>
                    <td className="p-3 font-bold text-slate-800">{branch.name}</td>
                    <td className="p-3 font-mono text-xs">{branch.code}</td>
                    <td className="p-3">
                      <span className={`rounded-lg px-2 py-1 text-xs font-bold ${branch.is_active ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
                        {branch.is_active ? "فعال" : "متوقف"}
                      </span>
                    </td>
                    <td className="p-3 text-xs text-slate-500">
                      {new Date(branch.created_at).toLocaleDateString(locale)}
                    </td>
                    <td className="p-3">
                      <div className="flex justify-center gap-2">
                        <button
                          type="button"
                          onClick={() => openEdit(branch)}
                          className="rounded-lg border border-slate-200 p-2 text-slate-600"
                          title="تعديل"
                        >
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => openState(branch)}
                          className={`rounded-lg border p-2 ${branch.is_active ? "border-red-200 text-red-600" : "border-emerald-200 text-emerald-600"}`}
                          title={branch.is_active ? "تعطيل" : "تفعيل"}
                        >
                          {branch.is_active
                            ? <PowerOff className="h-4 w-4" />
                            : <Power className="h-4 w-4" />}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!loading && items.length === 0 && (
                  <tr>
                    <td colSpan={5} className="p-10 text-center text-slate-400">
                      لا توجد فروع مطابقة.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500">
              {total !== null ? `${total} فرع · ` : ""}الصفحة {cursorHistory.length + 1}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={!cursorHistory.length || loading}
                onClick={() => {
                  const previous = cursorHistory[cursorHistory.length - 1] ?? null;
                  setCursorHistory((history) => history.slice(0, -1));
                  setCursor(previous);
                }}
                className="rounded-xl border border-slate-200 p-2 disabled:opacity-40"
                title="الصفحة السابقة"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
              <button
                type="button"
                disabled={!nextCursor || loading}
                onClick={() => {
                  setCursorHistory((history) => [...history, cursor]);
                  setCursor(nextCursor);
                }}
                className="rounded-xl border border-slate-200 p-2 disabled:opacity-40"
                title="الصفحة التالية"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      )}

      {view === "form" && (
        <div className="space-y-4">
          <div>
            <label className="text-xs font-bold text-slate-600">اسم الفرع</label>
            <input
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                setRequestId(crypto.randomUUID());
              }}
              maxLength={150}
              disabled={submitting}
              className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5 outline-none"
            />
          </div>
          <div>
            <label className="text-xs font-bold text-slate-600">كود الفرع</label>
            <input
              value={code}
              onChange={(event) => {
                setCode(event.target.value.toUpperCase());
                setRequestId(crypto.randomUUID());
              }}
              maxLength={50}
              disabled={submitting}
              dir="ltr"
              className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5 font-mono outline-none"
              placeholder="HQ"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={saveForm}
              disabled={submitting}
              className="rounded-xl bg-blue-600 px-5 py-2.5 font-bold text-white disabled:opacity-50"
            >
              {submitting ? "جارٍ الحفظ..." : "حفظ"}
            </button>
            <button
              type="button"
              onClick={() => setView("list")}
              disabled={submitting}
              className="rounded-xl border border-slate-200 px-5 py-2.5 font-bold"
            >
              رجوع
            </button>
          </div>
        </div>
      )}

      {view === "state" && selected && (
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            الفرع: <strong>{selected.name}</strong>
          </p>
          <p className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs font-semibold text-amber-800">
            تغيير حالة الفرع لا يغير حالة المستودعات المرتبطة ولا صلاحيات المواقع.
          </p>
          <div>
            <label className="text-xs font-bold text-slate-600">
              {selected.is_active ? "سبب التعطيل - إجباري" : "ملاحظة التفعيل - اختيارية"}
            </label>
            <textarea
              value={reason}
              onChange={(event) => {
                setReason(event.target.value);
                setRequestId(crypto.randomUUID());
              }}
              maxLength={1000}
              disabled={submitting}
              className="mt-1 min-h-28 w-full rounded-xl border border-slate-200 px-3 py-2.5 outline-none"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={changeState}
              disabled={submitting}
              className={`rounded-xl px-5 py-2.5 font-bold text-white disabled:opacity-50 ${selected.is_active ? "bg-red-600" : "bg-emerald-600"}`}
            >
              {submitting
                ? "جارٍ التنفيذ..."
                : selected.is_active
                  ? "تأكيد التعطيل"
                  : "تأكيد التفعيل"}
            </button>
            <button
              type="button"
              onClick={() => setView("list")}
              disabled={submitting}
              className="rounded-xl border border-slate-200 px-5 py-2.5 font-bold"
            >
              رجوع
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
