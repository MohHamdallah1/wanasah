import { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseBranchPage, type BranchItem } from "./branchContracts";

interface BranchSelectorProps {
  value: number | null;
  currentLabel: string | null;
  disabled: boolean;
  refreshKey: number;
  onChange: (branchId: number | null) => void;
}

export function BranchSelector({
  value,
  currentLabel,
  disabled,
  refreshKey,
  onChange,
}: BranchSelectorProps) {
  const authenticatedFetch = useAuthFetch();
  const requestSeq = useRef(0);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<BranchItem[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      const clean = searchInput.trim();
      setSearch(clean.length >= 2 ? clean : "");
    }, 250);
    return () => window.clearTimeout(timeoutId);
  }, [searchInput]);

  useEffect(() => {
    const seq = ++requestSeq.current;
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
        setError(requestError instanceof Error ? requestError.message : "تعذر جلب الفروع.");
      } finally {
        if (seq === requestSeq.current) setLoading(false);
      }
    };
    void load();
  }, [authenticatedFetch, refreshKey, search]);

  const options = useMemo(() => {
    if (value === null || items.some((item) => item.id === value) || !currentLabel) return items;
    return [
      ...items,
      {
        id: value,
        name: currentLabel,
        code: "",
        is_active: false,
        created_at: "",
      },
    ];
  }, [currentLabel, items, value]);

  return (
    <div className="space-y-2">
      <label className="text-xs font-bold text-slate-600" htmlFor="warehouse-branch-search">الفرع</label>
      <div className="relative">
        <Search className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          id="warehouse-branch-search"
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          disabled={disabled}
          maxLength={100}
          placeholder="ابحث عن فرع بحرفين على الأقل"
          className="w-full rounded-xl border border-slate-200 py-2.5 pl-3 pr-10 text-sm outline-none focus:ring-2 focus:ring-blue-500/20 disabled:opacity-50"
        />
      </div>
      <select
        value={value === null ? "" : String(value)}
        onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}
        disabled={disabled || loading || Boolean(error)}
        className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500/20 disabled:opacity-50"
      >
        <option value="">غير مرتبط بفرع</option>
        {options.map((branch) => (
          <option key={branch.id} value={branch.id}>
            {branch.name}{branch.code ? ` (${branch.code})` : " (غير فعال)"}
          </option>
        ))}
      </select>
      {loading && <p className="text-xs font-semibold text-slate-400">جارٍ تحميل الفروع...</p>}
      {error && <p role="alert" className="text-xs font-semibold text-red-600">{error}</p>}
      {hasMore && <p className="text-xs font-semibold text-amber-700">توجد نتائج إضافية؛ استخدم البحث للوصول إلى الفرع المطلوب.</p>}
    </div>
  );
}

