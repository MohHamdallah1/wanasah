from __future__ import annotations

from pathlib import Path
import hashlib
import re

ROOT = Path(__file__).resolve().parent
BOARD = ROOT / "dashboard" / "src" / "pages" / "DispatchBoard.tsx"
SHORTAGE_MODAL = ROOT / "dashboard" / "src" / "components" / "dispatch" / "ShortageModal.tsx"
TYPES = ROOT / "dashboard" / "src" / "types" / "dispatch.ts"
SCHEMAS = ROOT / "wa_backend" / "schemas.py"
DISPATCH = ROOT / "wa_backend" / "api" / "dispatch.py"

EXPECTED_BOARD_SHA256 = "f9d44dbec7ac4006d8e39a2a3a0e7e656b7705e8a3c8c456a2a13d0e79ad1746"


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n")


def sha256_norm(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def write_preserving_newlines(path: Path, content_lf: str) -> None:
    raw = path.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    content = content_lf if newline == "\n" else content_lf.replace("\n", "\r\n")
    path.write_text(content, encoding="utf-8", newline="")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"UNCHANGED={label}")
        return text
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected 1 match, found {count}")
    print(f"PATCHED={label}")
    return text.replace(old, new, 1)


for path in (BOARD, SHORTAGE_MODAL, TYPES, SCHEMAS, DISPATCH):
    if not path.exists():
        fail(f"Missing file: {path.relative_to(ROOT)}")


# ============================================================
# 1) DispatchBoard.tsx — exact current reviewed attachment only
# ============================================================
board_raw = BOARD.read_text(encoding="utf-8")
board = normalize(board_raw)
if sha256_norm(board_raw) != EXPECTED_BOARD_SHA256:
    if "replaceShortageGroupAtomic" not in board:
        fail(
            "DispatchBoard.tsx differs from the exact reviewed attachment. "
            f"Current normalized SHA256={sha256_norm(board_raw)}"
        )

if "const shortageMutationInFlightRef = useRef(false);" not in board:
    board = replace_once(
        board,
        '''  // Snapshot of shops taken when entering edit mode — used for Cancel/revert
  const savedShopsRef = useRef<Shop[]>([]);
''',
        '''  // Snapshot of shops taken when entering edit mode — used for Cancel/revert
  const savedShopsRef = useRef<Shop[]>([]);
  const shortageMutationInFlightRef = useRef(false);
''',
        "dispatchboard_shortage_mutation_guard",
    )

board = replace_once(
    board,
    '''        if (nextProducts.length > 0) {
          setNewShortage((prev) =>
            prev.productName
              ? prev
              : { productName: nextProducts[0].name, quantity: 1 }
          );
        }
''',
    '''        if (nextProducts.length > 0) {
          setNewShortage((prev) =>
            prev.productId
              ? prev
              : {
                  productId: nextProducts[0].id,
                  productName: nextProducts[0].name,
                  quantity: 1,
                }
          );
        }
''',
    "dispatchboard_shortage_product_identity_init",
)

