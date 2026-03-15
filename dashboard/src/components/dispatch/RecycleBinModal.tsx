import { Search, RotateCcw } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { Shop, Zone } from "@/types/dispatch";

interface RecycleBinModalProps {
  isOpen: boolean;
  onClose: () => void;
  recycleSearchQuery: string;
  onRecycleSearchQueryChange: (query: string) => void;
  filteredRecycleBin: Shop[];
  zones: Zone[];
  onRestoreShop: (id: string) => void;
}

export function RecycleBinModal({
  isOpen,
  onClose,
  recycleSearchQuery,
  onRecycleSearchQueryChange,
  filteredRecycleBin,
  zones,
  onRestoreShop,
}: RecycleBinModalProps) {
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="🗑️ سلة المحذوفات"
    >
      <div className="space-y-4">
        <div className="relative">
          <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="search"
            value={recycleSearchQuery}
            onChange={(e) => onRecycleSearchQueryChange(e.target.value)}
            placeholder="بحث في المحذوفات (اسم، مالك، هاتف، منطقة)..."
            className="w-full rounded-xl border border-slate-200 bg-slate-50 pr-9 pl-4 py-2.5 text-sm focus:ring-2 focus:ring-[#1e87bb]/20 outline-none transition-all"
          />
        </div>
        {filteredRecycleBin.length === 0 ? (
          <div className="py-12 text-center text-slate-400">سلة المحذوفات فارغة</div>
        ) : (
          <div className="divide-y divide-slate-100 border border-slate-100 rounded-2xl overflow-hidden">
            {filteredRecycleBin.map(shop => (
              <div key={shop.id} className="flex items-center justify-between p-4 hover:bg-slate-50 transition-colors">
                <div>
                  <p className="font-bold text-slate-800">
                    {shop.name} 
                    <span className="text-xs font-medium text-slate-400 mr-2">({zones.find(z => z.id === shop.zoneId)?.name})</span>
                  </p>
                  <p className="text-xs text-slate-500">{shop.owner} · {shop.phone}</p>
                </div>
                <button
                  onClick={() => onRestoreShop(shop.id)}
                  className="flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-50 text-[#1e87bb] text-sm font-bold hover:bg-emerald-100 transition-colors"
                >
                  <RotateCcw className="w-4 h-4" />
                  استعادة ♻️
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}
