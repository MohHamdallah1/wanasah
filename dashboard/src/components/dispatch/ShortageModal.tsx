import { Minus, Trash2 } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { CustomSelect } from "@/components/ui/custom-select";
import { Zone, Shop, Shortage } from "@/types/dispatch";

interface ShortageModalProps {
  isOpen: boolean;
  onClose: () => void;
  zones: Zone[];
  activeShops: Shop[];
  shortageZoneId: string;
  shortageShopId: string;
  onZoneChange: (id: string) => void;
  onShopChange: (id: string) => void;
  products: { id: string; name: string }[];
  newShortage: Partial<Shortage>;
  onNewShortageChange: (shortage: Partial<Shortage>) => void;
  shortageDraft: { productId: string; productName: string; quantity: number }[];
  onAddProductToDraft: () => void;
  onRemoveProductFromDraft: (index: number) => void;
  onConfirmShortages: () => void;
  shortages: Shortage[];
  onDeleteShortage: (id: string) => void;
  drivers: { id: string; name: string }[];
  shortageDriverId: string;
  onDriverChange: (id: string) => void;
}

export function ShortageModal({
  isOpen,
  onClose,
  zones,
  activeShops,
  shortageZoneId,
  shortageShopId,
  onZoneChange,
  onShopChange,
  products,
  newShortage,
  onNewShortageChange,
  shortageDraft,
  onAddProductToDraft,
  onRemoveProductFromDraft,
  onConfirmShortages,
  shortages,
  onDeleteShortage,
  drivers,
  shortageDriverId,
  onDriverChange,
}: ShortageModalProps) {
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="📦 طلبات ونواقص المحلات"
      maxWidth="max-w-5xl"
    >
      <div className="space-y-6">
        <div className="bg-slate-50 p-6 rounded-2xl border border-slate-200 space-y-4">
          <div className="grid grid-cols-3 gap-4">
            <CustomSelect
              label="المنطقة"
              options={zones.map(z => ({ id: z.id, label: z.name }))}
              value={shortageZoneId}
              onChange={onZoneChange}
            />
            <CustomSelect
              label="المحل"
              options={activeShops.filter(s => s.zoneId === shortageZoneId).map(s => ({ id: s.id, label: s.name }))}
              value={shortageShopId}
              onChange={onShopChange}
              disabled={!shortageZoneId}
            />
            <CustomSelect
              label="توجيه الطلب للمندوب"
              options={drivers.map(d => ({ id: d.id, label: d.name }))}
              value={shortageDriverId}
              onChange={onDriverChange}
            />
          </div>

          <div className="grid grid-cols-5 gap-4 items-end bg-white p-4 rounded-xl border border-slate-100">
            <div className="col-span-2 flex flex-col gap-1.5">
              <span className="text-xs font-semibold text-slate-600">المنتج</span>
              <select
                value={newShortage.productName}
                onChange={e => onNewShortageChange({ ...newShortage, productName: e.target.value })}
                className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20 transition-all"
              >
                {products.map(prod => (
                  <option key={prod.id} value={prod.name}>{prod.name}</option>
                ))}
              </select>
            </div>
            <div className="col-span-2 flex flex-col gap-1.5">
              <span className="text-xs font-semibold text-slate-600">الكمية</span>
              <input
                type="number"
                value={newShortage.quantity || 0}
                onChange={e => onNewShortageChange({ ...newShortage, quantity: parseInt(e.target.value) || 0 })}
                onFocus={e => e.target.select()}
                className="w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm text-center outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
              />
            </div>
            <button
              onClick={onAddProductToDraft}
              disabled={!shortageShopId}
              className="bg-emerald-500 text-white h-[46px] rounded-xl font-bold hover:bg-emerald-600 transition-colors shadow-lg shadow-emerald-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              إضافة للقائمة
            </button>
          </div>

          {shortageDraft.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-100 overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 border-b border-slate-100">
                  <tr>
                    <th className="text-start p-3 text-slate-500 font-bold">المنتج</th>
                    <th className="text-center p-3 text-slate-500 font-bold">الكمية</th>
                    <th className="w-12 p-3"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {shortageDraft.map((item, idx) => (
                    <tr key={idx}>
                      <td className="p-3 font-medium text-slate-700">{item.productName}</td>
                      <td className="p-3 text-center font-bold text-[#1e87bb]">{item.quantity}</td>
                      <td className="p-3">
                        <button onClick={() => onRemoveProductFromDraft(idx)} className="text-red-400 hover:text-red-600">
                          <Minus className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <button
            onClick={onConfirmShortages}
            disabled={shortageDraft.length === 0}
            className="w-full bg-[#1e87bb] text-white py-3 rounded-xl font-bold hover:bg-[#156a94] transition-colors shadow-lg shadow-[#1e87bb]/20 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            تأكيد الطلب وحفظ ({shortageDraft.length})
          </button>
        </div>

        <div className="rounded-2xl border border-slate-200 overflow-hidden shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="text-start p-4 text-slate-500 font-bold">المنطقة</th>
                <th className="text-start p-4 text-slate-500 font-bold">المحل</th>
                <th className="text-start p-4 text-slate-500 font-bold">المنتج</th>
                <th className="text-center p-4 text-slate-500 font-bold">الكمية</th>
                <th className="text-center p-4 text-slate-500 font-bold">وقت الانتظار</th>
                <th className="text-center p-4 text-slate-500 font-bold">الحالة</th>
                <th className="w-16 p-4"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {shortages.length === 0 ? (
                <tr>
                  <td colSpan={7} className="p-12 text-center text-slate-400">لا توجد طلبات معلقة</td>
                </tr>
              ) : (
                shortages.map(sh => (
                  <tr key={sh.id} className="hover:bg-slate-50 transition-colors">
                    <td className="p-4 font-medium text-slate-700">{sh.zoneName}</td>
                    <td className="p-4 font-bold text-slate-800">{sh.shopName}</td>
                    <td className="p-4 text-slate-600">{sh.productName}</td>
                    <td className="p-4 text-center font-bold text-[#1e87bb]">{sh.quantity}</td>
                    <td className={`p-4 text-center ${sh.waitTime === "3 ساعات" ? "text-red-500 font-bold animate-pulse" : "text-slate-500"}`}>
                      {sh.waitTime || "الآن"}
                    </td>
                    <td className="p-4 text-center">
                      <span className="px-3 py-1 rounded-full bg-amber-50 text-amber-700 text-[11px] font-bold border border-amber-100">قيد الانتظار</span>
                    </td>
                    <td className="p-4 text-center">
                      <button
                        onClick={() => onDeleteShortage(sh.id)}
                        className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-all"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </Modal>
  );
}