old_shortage_block = '''  const handleAddShortage = async () => {
    if (!shortageZoneId || !shortageShopId || shortageDraft.length === 0) {
      return toast.error("⚠️ يرجى إكمال بيانات الطلب");
    }
    if (
      shortageDraft.some(
        (item) =>
          !item.productId ||
          !Number.isInteger(Number(item.productId)) ||
          Number(item.productId) <= 0 ||
          !Number.isInteger(Number(item.quantity)) ||
          Number(item.quantity) <= 0
      )
    ) {
      return toast.error("⚠️ يوجد منتج أو كمية غير صالحة في الطلب.");
    }

    const newShortages = shortageDraft.map((item) => ({
      zoneId: Number(shortageZoneId),
      shopId: Number(shortageShopId),
      driverId: shortageDriverId ? Number(shortageDriverId) : null,
      productId: Number(item.productId),
      quantity: Number(item.quantity),
    }));
    try {
      // إذا كنا في وضع التعديل: احذف الطلبات القديمة أولاً ثم أنشئ الجديدة (Delete-then-Insert)
      if (editingShortageIds.length > 0) {
        await Promise.all(
          editingShortageIds.map(id =>
            authenticatedFetch(`/dispatch/shortages/${id}`, { method: "DELETE" })
          )
        );
        setEditingShortageIds([]);
      }
      await authenticatedFetch("/dispatch/shortages", {
        method: "POST",
        body: JSON.stringify(newShortages)
      });
      const data = await authenticatedFetch("/dispatch/shortages");
      setShortages(Array.isArray(data) ? data : []);
      setShortageDraft([]);
      if (products.length > 0) setNewShortage({ productName: products[0].name, quantity: 1 });
      toast.success("تم تسجيل الطلبات بنجاح");
    } catch (err: unknown) {
      toast.error(getErrorMessage(err));
    }
  };

  const handleAddProductToDraft = () => {
    if (!newShortage.productName || !newShortage.quantity) return toast.error("⚠️ اختر منتج وكمية");
    const product = products.find(pr => pr.name === newShortage.productName);
    setShortageDraft(prev => {
      const existing = prev.findIndex(d => d.productName === newShortage.productName);
      if (existing !== -1) {
        // دمج الكمية بدل إضافة سطر جديد
        return prev.map((d, i) => i === existing ? { ...d, quantity: d.quantity + newShortage.quantity! } : d);
      }
      return [...prev, { productId: product?.id || "", productName: newShortage.productName!, quantity: newShortage.quantity! }];
    });
    setNewShortage(p => ({ ...p, quantity: 1 }));
  };

  const handleEditShortageGroup = (shopId: string) => {
    const shopShortages = shortages.filter(s => s.shopId === shopId);
    if (shopShortages.length === 0) return;

    const first = shopShortages[0];

    // 1. تحديد المنطقة والمحل في قوائم الاختيار
    setShortageZoneId(first.zoneId);
    setShortageShopId(first.shopId);

    // 2. نقل المنتجات للـ Draft
    const draft = shopShortages.map(s => ({
      productId: s.productId,
      productName: s.productName,
      quantity: s.quantity,
    }));
    setShortageDraft(draft);

    // 3. حفظ IDs القديمة للحذف لاحقاً عند تأكيد الطلب فقط (لا حذف الآن)
    setEditingShortageIds(shopShortages.map(s => s.id));

    toast.info("تم تحميل الطلب للتعديل — عدّل الكميات ثم اضغط تأكيد الطلب");
  };

  const handleCloseShortageModal = () => {
    setIsShortageModalOpen(false);
    setShortageDraft([]);
    setShortageZoneId("");
    setShortageShopId("");
    setEditingShortageIds([]);
  };
'''

