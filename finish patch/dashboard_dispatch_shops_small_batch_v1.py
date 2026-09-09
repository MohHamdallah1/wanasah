from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOARD = ROOT / "dashboard" / "src" / "pages" / "DispatchBoard.tsx"
BULK_TRANSFER = ROOT / "dashboard" / "src" / "components" / "dispatch" / "BulkTransferModal.tsx"
SHOP_FORM = ROOT / "dashboard" / "src" / "components" / "dispatch" / "ShopFormModal.tsx"
SHOP_TABLE = ROOT / "dashboard" / "src" / "components" / "dispatch" / "ShopTable.tsx"


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"UNCHANGED={label}")
        return
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected 1 match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"PATCHED={label}")


for path in (BOARD, BULK_TRANSFER, SHOP_FORM, SHOP_TABLE):
    if not path.exists():
        fail(f"Missing file: {path.relative_to(ROOT)}")


replace_once(
    BOARD,
    '''        await authenticatedFetch(`/dispatch/shops/${editingShopId}`, {
          method: "PUT",
          body: JSON.stringify(apiPayload)
        });
        setShops(prev => prev.map(s => s.id === editingShopId ? { ...s, ...localShopState } : s));
        if (isEditMode) setHasUnsavedChanges(true);
        setIsShopModalOpen(false);
        toast.success("تم تحديث بيانات المحل ✅");
''',
    '''        await authenticatedFetch(`/dispatch/shops/${editingShopId}`, {
          method: "PUT",
          body: JSON.stringify(apiPayload)
        });
        const [shopsRaw, initRaw] = await Promise.all([
          authenticatedFetch("/dispatch/shops"),
          authenticatedFetch("/dispatch/init"),
        ]);
        setShops(normalizeShops(shopsRaw));
        const initData = initRaw as DispatchInitPayload;
        setZones(sortZones(Array.isArray(initData.zones) ? initData.zones : []));
        setIsShopModalOpen(false);
        toast.success("تم تحديث بيانات المحل ✅");
''',
    "dispatch_shop_edit_canonical_refresh",
)

replace_once(
    BULK_TRANSFER,
    '''        <button 
          onClick={onConfirm}
          className="w-full bg-[#1e87bb] text-white py-2.5 rounded-xl font-bold hover:bg-[#166a94] transition-colors shadow-lg"
        >
''',
    '''        <button
          onClick={onConfirm}
          disabled={selectedShopIds.length === 0 || !targetTransferZoneId}
          className="w-full bg-[#1e87bb] text-white py-2.5 rounded-xl font-bold hover:bg-[#166a94] transition-colors shadow-lg disabled:opacity-50 disabled:cursor-not-allowed"
        >
''',
    "bulk_transfer_fail_closed_button",
)

replace_once(
    SHOP_FORM,
    '''interface ShopFormModalProps {
''',
    '''interface ShopFormState {
  name: string;
  owner: string;
  phone: string;
  mapLink: string;
  zoneId: string;
  initialDebt: number;
  maxDebtLimit: number;
}

interface ShopFormModalProps {
''',
    "shop_form_state_type",
)

replace_once(
    SHOP_FORM,
    '''  shopForm: {
    name: string;
    owner: string;
    phone: string;
    mapLink: string;
    zoneId: string;
    initialDebt: number;
    maxDebtLimit: number;
  };
  onShopFormChange: (form: any) => void;
''',
    '''  shopForm: ShopFormState;
  onShopFormChange: (form: ShopFormState) => void;
''',
    "shop_form_remove_any",
)

replace_once(
    SHOP_FORM,
    '''            type="text"
            value={shopForm.name}
''',
    '''            type="text"
            required
            minLength={2}
            maxLength={150}
            value={shopForm.name}
''',
    "shop_name_contract",
)

replace_once(
    SHOP_FORM,
    '''            type="text"
            value={shopForm.owner}
''',
    '''            type="text"
            maxLength={100}
            value={shopForm.owner}
''',
    "shop_owner_contract",
)

replace_once(
    SHOP_FORM,
    '''            type="tel"
            value={shopForm.phone}
''',
    '''            type="tel"
            maxLength={20}
            value={shopForm.phone}
''',
    "shop_phone_contract",
)

