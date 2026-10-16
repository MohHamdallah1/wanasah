import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Search } from "lucide-react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { branchSelectorCopy } from "./branchSelectorI18n";
import { parseBranchPage, type BranchItem } from "./branchContracts";

interface BranchSelectorProps {
  value: number | null;
  currentLabel: string | null;
  disabled: boolean;
  refreshKey: number;
  canReadBranches: boolean;
  onChange: (branchId: number | null) => void;
}

export function BranchSelector({
  value,
  currentLabel,
  disabled,
  refreshKey,
  canReadBranches,
  onChange,
}: BranchSelectorProps) {
  const authenticatedFetch = useAuthFetch();
  const { i18n } = useTranslation();
  const copy = branchSelectorCopy(i18n.resolvedLanguage ?? i18n.language);
  const requestSeq = useRef(0);
  const currentBranchIdRef = useRef<number | null>(value);
  const currentLabelRef = useRef<string | null>(currentLabel);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<BranchItem[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (currentLabel !== currentLabelRef.current) {
      currentLabelRef.current = currentLabel;
      currentBranchIdRef.current = value;
    } else if (currentLabel === null) {
      currentBranchIdRef.current = null;
    }
  }, [currentLabel, value]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      const clean = searchInput.trim();
      setSearch(clean.length >= 2 ? clean : "");
    }, 250);
    return () => window.clearTimeout(timeoutId);
  }, [searchInput]);

  useEffect(() => {
    const seq = ++requestSeq.current;
    if (!canReadBranches) {
      setItems([]);
      setHasMore(false);
      setLoading(false);
      setError("");
      return;
    }
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const params = new URLSearchParams({ limit: "50" });
        if (search) params.set("search", search);
        const page = parseBranchPage(
          await authenticatedFetch(`/warehouse/branches/options?${params.toString()}`),
        );
        if (seq !== requestSeq.current) return;
        setItems(page.items);
        setHasMore(page.has_more);
      } catch (requestError) {
        if (seq !== requestSeq.current) return;
        setItems([]);
        setHasMore(false);
        setError(requestError instanceof Error ? requestError.message : copy.loadFailed);
      } finally {
        if (seq === requestSeq.current) setLoading(false);
      }
    };
    void load();
  }, [authenticatedFetch, canReadBranches, copy.loadFailed, refreshKey, search]);

  const currentBranchId = currentBranchIdRef.current;
  const options = useMemo(() => {
    if (
      currentBranchId === null ||
      items.some((item) => item.id === currentBranchId) ||
      !currentLabel
    ) return items;
    return [
      ...items,
      {
        id: currentBranchId,
        name: currentLabel,
        code: "",
        is_active: false,
        created_at: "",
      },
    ];
  }, [currentBranchId, currentLabel, items]);

  if (!canReadBranches) {
    return (
      <div className="space-y-2">
        <span className="text-xs font-bold text-slate-600">{copy.branch}</span>
        <div className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-600">
          {currentLabel ?? (currentBranchId === null ? copy.none : `${copy.currentNumber} #${currentBranchId}`)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <label className="text-xs font-bold text-slate-600" htmlFor="warehouse-branch-search">{copy.branch}</label>
      <div className="relative">
        <Search className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
        <input
          id="warehouse-branch-search"
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          disabled={disabled}
          maxLength={100}
          placeholder={copy.search}
          className="w-full rounded-xl border border-slate-200 py-2.5 ps-10 pe-3 text-sm outline-none focus:ring-2 focus:ring-blue-500/20 disabled:opacity-50"
        />
      </div>
      <select
        value={value === null ? "" : String(value)}
        onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}
        disabled={disabled || loading || Boolean(error)}
        className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500/20 disabled:opacity-50"
      >
        <option value="">{copy.none}</option>
        {options.map((branch) => {
          const preservedCurrent = !branch.is_active && branch.id === currentBranchId;
          return (
            <option
              key={branch.id}
              value={branch.id}
              disabled={preservedCurrent && value !== currentBranchId}
            >
              {branch.name}{branch.code ? ` (${branch.code})` : ` (${copy.current})`}
            </option>
          );
        })}
      </select>
      {loading && <p className="text-xs font-semibold text-slate-400">{copy.loading}</p>}
      {error && <p role="alert" className="text-xs font-semibold text-red-600">{error}</p>}
      {hasMore && <p className="text-xs font-semibold text-amber-700">{copy.more}</p>}
    </div>
  );
}