new_shortage_block = '''  const refreshShortages = useCallback(async () => {
    const data = await authenticatedFetch("/dispatch/shortages");
    setShortages(Array.isArray(data) ? data : []);
  }, [authenticatedFetch]);

  const replaceShortageGroupAtomic = useCallback(
    async (
      shortageIds: string[],
      items: Array<{
        zoneId: number;
        shopId: number;
        driverId: number | null;
        productId: number;
        quantity: number;
      }>
    ) => {
      if (shortageMutationInFlightRef.current) {
        toast.info("هناك عملية نواقص قيد التنفيذ.");
        return false;
      }

      const parsedIds = shortageIds.map(Number);
      if (
        parsedIds.length === 0 ||
        parsedIds.some((id) => !Number.isInteger(id) || id <= 0)
      ) {
        toast.error("معرفات طلبات النواقص غير صالحة.");
        return false;
      }

      shortageMutationInFlightRef.current = true;
      try {
        await authenticatedFetch("/dispatch/shortages/group", {
          method: "PUT",
          body: JSON.stringify({
            request_id: crypto.randomUUID(),
            shortage_ids: parsedIds,
            items,
          }),
        });
        await refreshShortages();
        return true;
      } catch (err: unknown) {
        toast.error(getErrorMessage(err));
        return false;
      } finally {
        shortageMutationInFlightRef.current = false;
      }
    },
    [authenticatedFetch, refreshShortages]
  );

  const handleAddShortage = async () => {
    if (!shortageZoneId || !shortageShopId || shortageDraft.length === 0) {
      return toast.error("⚠️ يرجى إكمال بيانات الطلب");
    }
    if (
      shortageDraft.some(
        (item) =>
          !item.productId ||
          !Number.isInteger(Number(item.productId)) ||
          Number(item.productId) <= 0 ||
          !Number.isInteger(Number(item.quantity)) ||
          Number(item.quantity) <= 0
      )
    ) {
      return toast.error("⚠️ يوجد منتج أو كمية غير صالحة في الطلب.");
    }

    const newShortages = shortageDraft.map((item) => ({
      zoneId: Number(shortageZoneId),
      shopId: Number(shortageShopId),
      driverId: shortageDriverId ? Number(shortageDriverId) : null,
      productId: Number(item.productId),
      quantity: Number(item.quantity),
    }));

    if (shortageMutationInFlightRef.current) {
      toast.info("هناك عملية نواقص قيد التنفيذ.");
      return;
    }

    try {
      let saved = false;
      if (editingShortageIds.length > 0) {
        saved = await replaceShortageGroupAtomic(
          editingShortageIds,
          newShortages
        );
      } else {
        shortageMutationInFlightRef.current = true;
        try {
          await authenticatedFetch("/dispatch/shortages", {
            method: "POST",
            body: JSON.stringify(newShortages),
          });
          await refreshShortages();
          saved = true;
        } finally {
          shortageMutationInFlightRef.current = false;
        }
      }

      if (!saved) return;

      const wasEditing = editingShortageIds.length > 0;
      setEditingShortageIds([]);
      setShortageDraft([]);
      if (products.length > 0) {
        setNewShortage({
          productId: products[0].id,
          productName: products[0].name,
          quantity: 1,
        });
      }
      toast.success(
        wasEditing
          ? "تم حفظ تعديلات الطلبات ذرياً"
          : "تم تسجيل الطلبات بنجاح"
      );
    } catch (err: unknown) {
      toast.error(getErrorMessage(err));
      shortageMutationInFlightRef.current = false;
    }
  };

  const handleAddProductToDraft = () => {
    if (!newShortage.productId || !newShortage.quantity) {
      return toast.error("⚠️ اختر منتج وكمية");
    }

    const product = products.find((item) => item.id === newShortage.productId);
    if (!product) {
      return toast.error("المنتج المحدد لم يعد متاحاً.");
    }

    setShortageDraft((prev) => {
      const existing = prev.findIndex(
        (item) => item.productId === product.id
      );
      if (existing !== -1) {
        return prev.map((item, index) =>
          index === existing
            ? {
                ...item,
                quantity: item.quantity + Number(newShortage.quantity),
              }
            : item
        );
      }
      return [
        ...prev,
        {
          productId: product.id,
          productName: product.name,
          quantity: Number(newShortage.quantity),
        },
      ];
    });
    setNewShortage((prev) => ({ ...prev, quantity: 1 }));
  };

  const handleEditShortageGroup = (
    shopId: string,
    driverId?: string
  ) => {
    const shopShortages = shortages.filter(
      (item) =>
        item.shopId === shopId &&
        (item.driverId || "") === (driverId || "")
    );
    if (shopShortages.length === 0) return;

    const first = shopShortages[0];
    const identityKeys = new Set(
      shopShortages.map(
        (item) =>
          `${item.zoneId}:${item.shopId}:${item.driverId || ""}`
      )
    );
    if (identityKeys.size !== 1) {
      toast.error("مجموعة النواقص غير متسقة ولا يمكن تعديلها بأمان.");
      return;
    }

    setShortageZoneId(first.zoneId);
    setShortageShopId(first.shopId);
    setShortageDriverId(first.driverId || "");

    setShortageDraft(
      shopShortages.map((item) => ({
        productId: item.productId,
        productName: item.productName,
        quantity: item.quantity,
      }))
    );

    setEditingShortageIds(shopShortages.map((item) => item.id));
    toast.info("تم تحميل الطلب للتعديل — الهوية ثابتة ويمكن تعديل المنتجات والكميات.");
  };

  const handleDeleteShortageGroup = (ids: string[]) => {
    setConfirmDialog({
      isOpen: true,
      title: "حذف طلبات المحل",
      message: `هل أنت متأكد من حذف المجموعة كاملة (${ids.length} منتجات)؟`,
      onConfirm: async () => {
        try {
          const deleted = await replaceShortageGroupAtomic(ids, []);
          if (deleted) {
            toast.success("تم حذف المجموعة كاملة ذرياً");
          }
        } finally {
          setConfirmDialog((dialog) => ({ ...dialog, isOpen: false }));
        }
      },
    });
  };

  const handleCloseShortageModal = () => {
    setIsShortageModalOpen(false);
    setShortageDraft([]);
    setShortageZoneId("");
    setShortageShopId("");
    setShortageDriverId("");
    setEditingShortageIds([]);
  };
'''

board = replace_once(
    board,
    old_shortage_block,
    new_shortage_block,
    "dispatchboard_atomic_shortage_group",
)

board = replace_once(
    board,
    '''        onCancelEdit={() => { setShortageDraft([]); setEditingShortageIds([]); setShortageZoneId(""); setShortageShopId(""); }}
''',
    '''        onCancelEdit={() => { setShortageDraft([]); setEditingShortageIds([]); setShortageZoneId(""); setShortageShopId(""); setShortageDriverId(""); }}
''',
    "dispatchboard_shortage_cancel_identity",
)