replace_once(
    SHOP_FORM,
    '''              type="url"
              value={shopForm.mapLink}
''',
    '''              type="text"
              maxLength={500}
              value={shopForm.mapLink}
''',
    "shop_map_contract",
)

replace_once(
    SHOP_FORM,
    '''            <input
              type="number"
              value={shopForm.maxDebtLimit}
''',
    '''            <input
              type="number"
              min="0"
              step="0.001"
              value={shopForm.maxDebtLimit}
''',
    "shop_max_debt_contract",
)

replace_once(
    SHOP_FORM,
    '''          <input
            type="number"
            value={shopForm.initialDebt}
''',
    '''          <input
            type="number"
            min="0"
            step="0.001"
            value={shopForm.initialDebt}
''',
    "shop_initial_debt_contract",
)

replace_once(
    SHOP_TABLE,
    '''import { GripVertical, Pencil, Archive, MapPin } from "lucide-react";
''',
    '''import { GripVertical, Pencil, Archive } from "lucide-react";
''',
    "shop_table_unused_import",
)

replace_once(
    SHOP_TABLE,
    '''              <td colSpan={isEditMode ? 6 : 4} className="p-12 text-center text-slate-400">لا توجد محلات في هذه المنطقة حالياً.</td>
''',
    '''              <td colSpan={isEditMode ? 7 : 5} className="p-12 text-center text-slate-400">لا توجد محلات في هذه المنطقة حالياً.</td>
''',
    "shop_table_colspan",
)

replace_once(
    SHOP_TABLE,
    '''                    <a href={shop.mapLink} target="_blank" rel="noreferrer" className="text-[10px] text-emerald-600 font-medium hover:underline w-fit">عرض الموقع</a>
''',
    '''                    {shop.mapLink ? (
                      <a href={shop.mapLink} target="_blank" rel="noreferrer" className="text-[10px] text-emerald-600 font-medium hover:underline w-fit">عرض الموقع</a>
                    ) : (
                      <span className="text-[10px] text-slate-400">لا يوجد موقع</span>
                    )}
''',
    "shop_table_optional_map",
)

board = BOARD.read_text(encoding="utf-8")
bulk_transfer = BULK_TRANSFER.read_text(encoding="utf-8")
shop_form = SHOP_FORM.read_text(encoding="utf-8")
shop_table = SHOP_TABLE.read_text(encoding="utf-8")

checks = {
    "CANONICAL_SHOP_REFRESH": (
        'const [shopsRaw, initRaw] = await Promise.all([' in board
        and 'setShops(normalizeShops(shopsRaw));' in board
    ),
    "NO_FALSE_DIRTY_AFTER_SERVER_SAVE": "if (isEditMode) setHasUnsavedChanges(true);" not in board,
    "BULK_TRANSFER_FAIL_CLOSED": "selectedShopIds.length === 0 || !targetTransferZoneId" in bulk_transfer,
    "SHOP_FORM_NO_ANY": "form: any" not in shop_form,
    "SHOP_FORM_SCHEMA_LIMITS": (
        "minLength={2}" in shop_form
        and "maxLength={150}" in shop_form
        and "maxLength={100}" in shop_form
        and "maxLength={20}" in shop_form
        and "maxLength={500}" in shop_form
    ),
    "SHOP_FORM_MONEY_DECIMALS": shop_form.count('step="0.001"') >= 2,
    "SHOP_TABLE_NO_UNUSED_MAPPIN": "MapPin" not in shop_table,
    "SHOP_TABLE_COLSPAN": "isEditMode ? 7 : 5" in shop_table,
    "SHOP_TABLE_OPTIONAL_MAP": "لا يوجد موقع" in shop_table,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail(f"Static verification failed: {failed}")

print("DISPATCH_SHOP_CANONICAL_REFRESH=OK")
print("BULK_TRANSFER_CONTRACT=OK")
print("SHOP_FORM_BACKEND_CONTRACT=OK")
print("SHOP_TABLE_CONTRACT=OK")
print("DASHBOARD_DISPATCH_SHOPS_SMALL_BATCH_V1=OK")
