import { GripVertical, Pencil, Archive, MapPin } from "lucide-react";
import { Shop, Zone } from "@/types/dispatch";
import { SequenceInput } from "@/components/ui/sequence-input";
import { useMemo } from "react";

interface ShopTableProps {
  shops: Shop[];
  zones: Zone[];
  isEditMode: boolean;
  selectedShopIds: string[];
  allFilteredShops: Shop[] | null;
  selectedZoneIdForZones: string;
  onToggleSelectAll: () => void;
  onToggleSelectShop: (id: string) => void;
  onSequenceChange: (shopId: string, newSeq: number) => void;
  onEditShop: (shop: Shop) => void;
  onArchiveShop: (id: string) => void;
  onDragStart: (e: React.DragEvent, id: string) => void;
  onDrop: (e: React.DragEvent, targetId: string) => void;
}

export function ShopTable({
  shops,
  zones,
  isEditMode,
  selectedShopIds,
  allFilteredShops,
  selectedZoneIdForZones,
  onToggleSelectAll,
  onToggleSelectShop,
  onSequenceChange,
  onEditShop,
  onArchiveShop,
  onDragStart,
  onDrop,
}: ShopTableProps) {
  // +++ الكي الجراحي: بناء فهرس (Map) للمناطق مرة واحدة فقط لجعل سرعة البحث O(1) +++
  const zonesMap = useMemo(() => {
    const map = new Map<string, string>();
    zones.forEach(z => map.set(z.id, z.name));
    return map;
  }, [zones]);
  
  return (
    <div className="flex-1 overflow-y-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-white shadow-sm z-10">
          <tr className="text-slate-400 text-[10px] uppercase border-b border-slate-100">
            {isEditMode && (
              <th className="w-12 p-3 px-4">
                <input
                  type="checkbox"
                  checked={shops.length > 0 && selectedShopIds.length === shops.length}
                  onChange={onToggleSelectAll}
                  className="w-4 h-4 rounded border-slate-300 text-[#1e87bb] focus:ring-[#1e87bb]/20 cursor-pointer"
                />
              </th>
            )}
            <th className="w-20 p-3 text-center">الترتيب</th>
            <th className="text-start p-3">المحل</th>
            <th className="text-start p-3">المالك / الهاتف</th>
            <th className="p-4 text-start font-bold text-slate-500">المنطقة</th>
            <th className="text-center p-3">المديونية</th>
            {isEditMode && <th className="w-24 p-3"></th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">
          {shops.length === 0 ? (
            <tr>
              <td colSpan={isEditMode ? 6 : 4} className="p-12 text-center text-slate-400">لا توجد محلات في هذه المنطقة حالياً.</td>
            </tr>
          ) : (
            shops.map((shop) => (
              <tr
                key={shop.id}
                draggable={isEditMode}
                onDragStart={(e) => isEditMode && onDragStart(e, shop.id)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => isEditMode && onDrop(e, shop.id)}
                className={`group hover:bg-slate-50/80 transition-colors ${isEditMode ? 'cursor-default' : 'cursor-default'}`}
              >
                {isEditMode && (
                  <td className="p-3 px-4 text-center flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={selectedShopIds.includes(shop.id)}
                      onChange={() => onToggleSelectShop(shop.id)}
                      className="w-4 h-4 rounded border-slate-300 text-[#1e87bb] focus:ring-[#1e87bb]/20 cursor-pointer"
                    />
                    <GripVertical className="w-4 h-4 text-slate-300 group-hover:text-slate-500 cursor-grab active:cursor-grabbing" />
                  </td>
                )}
                <td className="p-3 text-center">
                  {isEditMode ? (
                    <SequenceInput
                      value={shop.sequence}
                      onCommit={(n) => onSequenceChange(shop.id, n)}
                    />
                  ) : (
                    <span className="font-bold text-slate-700">{shop.sequence}</span>
                  )}
                </td>
                <td className="p-3">
                  <div className="flex flex-col">
                    <p className="font-bold text-slate-800">
                      {shop.name}
                      {allFilteredShops !== null && (
                        <span className="mr-2 text-[10px] bg-emerald-50 text-[#1e87bb] px-1.5 py-0.5 rounded-md font-bold">
                          {zonesMap.get(shop.zoneId) || "غير محدد"}
                        </span>
                      )}
                    </p>
                    <a href={shop.mapLink} target="_blank" rel="noreferrer" className="text-[10px] text-emerald-600 font-medium hover:underline w-fit">عرض الموقع</a>
                  </div>
                </td>
                <td className="p-3">
                  <p className="font-medium text-slate-700">{shop.owner}</p>
                  <p className="text-xs text-slate-400">{shop.phone}</p>
                </td>
                <td className="p-4 text-slate-600 font-medium">
                  {zonesMap.get(shop.zoneId) || "غير محدد"}
                </td>
                <td className="p-3 text-center">
                  <span className={`px-2 py-1 rounded-lg text-xs font-bold ${shop.initialDebt > 0 ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-500'}`}>
                    {shop.initialDebt} د.أ
                  </span>
                </td>
                {isEditMode && (
                  <td className="p-3">
                    {/* +++ إزالة opacity-0 لتظهر الأيقونات دائماً في وضع التعديل +++ */}
                    <div className="flex justify-end gap-2 px-4">
                      {/* تولتيب صاروخي لزر التعديل */}
                      <div className="relative group/btn flex items-center">
                        <button
                          onClick={() => onEditShop(shop)}
                          className="p-2 text-slate-400 hover:text-[#1e87bb] hover:bg-emerald-50 rounded-lg transition-all shadow-sm border border-transparent hover:border-emerald-100"
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-max bg-slate-800 text-white text-[10px] font-bold px-2.5 py-1.5 rounded-lg hidden group-hover/btn:block z-50 shadow-xl">
                          تعديل بيانات المحل
                        </div>
                      </div>

                      {/* تولتيب صاروخي لزر الأرشفة */}
                      <div className="relative group/btn flex items-center">
                        <button
                          onClick={() => onArchiveShop(shop.id)}
                          className="p-2 text-slate-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all shadow-sm border border-transparent hover:border-red-100"
                        >
                          <Archive className="w-4 h-4" />
                        </button>
                        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-max bg-slate-800 text-white text-[10px] font-bold px-2.5 py-1.5 rounded-lg hidden group-hover/btn:block z-50 shadow-xl">
                          أرشفة المحل
                        </div>
                      </div>
                    </div>
                  </td>
                )}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