old_group_delete_prop = '''        onDeleteShortageGroup={ids => setConfirmDialog({ isOpen: true, title: "حذف طلبات المحل", message: `هل أنت متأكد من حذف جميع طلبات هذا المحل (${ids.length} منتجات) نهائياً؟`, onConfirm: async () => { try { await Promise.all(ids.map(id => authenticatedFetch(`/dispatch/shortages/${id}`, { method: "DELETE" }))); setShortages(prev => prev.filter(s => !ids.includes(s.id))); toast.success("تم حذف جميع طلبات المحل بنجاح"); } catch (e: unknown) { toast.error("خطأ في الحذف: " + getErrorMessage(e)); } finally { setConfirmDialog(d => ({ ...d, isOpen: false })); } } })}
'''
board = replace_once(
    board,
    old_group_delete_prop,
    '''        onDeleteShortageGroup={handleDeleteShortageGroup}
''',
    "dispatchboard_atomic_shortage_group_delete",
)

write_preserving_newlines(BOARD, board)


# ============================================================
# 2) ShortageModal — group by shop+driver and lock identity edit
# ============================================================
modal = normalize(SHORTAGE_MODAL.read_text(encoding="utf-8"))

modal = replace_once(
    modal,
    '''  onEditShortageGroup: (shopId: string) => void;
''',
    '''  onEditShortageGroup: (shopId: string, driverId?: string) => void;
''',
    "shortage_modal_edit_callback_contract",
)

modal = replace_once(
    modal,
    '''  const map = new Map<string, {
    shopId: string; shopName: string; zoneName: string;
    driverName: string;
''',
    '''  const map = new Map<string, {
    shopId: string; shopName: string; zoneName: string;
    driverId: string;
    driverName: string;
''',
    "shortage_modal_group_driver_field",
)

modal = replace_once(
    modal,
    '''  for (const sh of shortages) {
    if (!map.has(sh.shopId)) {
      map.set(sh.shopId, {
        shopId: sh.shopId,
        shopName: sh.shopName,
        zoneName: sh.zoneName,
        driverName: sh.driverName || "",
''',
    '''  for (const sh of shortages) {
    const groupKey = `${sh.shopId}:${sh.driverId || ""}`;
    if (!map.has(groupKey)) {
      map.set(groupKey, {
        shopId: sh.shopId,
        shopName: sh.shopName,
        zoneName: sh.zoneName,
        driverId: sh.driverId || "",
        driverName: sh.driverName || "",
''',
    "shortage_modal_group_key",
)

modal = replace_once(
    modal,
    '''    const entry = map.get(sh.shopId)!;
''',
    '''    const entry = map.get(groupKey)!;
''',
    "shortage_modal_group_lookup",
)

modal = replace_once(
    modal,
    '''                value={shortageZoneId}
                onChange={onZoneChange}
              />
''',
    '''                value={shortageZoneId}
                onChange={onZoneChange}
                disabled={isEditMode}
              />
''',
    "shortage_modal_lock_zone",
)

modal = replace_once(
    modal,
    '''                value={shortageShopId}
                onChange={onShopChange}
                disabled={!shortageZoneId}
              />
''',
    '''                value={shortageShopId}
                onChange={onShopChange}
                disabled={isEditMode || !shortageZoneId}
              />
''',
    "shortage_modal_lock_shop",
)

modal = replace_once(
    modal,
    '''                value={shortageDriverId}
                onChange={onDriverChange}
              />
''',
    '''                value={shortageDriverId}
                onChange={onDriverChange}
                disabled={isEditMode}
              />
''',
    "shortage_modal_lock_driver",
)

modal = replace_once(
    modal,
    '''                <select
                  value={newShortage.productName}
                  onChange={e => onNewShortageChange({ ...newShortage, productName: e.target.value })}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20 transition-all"
                >
                  {products.map(prod => (
                    <option key={prod.id} value={prod.name}>{prod.name}</option>
                  ))}
                </select>
''',
    '''                <select
                  value={newShortage.productId || ""}
                  onChange={e => {
                    const product = products.find(item => item.id === e.target.value);
                    onNewShortageChange({
                      ...newShortage,
                      productId: e.target.value,
                      productName: product?.name || "",
                    });
                  }}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20 transition-all"
                >
                  {products.map(prod => (
                    <option key={prod.id} value={prod.id}>{prod.name}</option>
                  ))}
                </select>
''',
    "shortage_modal_product_id_selection",
)

modal = replace_once(
    modal,
    '''              onEdit={() => onEditShortageGroup(group.shopId)}
''',
    '''              onEdit={() => onEditShortageGroup(group.shopId, group.driverId)}
''',
    "shortage_modal_edit_group_identity",
)

write_preserving_newlines(SHORTAGE_MODAL, modal)


