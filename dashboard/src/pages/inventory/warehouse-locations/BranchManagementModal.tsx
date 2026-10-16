import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, ChevronRight, Pencil, Plus, Power, PowerOff, RefreshCcw, Search } from "lucide-react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import { parseBranchMutation, parseBranchPage, type BranchItem } from "./branchContracts";
import {
  branchManagementCopy,
  formatInventoryDate,
  formatInventoryInteger,
} from "./i18n";

interface BranchManagementModalProps {
  isOpen: boolean;
  onClose: () => void;
  onBranchesChanged: () => void | Promise<void>;
}

type View = "list" | "form" | "state";
type FormMode = "create" | "edit";

const BRANCH_CODE_RE = /^[A-Z0-9][A-Z0-9_-]*$/;
const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30";

export function BranchManagementModal({ isOpen, onClose, onBranchesChanged }: BranchManagementModalProps) {
  const authenticatedFetch = useAuthFetch();
  const access = useInventoryAccess();
  const canRead = access.can("branch.read");
  const canCreate = access.can("branch.create");
  const canUpdate = access.can("branch.update");
  const canState = access.can("branch.state");
  const { i18n } = useTranslation();
  const language = i18n.resolvedLanguage ?? i18n.language;
  const isArabic = (language ?? "").toLowerCase().startsWith("ar");
  const dir = i18n.dir();
  const copy = branchManagementCopy(language);
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
    if (!isOpen || view !== "list" || !canRead) return;
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
      toast.error(apiErrorMessage(error, copy.loadFailed));
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [authenticatedFetch, canRead, copy.loadFailed, cursor, isOpen, search, view]);

  useEffect(() => { void fetchPage(); }, [fetchPage, refreshKey]);

  useEffect(() => {
    if (!isOpen) return;
    setView("list");
    setCursor(null);
    setCursorHistory([]);
    setNextCursor(null);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || canRead) return;
    requestSeq.current += 1;
    setItems([]);
    setNextCursor(null);
    setTotal(null);
    setLoading(false);
    setView("list");
  }, [canRead, isOpen]);

  const resetList = () => {
    setView("list");
    setCursor(null);
    setCursorHistory([]);
    setNextCursor(null);
    setRefreshKey((value) => value + 1);
  };

  const openCreate = () => {
    if (!canCreate) return;
    setFormMode("create");
    setSelected(null);
    setName("");
    setCode("");
    setRequestId(crypto.randomUUID());
    setView("form");
  };

  const openEdit = (branch: BranchItem) => {
    if (!canUpdate) return;
    setFormMode("edit");
    setSelected(branch);
    setName(branch.name);
    setCode(branch.code);
    setRequestId(crypto.randomUUID());
    setView("form");
  };

  const openState = (branch: BranchItem) => {
    if (!canState) return;
    setSelected(branch);
    setReason("");
    setRequestId(crypto.randomUUID());
    setView("state");
  };

  const saveForm = async () => {
    if ((formMode === "create" && !canCreate) || (formMode === "edit" && !canUpdate)) return;
    const cleanName = name.trim();
    const cleanCode = code.trim().toUpperCase();
    if (!cleanName || cleanName.length > 150) {
      toast.error(copy.nameInvalid);
      return;
    }
    if (!cleanCode || cleanCode.length > 50 || !BRANCH_CODE_RE.test(cleanCode)) {
      toast.error(copy.codeInvalid);
      return;
    }
    if (formMode === "edit" && selected?.name === cleanName && selected.code === cleanCode) {
      toast.info(copy.noChanges);
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
      toast.error(apiErrorMessage(error, copy.saveFailed));
    } finally {
      setSubmitting(false);
    }
  };

  const changeState = async () => {
    if (!selected || !canState) return;
    const activating = !selected.is_active;
    const cleanReason = reason.trim();
    if (!activating && !cleanReason) {
      toast.error(copy.reasonRequired);
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
      toast.error(apiErrorMessage(error, copy.stateFailed));
    } finally {
      setSubmitting(false);
    }
  };

  const title = view === "list" ? copy.manage : view === "form"
    ? (formMode === "create" ? copy.add : copy.edit)
    : (selected?.is_active ? copy.deactivate : copy.activate);
  const canSaveForm = formMode === "create" ? canCreate : canUpdate;
  const pageNumber = formatInventoryInteger(cursorHistory.length + 1, language);
  const totalLabel = total === null ? "" : `${copy.total(formatInventoryInteger(total, language))} · `;

  return (
    <Modal isOpen={isOpen} onClose={() => !submitting && onClose()} title={title} maxWidth="max-w-4xl">
      <div dir={dir}>
      {view === "list" && (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative flex-1">
              <Search aria-hidden="true" className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                maxLength={100}
                disabled={!canRead}
                aria-label={copy.search}
                placeholder={copy.search}
                className={`w-full rounded-xl border border-slate-200 py-2.5 ps-10 pe-3 text-sm outline-none disabled:opacity-50 ${focusRing}`}
              />
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setRefreshKey((value) => value + 1)}
                disabled={loading || !canRead}
                className={`rounded-xl border border-slate-200 p-2.5 text-slate-600 disabled:cursor-not-allowed disabled:opacity-40 ${focusRing}`}
                title={copy.refresh}
                aria-label={copy.refresh}
              >
                <RefreshCcw aria-hidden="true" className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              </button>
              <button
                type="button"
                onClick={openCreate}
                disabled={!canCreate}
                className={`flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-40 ${focusRing}`}
              >
                <Plus aria-hidden="true" className="h-4 w-4" />
                {copy.newBranch}
              </button>
            </div>
          </div>
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className={`w-full min-w-[620px] text-sm ${isArabic ? "text-right" : "text-left"}`}>
              <thead className="bg-slate-50">
                <tr>
                  <th className="p-3">{copy.branch}</th>
                  <th className="p-3">{copy.code}</th>
                  <th className="p-3">{copy.status}</th>
                  <th className="p-3">{copy.created}</th>
                  <th className="p-3 text-center">{copy.actions}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((branch) => (
                  <tr key={branch.id}>
                    <td className="p-3 font-bold text-slate-800">{branch.name}</td>
                    <td className="p-3 font-mono text-xs">{branch.code}</td>
                    <td className="p-3">
                      <span className={`rounded-lg px-2 py-1 text-xs font-bold ${branch.is_active ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
                        {branch.is_active ? copy.active : copy.inactive}
                      </span>
                    </td>
                    <td className="p-3 text-xs text-slate-500">
                      {formatInventoryDate(branch.created_at, language)}
                    </td>
                    <td className="p-3">
                      <div className="flex justify-center gap-2">
                        <button
                          type="button"
                          onClick={() => openEdit(branch)}
                          disabled={!canUpdate}
                          className={`rounded-lg border border-slate-200 p-2 text-slate-600 disabled:cursor-not-allowed disabled:opacity-40 ${focusRing}`}
                          title={copy.editAction}
                          aria-label={`${copy.editAction}: ${branch.name}`}
                        >
                          <Pencil aria-hidden="true" className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => openState(branch)}
                          disabled={!canState}
                          className={`rounded-lg border p-2 disabled:cursor-not-allowed disabled:opacity-40 ${focusRing} ${branch.is_active ? "border-red-200 text-red-600" : "border-emerald-200 text-emerald-600"}`}
                          title={branch.is_active ? copy.deactivateAction : copy.activateAction}
                          aria-label={`${branch.is_active ? copy.deactivateAction : copy.activateAction}: ${branch.name}`}
                        >
                          {branch.is_active
                            ? <PowerOff aria-hidden="true" className="h-4 w-4" />
                            : <Power aria-hidden="true" className="h-4 w-4" />}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!loading && items.length === 0 && (
                  <tr>
                    <td colSpan={5} className="p-10 text-center text-slate-400">
                      {copy.empty}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="min-w-0 break-words text-xs text-slate-500">
              {totalLabel}{copy.page(pageNumber)}
            </span>
            <div className="flex shrink-0 gap-2">
              <button
                type="button"
                disabled={!cursorHistory.length || loading || !canRead}
                onClick={() => {
                  const previous = cursorHistory[cursorHistory.length - 1] ?? null;
                  setCursorHistory((history) => history.slice(0, -1));
                  setCursor(previous);
                }}
                className={`rounded-xl border border-slate-200 p-2 disabled:opacity-40 ${focusRing}`}
                title={copy.previous}
                aria-label={copy.previous}
              >
                {isArabic ? <ChevronRight aria-hidden="true" className="h-4 w-4" /> : <ChevronLeft aria-hidden="true" className="h-4 w-4" />}
              </button>
              <button
                type="button"
                disabled={!nextCursor || loading || !canRead}
                onClick={() => {
                  setCursorHistory((history) => [...history, cursor]);
                  setCursor(nextCursor);
                }}
                className={`rounded-xl border border-slate-200 p-2 disabled:opacity-40 ${focusRing}`}
                title={copy.next}
                aria-label={copy.next}
              >
                {isArabic ? <ChevronLeft aria-hidden="true" className="h-4 w-4" /> : <ChevronRight aria-hidden="true" className="h-4 w-4" />}
              </button>
            </div>
          </div>
        </div>
      )}

      {view === "form" && (
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void saveForm(); }}>
          <label className="block text-xs font-bold text-slate-600">
            {copy.branchName}
            <input
              autoFocus
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                setRequestId(crypto.randomUUID());
              }}
              maxLength={150}
              disabled={submitting || !canSaveForm}
              className={`mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5 outline-none disabled:opacity-50 ${focusRing}`}
            />
          </label>
          <label className="block text-xs font-bold text-slate-600">
            {copy.branchCode}
            <input
              value={code}
              onChange={(event) => {
                setCode(event.target.value.toUpperCase());
                setRequestId(crypto.randomUUID());
              }}
              maxLength={50}
              disabled={submitting || !canSaveForm}
              dir="ltr"
              className={`mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5 font-mono outline-none disabled:opacity-50 ${focusRing}`}
              placeholder="HQ"
            />
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              type="submit"
              disabled={submitting || !canSaveForm}
              className={`rounded-xl bg-blue-600 px-5 py-2.5 font-bold text-white disabled:cursor-not-allowed disabled:opacity-50 ${focusRing}`}
            >
              {submitting ? copy.saving : copy.save}
            </button>
            <button
              type="button"
              onClick={() => setView("list")}
              disabled={submitting}
              className={`rounded-xl border border-slate-200 px-5 py-2.5 font-bold ${focusRing}`}
            >
              {copy.back}
            </button>
          </div>
        </form>
      )}

      {view === "state" && selected && (
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void changeState(); }}>
          <p className="break-words text-sm text-slate-600">
            {copy.branch}: <strong>{selected.name}</strong>
          </p>
          <p className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs font-semibold text-amber-800">
            {copy.nonCascade}
          </p>
          <label className="block text-xs font-bold text-slate-600">
            {selected.is_active ? copy.reasonDeactivate : copy.noteActivate}
            <textarea
              autoFocus
              value={reason}
              onChange={(event) => {
                setReason(event.target.value);
                setRequestId(crypto.randomUUID());
              }}
              maxLength={1000}
              disabled={submitting || !canState}
              className={`mt-1 min-h-28 w-full rounded-xl border border-slate-200 px-3 py-2.5 outline-none disabled:opacity-50 ${focusRing}`}
            />
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              type="submit"
              disabled={submitting || !canState}
              className={`rounded-xl px-5 py-2.5 font-bold text-white disabled:cursor-not-allowed disabled:opacity-50 ${focusRing} ${selected.is_active ? "bg-red-600" : "bg-emerald-600"}`}
            >
              {submitting
                ? copy.executing
                : selected.is_active
                  ? copy.deactivateAction
                  : copy.activateAction}
            </button>
            <button
              type="button"
              onClick={() => setView("list")}
              disabled={submitting}
              className={`rounded-xl border border-slate-200 px-5 py-2.5 font-bold ${focusRing}`}
            >
              {copy.back}
            </button>
          </div>
        </form>
      )}
      </div>
    </Modal>
  );
}