# ============================================================
# 3) Frontend type — ensure sessionBound + shortage product ID
# ============================================================
types = normalize(TYPES.read_text(encoding="utf-8"))

if "  sessionBound: boolean;\n" not in types:
    types = replace_once(
        types,
        '''  sessionEnded: boolean;
''',
        '''  sessionEnded: boolean;
  sessionBound: boolean;
''',
        "dispatch_types_session_bound",
    )
else:
    print("UNCHANGED=dispatch_types_session_bound")

shortage_section = ""
if "export interface Shortage {" in types:
    shortage_section = types.split("export interface Shortage {", 1)[1].split("}", 1)[0]
if "  productId: string;\n" not in shortage_section:
    types = replace_once(
        types,
        '''export interface Shortage {
  id: string;
''',
        '''export interface Shortage {
  id: string;
  productId: string;
''',
        "dispatch_types_shortage_product_id",
    )

write_preserving_newlines(TYPES, types)


# ============================================================
# 4) Backend schema — atomic shortage group request
# ============================================================
schemas = normalize(SCHEMAS.read_text(encoding="utf-8"))

if "class ReplaceShortageGroupRequest(RequestModel):" not in schemas:
    marker = "class BulkImportRequest"
    index = schemas.find(marker)
    if index == -1:
        fail("Could not locate BulkImportRequest insertion anchor in schemas.py")

    schema_block = '''class ReplaceShortageGroupRequest(RequestModel):
    request_id: UUID
    shortage_ids: List[PositiveDbInt] = Field(..., min_length=1, max_length=5000)
    items: List[CreateShortageItem] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def validate_group_replace(self) -> "ReplaceShortageGroupRequest":
        ids = [int(item_id) for item_id in self.shortage_ids]
        if len(ids) != len(set(ids)):
            raise ValueError("shortage_ids تحتوي معرفاً مكرراً.")

        if self.items:
            identities = {
                (
                    int(item.shopId),
                    int(item.zoneId),
                    int(item.driverId) if item.driverId is not None else None,
                )
                for item in self.items
            }
            if len(identities) != 1:
                raise ValueError("استبدال مجموعة النواقص يجب أن يحافظ على محل/منطقة/مندوب واحد.")

            product_ids = [int(item.product_variant_id) for item in self.items]
            if len(product_ids) != len(set(product_ids)):
                raise ValueError("لا يجوز تكرار نفس المنتج داخل مجموعة النواقص.")

        return self


'''
    schemas = schemas[:index] + schema_block + schemas[index:]
    print("PATCHED=schemas_replace_shortage_group")
else:
    print("UNCHANGED=schemas_replace_shortage_group")

write_preserving_newlines(SCHEMAS, schemas)


# ============================================================
# 5) Backend dispatch — import + atomic company-scoped endpoint
# ============================================================
dispatch = normalize(DISPATCH.read_text(encoding="utf-8"))

if "ReplaceShortageGroupRequest" not in dispatch.split(")\nfrom uuid", 1)[0]:
    dispatch = replace_once(
        dispatch,
        '''CreateShortageItem, BulkImportRequest, UpdateZoneRequest, RestoreZoneRequest, ForceCancelHandshakeRequest)
''',
        '''CreateShortageItem, ReplaceShortageGroupRequest, BulkImportRequest, UpdateZoneRequest, RestoreZoneRequest, ForceCancelHandshakeRequest)
''',
        "dispatch_import_replace_shortage_group",
    )

if '@router.put("/dispatch/shortages/group"' not in dispatch:
    marker = "# =========================================\n# 26. الاستيراد الآمن للمحلات بالجملة"
    index = dispatch.find(marker)
    if index == -1:
        fail("Could not locate shortage endpoint insertion anchor in dispatch.py")

    endpoint = r'''# =========================================
# 25B. استبدال/حذف مجموعة نواقص ذرياً داخل Tenant واحد
# =========================================
@router.put("/dispatch/shortages/group", status_code=200)
async def replace_shortage_group(
    payload: ReplaceShortageGroupRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id
    shortage_ids = sorted({int(item_id) for item_id in payload.shortage_ids})
    canonical_items = sorted(
        [
            {
                "zoneId": int(item.zoneId),
                "shopId": int(item.shopId),
                "driverId": int(item.driverId) if item.driverId is not None else None,
                "productId": int(item.product_variant_id),
                "quantity": int(item.quantity),
            }
            for item in payload.items
        ],
        key=lambda item: item["productId"],
    )
    request_hash = hashlib.sha256(
        json.dumps(
            {"shortage_ids": shortage_ids, "items": canonical_items},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="DISPATCH_REPLACE_SHORTAGE_GROUP",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay is not None:
            await db.rollback()
            return replay

        pre_rows = (
            await db.execute(
                select(
                    ShortageRequest.id,
                    ShortageRequest.shop_id,
                    ShortageRequest.zone_id,
                    ShortageRequest.driver_id,
                    ShortageRequest.status,
                )
                .filter(
                    ShortageRequest.company_id == company_id,
                    ShortageRequest.id.in_(shortage_ids),
                )
                .order_by(ShortageRequest.id.asc())
            )
        ).all()

        if {int(row.id) for row in pre_rows} != set(shortage_ids):
            raise HTTPException(status_code=404, detail="أحد طلبات النواقص غير موجود داخل الشركة.")
        if any(str(row.status) != "pending" for row in pre_rows):
            raise HTTPException(status_code=409, detail="لا يمكن تعديل مجموعة تحتوي طلباً غير معلق.")

        shop_ids = {int(row.shop_id) for row in pre_rows}
        zone_ids = {int(row.zone_id) for row in pre_rows}
        driver_ids = {
            int(row.driver_id) if row.driver_id is not None else None
            for row in pre_rows
        }
        if len(shop_ids) != 1 or len(zone_ids) != 1 or len(driver_ids) != 1:
            raise HTTPException(
                status_code=409,
                detail="مجموعة النواقص الحالية غير متسقة في المحل/المنطقة/المندوب.",
            )

        shop_id = next(iter(shop_ids))
        zone_id = next(iter(zone_ids))
        driver_id = next(iter(driver_ids))

        if payload.items:
            for item in payload.items:
                next_driver_id = int(item.driverId) if item.driverId is not None else None
                if (
                    int(item.shopId) != shop_id
                    or int(item.zoneId) != zone_id
                    or next_driver_id != driver_id
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="تعديل مجموعة النواقص لا يسمح بتغيير المحل أو المنطقة أو المندوب.",
                    )

        if driver_id is not None and payload.items:
            driver = (
                await db.execute(
                    select(Driver)
                    .filter(
                        Driver.company_id == company_id,
                        Driver.id == driver_id,
                    )
                    .order_by(Driver.id.asc())
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if driver is None:
                raise HTTPException(
                    status_code=409,
                    detail="المندوب المرتبط بمجموعة النواقص لم يعد موجوداً داخل الشركة.",
                )

        locked_zones = await _dispatch_lock_zone_rows(
            db,
            company_id=company_id,
            zone_ids=[zone_id],
        )
        await _dispatch_advisory_locks(
            db,
            company_id=company_id,
            keys=[f"dispatch-shop:{shop_id}"],
        )

        locked_shortages = (
            await db.execute(
                select(ShortageRequest)
                .filter(
                    ShortageRequest.company_id == company_id,
                    ShortageRequest.id.in_(shortage_ids),
                )
                .order_by(ShortageRequest.id.asc())
                .with_for_update()
            )
        ).scalars().all()

        if {int(row.id) for row in locked_shortages} != set(shortage_ids):
            raise HTTPException(
                status_code=409,
                detail="تغيرت مجموعة النواقص أثناء التعديل؛ أعد تحميل البيانات.",
            )
        if any(str(row.status) != "pending" for row in locked_shortages):
            raise HTTPException(status_code=409, detail="تغيرت حالة أحد طلبات النواقص أثناء التعديل.")
        if any(
            int(row.shop_id) != shop_id
            or int(row.zone_id) != zone_id
            or (int(row.driver_id) if row.driver_id is not None else None) != driver_id
            for row in locked_shortages
        ):
            raise HTTPException(status_code=409, detail="تغيرت هوية مجموعة النواقص أثناء التعديل.")

        shop = (
            await db.execute(
                select(Shop)
                .filter(Shop.company_id == company_id, Shop.id == shop_id)
                .order_by(Shop.id.asc())
                .with_for_update()
            )
        ).scalar_one_or_none()
        if shop is None:
            raise HTTPException(
                status_code=409,
                detail="المحل المرتبط بمجموعة النواقص مفقود داخل الشركة.",
            )

        if payload.items:
            zone = locked_zones[zone_id]
            if not zone.is_active or shop.is_archived or not shop.is_active:
                raise HTTPException(
                    status_code=409,
                    detail="لا يمكن حفظ نواقص لمحل أو منطقة غير فعالة.",
                )
            if shop.zone_id is None or int(shop.zone_id) != zone_id:
                raise HTTPException(status_code=409, detail="منطقة مجموعة النواقص لا تطابق منطقة المحل.")

            product_ids = sorted({int(item.product_variant_id) for item in payload.items})
            variants = (
                await db.execute(
                    select(ProductVariant)
                    .filter(
                        ProductVariant.company_id == company_id,
                        ProductVariant.id.in_(product_ids),
                    )
                    .order_by(ProductVariant.id.asc())
                )
            ).scalars().all()
            if {int(variant.id) for variant in variants} != set(product_ids):
                raise HTTPException(status_code=404, detail="أحد المنتجات غير موجود أو لا يتبع شركتك.")

            conflicting = (
                await db.execute(
                    select(ShortageRequest.id)
                    .filter(
                        ShortageRequest.company_id == company_id,
                        ShortageRequest.shop_id == shop_id,
                        ShortageRequest.product_variant_id.in_(product_ids),
                        ShortageRequest.status == "pending",
                        ShortageRequest.id.notin_(shortage_ids),
                    )
                    .order_by(ShortageRequest.id.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if conflicting is not None:
                raise HTTPException(
                    status_code=409,
                    detail="يوجد طلب معلق آخر لأحد المنتجات خارج المجموعة التي تعدلها.",
                )

        pending_visit = None
        if driver_id is not None:
            await _dispatch_advisory_locks(
                db,
                company_id=company_id,
                keys=[f"pending-visit:{driver_id}:{shop_id}"],
            )
            pending_visits = (
                await db.execute(
                    select(Visit)
                    .filter(
                        Visit.company_id == company_id,
                        Visit.driver_id == driver_id,
                        Visit.shop_id == shop_id,
                        Visit.status == "Pending",
                    )
                    .order_by(Visit.id.asc())
                    .with_for_update()
                )
            ).scalars().all()
            if len(pending_visits) > 1:
                raise HTTPException(
                    status_code=409,
                    detail="تم اكتشاف أكثر من زيارة Pending لنفس المندوب والمحل.",
                )
            pending_visit = pending_visits[0] if pending_visits else None

        for row in locked_shortages:
            await db.delete(row)
        await db.flush()

        for item in payload.items:
            db.add(
                ShortageRequest(
                    company_id=company_id,
                    zone_id=zone_id,
                    shop_id=shop_id,
                    driver_id=driver_id,
                    product_variant_id=int(item.product_variant_id),
                    quantity=int(item.quantity),
                )
            )
        await db.flush()

        if driver_id is not None:
            remaining_for_owner = int(
                (
                    await db.execute(
                        select(func.count(ShortageRequest.id)).filter(
                            ShortageRequest.company_id == company_id,
                            ShortageRequest.shop_id == shop_id,
                            ShortageRequest.driver_id == driver_id,
                            ShortageRequest.status == "pending",
                        )
                    )
                ).scalar()
                or 0
            )

            if remaining_for_owner > 0:
                if pending_visit is None:
                    company_local_date = await get_company_local_date(db, company_id)
                    pending_visit = Visit(
                        company_id=company_id,
                        driver_id=driver_id,
                        shop_id=shop_id,
                        operational_date=company_local_date,
                        status="Pending",
                        sequence=shop.sequence if shop.sequence is not None else 999,
                        is_emergency=True,
                    )
                    db.add(pending_visit)
                else:
                    pending_visit.is_emergency = True
            elif pending_visit is not None and pending_visit.is_emergency:
                active_route = (
                    await db.execute(
                        select(DispatchRoute)
                        .filter(
                            DispatchRoute.company_id == company_id,
                            DispatchRoute.driver_id == driver_id,
                            DispatchRoute.status == "active",
                        )
                        .order_by(DispatchRoute.id.asc())
                        .limit(1)
                    )
                ).scalars().first()

                if active_route is not None and int(active_route.zone_id) == int(shop.zone_id or 0):
                    pending_visit.is_emergency = False
                else:
                    pending_visit.status = "Cancelled"
                    pending_visit.is_emergency = False
                    pending_visit.work_session_id = None

        response = {
            "message": (
                "تم حذف مجموعة النواقص ذرياً."
                if not payload.items
                else "تم استبدال مجموعة النواقص ذرياً."
            ),
            "deleted_count": len(shortage_ids),
            "created_count": len(payload.items),
        }
        complete_idempotent_operation(idem, response)
        await db.commit()

        asyncio.create_task(
            dispatch_manager.broadcast(
                {"event": "SHORTAGE_UPDATED", "message": "تم تحديث مجموعة نواقص"},
                company_id=company_id,
            )
        )
        return response

    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        logger.error(
            f"Shortage group replace integrity conflict: {str(exc)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=409,
            detail="تعارض متزامن أثناء تعديل مجموعة النواقص.",
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.error(
            f"Shortage group replace failed: {str(exc)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ داخلي أثناء تعديل مجموعة النواقص.",
        ) from exc


'''
    dispatch = dispatch[:index] + endpoint + dispatch[index:]
    print("PATCHED=dispatch_atomic_shortage_group_endpoint")
else:
    print("UNCHANGED=dispatch_atomic_shortage_group_endpoint")

write_preserving_newlines(DISPATCH, dispatch)


# ============================================================
# 6) Static gates
# ============================================================
board = normalize(BOARD.read_text(encoding="utf-8"))
modal = normalize(SHORTAGE_MODAL.read_text(encoding="utf-8"))
types = normalize(TYPES.read_text(encoding="utf-8"))
schemas = normalize(SCHEMAS.read_text(encoding="utf-8"))
dispatch = normalize(DISPATCH.read_text(encoding="utf-8"))

endpoint_start = dispatch.find('@router.put("/dispatch/shortages/group"')
endpoint_end = dispatch.find("# =========================================\n# 26. الاستيراد الآمن", endpoint_start)
if endpoint_start == -1 or endpoint_end == -1:
    fail("Atomic shortage group endpoint not found after patch.")
endpoint_text = dispatch[endpoint_start:endpoint_end]

checks = {
    "SESSION_BOUND_TYPE": "sessionBound: boolean;" in types,
    "NO_DELETE_THEN_INSERT": (
        "Delete-then-Insert" not in board
        and "Promise.all(\n          editingShortageIds.map" not in board
    ),
    "ATOMIC_EDIT_ENDPOINT_USED": (
        'authenticatedFetch("/dispatch/shortages/group"' in board
        and "replaceShortageGroupAtomic" in board
    ),
    "ATOMIC_GROUP_DELETE": "onDeleteShortageGroup={handleDeleteShortageGroup}" in board,
    "EDIT_DRIVER_PRESERVED": "setShortageDriverId(first.driverId || \"\");" in board,
    "PRODUCT_SELECTED_BY_ID": (
        "newShortage.productId" in board
        and "value={newShortage.productId || \"\"}" in modal
        and "<option key={prod.id} value={prod.id}>" in modal
    ),
    "EDIT_IDENTITY_LOCKED": (
        "disabled={isEditMode}" in modal
        and "disabled={isEditMode || !shortageZoneId}" in modal
    ),
    "GROUP_BY_SHOP_DRIVER": (
        'const groupKey = `${sh.shopId}:${sh.driverId || ""}`;' in modal
        and "driverId: string;" in modal
    ),
    "REQUEST_ID_IDEMPOTENCY": (
        "request_id: crypto.randomUUID()" in board
        and "request_id: UUID" in schemas
        and 'operation="DISPATCH_REPLACE_SHORTAGE_GROUP"' in endpoint_text
    ),
    "TENANT_SCOPE_ALL_SHORTAGE_QUERIES": (
        endpoint_text.count("ShortageRequest.company_id == company_id") >= 5
        and "Shop.company_id == company_id" in endpoint_text
        and "ProductVariant.company_id == company_id" in endpoint_text
        and "Visit.company_id == company_id" in endpoint_text
        and "DispatchRoute.company_id == company_id" in endpoint_text
    ),
    "GROUP_IDENTITY_FAIL_CLOSED": "لا يسمح بتغيير المحل أو المنطقة أو المندوب" in endpoint_text,
    "ATOMIC_TRANSACTION_SINGLE_COMMIT": endpoint_text.count("await db.commit()") == 1,
    "ROLLBACK_ON_FAILURE": endpoint_text.count("await db.rollback()") >= 3,
    "NO_COMPANY_ID_FROM_FRONTEND": re.search(r"\bcompany_?id\b", board, re.I) is None,
    "WAREHOUSE_STATUS_HAS_LOCATION_ID": (
        '/warehouse/status?location_id=${encodeURIComponent(selectedSourceWarehouseId)}'
        in board
    ),
    "ROUTE_SOURCE_LOCATION_ID": "source_location_id: Number(selectedSourceWarehouseId)" in board,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail(f"Static verification failed: {failed}")

print("SHORTAGE_ATOMIC_REPLACE=OK")
print("SHORTAGE_ATOMIC_GROUP_DELETE=OK")
print("SHORTAGE_IDENTITY_LOCK=OK")
print("SHORTAGE_PRODUCT_IDENTITY=OK")
print("SHORTAGE_TENANT_ISOLATION=OK")
print("DISPATCH_LOCATION_SCOPE=OK")
print("DASHBOARD_DISPATCH_SHORTAGE_ATOMIC_V4=OK")
