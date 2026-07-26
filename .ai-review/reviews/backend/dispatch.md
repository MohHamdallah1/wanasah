# Surgical Code Audit — `wa_backend/api/dispatch.py`

> Scope: Bugs, security vulnerabilities, race conditions, and architectural flaws found by direct code inspection, cross-referenced against `.ai-review/04_BUSINESS_RULES.md`. No source files were modified. File is 2968 lines / 26 endpoints.

---

## Finding #1

- **Severity**: Critical
- **Flaw Category**: Missing Validation → Inventory Fabrication (Phantom Stock)
- **Exact File & Line Number**: `wa_backend/api/dispatch.py`, lines 1983–2013 (function `update_route_status`, "no active session" inventory-edit branch)
- **Current Flawed Code**:
```python
raw_qty = payload.inventory.get(str(p_id), payload.inventory.get(p_id, 0))
clean_str = str(raw_qty).strip() if raw_qty is not None else ''
new_cartons = int(clean_str) if clean_str.isdigit() or (clean_str.startswith('-') and clean_str[1:].isdigit()) else 0
new_packs = new_cartons * ppc

curr_load = existing_vl_map.get(p_id)
curr_packs = (curr_load.quantity * ppc) if curr_load else 0
delta_packs = new_packs - curr_packs

if delta_packs == 0: continue

wh_rec = bulk_wh.get(p_id)
if not wh_rec:
    wh_rec = MainWarehouse(product_variant_id=p_id, available_quantity_packs=0, reserved_quantity_packs=0)
    db.add(wh_rec)
    
if delta_packs > 0:
    ...
else:
    wh_rec.available_quantity_packs += abs(delta_packs)
    db.add(WarehouseLedger(product_variant_id=p_id, transaction_type='DISPATCH_UNLOAD', quantity_packs=abs(delta_packs), balance_after_packs=wh_rec.available_quantity_packs, admin_id=current_admin.id, reference_id=f"VEH_EDIT_{route.id}", notes="تعديل حمولة سيارة قبل الدوام: إعادة للمستودع"))
    
if curr_load:
    if new_cartons <= 0: db.delete(curr_load)
    else: curr_load.quantity = new_cartons
elif new_cartons > 0:
    db.add(VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=p_id, quantity=new_cartons))
```
- **Impact Analysis**: The regex `clean_str.startswith('-') and clean_str[1:].isdigit()` **explicitly permits negative "cartons" values** to reach the math with zero range validation. If an admin (or a buggy/compromised dashboard client) submits a negative quantity for a product that already has a `VehicleLoad` row, `new_packs` becomes negative, inflating `delta_packs` far below the true intended change. The `else` branch then credits `MainWarehouse.available_quantity_packs` with `abs(delta_packs)` — **manufacturing warehouse stock out of thin air**. Crucially, unlike the sibling code in `dispatch_route` (Finding #4), this path **sidesteps the `chk_vload_qty` DB constraint** entirely because `new_cartons <= 0` triggers a `db.delete(curr_load)` instead of writing a negative value — so there is **no database-level backstop** and the fabricated warehouse credit **commits successfully**, permanently corrupting `MainWarehouse.available_quantity_packs` and violating Business Rule §1.3 (negative-stock/no-phantom-stock invariant, "no negative-value commit is permitted at any of these code paths" — this is the *inverse* exploit: positive-value fabrication via a negative input).
- **Recommended Surgical Fix**:
```python
raw_qty = payload.inventory.get(str(p_id), payload.inventory.get(p_id, 0))
clean_str = str(raw_qty).strip() if raw_qty is not None else ''
new_cartons = int(clean_str) if clean_str.isdigit() or (clean_str.startswith('-') and clean_str[1:].isdigit()) else 0

if new_cartons < 0:
    await db.rollback()
    raise HTTPException(status_code=400, detail=f"مرفوض: لا يمكن أن تكون كمية الصنف ({variant.variant_name}) سالبة.")

new_packs = new_cartons * ppc
```

---

## Finding #2

- **Severity**: High
- **Flaw Category**: Deadlock Risk / Lock-Ordering Violation
- **Exact File & Line Number**: `wa_backend/api/dispatch.py`, lines 439–466 (function `settle_session`)
- **Current Flawed Code**:
```python
# +++ قفل عهدة الجلسة لمنع المندوب من مزامنة زيارات متأخرة أثناء التسوية (Race Condition Shield) +++
stmt_inv = select(SessionInventory).with_for_update().filter_by(work_session_id=session.id)
all_session_inv = (await db.execute(stmt_inv)).scalars().all()
bulk_inv_records = {inv.product_variant_id: inv for inv in all_session_inv}
...
if all_involved_pids:
    stmt_vars = select(ProductVariant).filter(ProductVariant.id.in_(all_involved_pids))
    bulk_variants = {v.id: v for v in (await db.execute(stmt_vars)).scalars().all()}

    # +++ النسف المعماري للـ Deadlock المتصالب: تفريغ/قفل السيارة دائماً قبل قفل المستودع +++
    if route and route.vehicle_id:
        await db.execute(delete(VehicleLoad).where(VehicleLoad.vehicle_id == route.vehicle_id))

    stmt_wh = select(MainWarehouse).with_for_update().filter(
        MainWarehouse.product_variant_id.in_(all_involved_pids)
    ).order_by(MainWarehouse.product_variant_id.asc())
    bulk_wh_records = {w.product_variant_id: w for w in (await db.execute(stmt_wh)).scalars().all()}
```
- **Impact Analysis**: Business Rule §1.8 states the lock order `VehicleLoad → MainWarehouse → SessionInventory` is "a mandatory rule... repeated identically across ... `settle_session`" to prevent cross-endpoint deadlocks. Here, `SessionInventory` is locked **first** (line 440), and only *afterwards* is `VehicleLoad` deleted/locked (line 461) and `MainWarehouse` locked (line 463) — the exact reverse of the documented order used by `dispatch_route` and `adjust_route_inventory` in this same file. Two `DispatchRoute` rows can legitimately share the same `vehicle_id` over time (an old closed-but-unsettled route and a new route assigned to a different driver on the same truck). If an admin settles one session while another operation on the same vehicle (e.g. a concurrent `settle_session` for a sibling session, or `adjust_route_inventory`) is in-flight, the two transactions acquire `SessionInventory`/`VehicleLoad`/`MainWarehouse` locks in opposite orders — a textbook precondition for a Postgres deadlock, which manifests as a 500 error and forces a client-side retry of a financial settlement.
- **Recommended Surgical Fix**:
```python
# Lock/clear VehicleLoad and MainWarehouse BEFORE SessionInventory, per the mandated global order.
all_involved_pids = list(set(
    [r.product_variant_id for r in damaged_returns] + list(jard_map.keys())
))
all_involved_pids.sort()

if route and route.vehicle_id:
    await db.execute(delete(VehicleLoad).where(VehicleLoad.vehicle_id == route.vehicle_id))

stmt_wh = select(MainWarehouse).with_for_update().filter(
    MainWarehouse.product_variant_id.in_(all_involved_pids)
).order_by(MainWarehouse.product_variant_id.asc())
bulk_wh_records = {w.product_variant_id: w for w in (await db.execute(stmt_wh)).scalars().all()}

stmt_inv = select(SessionInventory).with_for_update().filter_by(work_session_id=session.id)
all_session_inv = (await db.execute(stmt_inv)).scalars().all()
bulk_inv_records = {inv.product_variant_id: inv for inv in all_session_inv}
all_involved_pids = sorted(set(all_involved_pids + list(bulk_inv_records.keys())))
```

---

## Finding #3

- **Severity**: High
- **Flaw Category**: Logic Bug / Incorrect Data Selection (Dict-Overwrite Ordering)
- **Exact File & Line Number**: `wa_backend/api/dispatch.py`, lines 2620–2628 (function `add_shortages`)
- **Current Flawed Code**:
```python
stmt_visits = select(Visit).with_for_update().filter(
    Visit.shop_id.in_(shop_ids),
    or_(
        Visit.status == 'Pending',
        and_(Visit.visit_timestamp >= today_start, Visit.visit_timestamp < today_end)
    )
).order_by(Visit.id.desc())
recent_visits = (await db.execute(stmt_visits)).scalars().all()
bulk_visits = {v.shop_id: v for v in recent_visits} 
```
- **Impact Analysis**: The query explicitly orders by `Visit.id.desc()` — clearly intending to prioritize the **most recent** visit per shop (the variable is even named `recent_visits`). However, a Python dict comprehension keeps the **last-processed** value for a duplicate key. Since iteration proceeds from *newest to oldest* (DESC order), the **oldest** matching visit for each shop is what actually survives in `bulk_visits`, not the newest. This directly undermines the "financial corruption shield" logic a few lines below (lines 2696–2737), whose entire purpose is to inspect `existing_visit.status`/`existing_visit.driver_id` of the *current* relevant visit before deciding whether to safely transfer it or spin up a new one. Operating on a stale, superseded visit row instead of the actual current one can cause the wrong `Visit` to be re-flagged as emergency, reassigned to a driver, or resurrected from `Cancelled`, while the true current visit for that shop is silently ignored.
- **Recommended Surgical Fix**:
```python
recent_visits = (await db.execute(stmt_visits)).scalars().all()
bulk_visits = {}
for v in recent_visits:  # already DESC by id -> first occurrence per shop is the newest
    if v.shop_id not in bulk_visits:
        bulk_visits[v.shop_id] = v
```

---

## Finding #4

- **Severity**: Medium
- **Flaw Category**: Missing Validation → Unhandled DB Constraint Violation
- **Exact File & Line Number**: `wa_backend/api/dispatch.py`, lines 767–773 and 848–854 (function `dispatch_route`, morning-load branch)
- **Current Flawed Code**:
```python
# parsing (lines 767-773)
for p, q in payload.inventory.items():
    if str(q).strip() != '':
        try:
            clean_inventory[int(str(p).strip())] = int(str(q).strip())
        except ValueError:
            continue
...
# assignment (lines 848-854)
if current_v_load:
    if new_cartons == 0: 
        db.delete(current_v_load) # الحذف الآمن في الذاكرة (Sync)
    else: 
        current_v_load.quantity = new_cartons
elif new_cartons > 0:
    db.add(VehicleLoad(vehicle_id=payload.vehicle_id, product_variant_id=p_id, quantity=new_cartons))
```
- **Impact Analysis**: No check rejects a negative integer for `q`. If `new_cartons` is negative and a `current_v_load` row already exists, the `if new_cartons == 0` test is `False` (it's not exactly zero), so the `else` branch writes a **negative value directly into `VehicleLoad.quantity`**. This violates `chk_vload_qty` (Business Rule §1.1) and aborts the whole transaction with a raw `IntegrityError`, which is caught only by the generic `except Exception` handler and surfaces as an opaque `500` instead of a clean `400`. Additionally, before the constraint kills the transaction, `wh_record.available_quantity_packs` was already mutated in memory based on the bogus negative `delta_packs` — harmless only because the rollback discards it, but it demonstrates the same missing-validation root cause as Finding #1, just currently defused by luck of the DB constraint rather than by design.
- **Recommended Surgical Fix**:
```python
for p, q in payload.inventory.items():
    if str(q).strip() != '':
        try:
            val = int(str(q).strip())
        except ValueError:
            continue
        if val < 0:
            continue  # or: raise HTTPException(400, ...) to reject the whole payload explicitly
        clean_inventory[int(str(p).strip())] = val
```

---

## Finding #5

- **Severity**: Medium
- **Flaw Category**: Data Integrity / Reporting Corruption
- **Exact File & Line Number**: `wa_backend/api/dispatch.py`, lines 540–552 (function `settle_session`)
- **Current Flawed Code**:
```python
# الكمية الصالحة المتبقية بعد عزل التوالف من الجرد الملموس
sellable_qty = actual_qty - damaged_packs

# +++ الدرع المحاسبي 2: تجميد اللقطة التاريخية (Snapshot) لإنقاذ تقارير المحاسبة +++
if inv_record:
    inv_record.current_remaining_quantity = actual_qty
else:
    db.add(SessionInventory(
        work_session_id=session.id,
        product_variant_id=prod_id,
        starting_quantity=0,
        current_remaining_quantity=actual_qty
    ))
```
- **Impact Analysis**: `current_remaining_quantity` is persisted as the raw **physical** jard count (`actual_qty`), which by design **includes damaged/expired units** (`damaged_packs`), not the sellable-only remainder. This field is read directly by `get_session_settlement_report` and `get_admin_dashboard_data` (both in this same file) to compute `sold_quantity = total_received - current_remaining_quantity`. After settlement, any damaged quantity for a product is silently folded into "remaining" instead of "sold/disposed", causing the settlement report and dashboard to **permanently under-report the true sold quantity** and over-report remaining sellable stock for that session — a direct contradiction of Business Rule §5.3 which treats damaged stock as a distinct accounting bucket from sellable remaining stock.
- **Recommended Surgical Fix**:
```python
if inv_record:
    inv_record.current_remaining_quantity = max(sellable_qty, 0)
else:
    db.add(SessionInventory(
        work_session_id=session.id,
        product_variant_id=prod_id,
        starting_quantity=0,
        current_remaining_quantity=max(sellable_qty, 0)
    ))
```
(Note: this fix must be applied before the existing `if sellable_qty < 0: ... sellable_qty = 0` clamp at line 554, or duplicated via `max(sellable_qty, 0)` as shown, to stay consistent with the floor rule already implemented later in the same function.)

---

## Finding #6

- **Severity**: Medium
- **Flaw Category**: Race Condition / Transaction Isolation (Stale Read)
- **Exact File & Line Number**: `wa_backend/api/dispatch.py`, lines 429–430 and 638–639 (function `settle_session`)
- **Current Flawed Code**:
```python
stmt_route = select(DispatchRoute).filter_by(work_session_id=session.id)
route = (await db.execute(stmt_route)).scalar_one_or_none()
...
# (used throughout the function for route.vehicle_id, ledger entries, etc.)
...
session.is_settled = True
if route:
    route.work_session_id = None
```
- **Impact Analysis**: Unlike every other row this function mutates (`WorkSession`, `SessionInventory`, `MainWarehouse`), `DispatchRoute` is read with a plain `SELECT`, **without `.with_for_update()`**. `route.vehicle_id` is then used throughout the function to decide where stock goes (vehicle rollover vs. warehouse fallback) and to tag ledger entries. If `update_route_status` concurrently reassigns this same route's `vehicle_id` (or driver) and commits in the window between this read and `settle_session`'s own commit, `settle_session` operates on a stale `vehicle_id`, potentially crediting `VehicleLoad`/ledger entries against a vehicle that is no longer actually associated with this route, corrupting the audit trail for a financially terminal, one-way operation (Business Rule §5.5).
- **Recommended Surgical Fix**:
```python
stmt_route = select(DispatchRoute).with_for_update().filter_by(work_session_id=session.id)
route = (await db.execute(stmt_route)).scalar_one_or_none()
```

---

## Finding #7

- **Severity**: Medium
- **Flaw Category**: Race Condition (TOCTOU)
- **Exact File & Line Number**: `wa_backend/api/dispatch.py`, lines 763–764 (function `dispatch_route`)
- **Current Flawed Code**:
```python
stmt_session = select(WorkSession).filter_by(driver_id=payload.driver_id, end_time=None)
active_session = (await db.execute(stmt_session)).scalar_one_or_none()
```
- **Impact Analysis**: Whether `active_session` is truthy determines the entire code path — synchronous "morning load" stock movement (direct `MainWarehouse`/`VehicleLoad` mutation) vs. the reserved "mid-day handshake" (`InventoryTransfer` + `reserved_quantity_packs`), per Business Rule §2.2. This is read with no row lock. If the target driver starts (or ends) a `WorkSession` concurrently with this admin dispatch action, the branch decision can be based on stale data, causing `VehicleLoad`/`SessionInventory` to diverge from what the driver's own device believes it has — a "split-brain" custody state that Business Rule §2.6 explicitly says must never occur.
- **Recommended Surgical Fix**:
```python
stmt_session = select(WorkSession).with_for_update().filter_by(driver_id=payload.driver_id, end_time=None)
active_session = (await db.execute(stmt_session)).scalar_one_or_none()
```

---

## Finding #8

- **Severity**: Medium
- **Flaw Category**: Race Condition / Lost Update
- **Exact File & Line Number**: `wa_backend/api/dispatch.py`, line 1895 (function `update_route_status`, driver-switch reconciliation branch)
- **Current Flawed Code**:
```python
stmt_vloads = select(VehicleLoad).filter(VehicleLoad.vehicle_id == route.vehicle_id, VehicleLoad.product_variant_id.in_(var_ids))
v_loads = (await db.execute(stmt_vloads)).scalars().all()
v_load_map = {vl.product_variant_id: vl for vl in v_loads}
...
# later in the same block:
if v_load: v_load.quantity = actual_cartons
else: db.add(VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=live_inv.product_variant_id, quantity=actual_cartons))
```
- **Impact Analysis**: Every other place in this file that reads `VehicleLoad` immediately before mutating it uses `.with_for_update()` (e.g. lines 778, 1219, 1964) explicitly to guard against "Lost Update" — the comment pattern "درع الفولاذي: قفل حمولة السيارة لمنع المشرفين من التعديل المزدوج" appears repeatedly elsewhere in the file. This one instance omits the lock. A concurrent `adjust_route_inventory` call on the same vehicle (which *does* take `with_for_update()`) will not be blocked by this unlocked read, so this driver-switch code can read a pre-change quantity, then blindly overwrite `v_load.quantity` at flush time, discarding the concurrent adjustment.
- **Recommended Surgical Fix**:
```python
stmt_vloads = select(VehicleLoad).with_for_update().filter(VehicleLoad.vehicle_id == route.vehicle_id, VehicleLoad.product_variant_id.in_(var_ids))
v_loads = (await db.execute(stmt_vloads)).scalars().all()
```

---

## Finding #9

- **Severity**: Medium
- **Flaw Category**: Missing Validation / Asymmetric Cascade (Incomplete Business Logic)
- **Exact File & Line Number**: `wa_backend/api/dispatch.py`, lines 2445–2469 (function `restore_zone`), contrasted with lines 2352–2364 (function `archive_zone`)
- **Current Flawed Code**:
```python
# archive_zone (2352-2364): cascades to shops
stmt_archive_shops = update(Shop).where(Shop.zone_id == zone_id).values(is_archived=True)
await db.execute(stmt_archive_shops)
...
# restore_zone (2445-2469): does NOT cascade back
zone = await db.get(Zone, zone_id)
if not zone:
    raise HTTPException(status_code=404, detail="المنطقة غير موجودة")
if getattr(zone, 'is_active', False):
    return {"message": "المنطقة نشطة بالفعل"}
try:
    zone.is_active = True
    await db.commit()
    return {"message": "تم استعادة المنطقة بنجاح"}
```
- **Impact Analysis**: `archive_zone` automatically archives every `Shop` in the zone as part of a single atomic cascade. `restore_zone` never reverses this — it only flips `Zone.is_active`. Every shop that was auto-archived stays `is_archived = True` forever, invisible to `get_dispatch_shops` (which filters `is_archived == False`), unless an admin manually restores each shop one-by-one via `bulk_update_shops`. A "restored" zone therefore appears in the active zone list but has **zero usable shops**, contradicting the intuitive (and only documented) meaning of "restore."
- **Recommended Surgical Fix**:
```python
try:
    zone.is_active = True
    await db.execute(update(Shop).where(Shop.zone_id == zone_id).values(is_archived=False))
    await db.commit()
    return {"message": "تم استعادة المنطقة وجميع المحلات التابعة لها بنجاح"}
```

---

## Finding #10

- **Severity**: Medium
- **Flaw Category**: Missing Validation
- **Exact File & Line Number**: `wa_backend/api/dispatch.py`, lines 424–427 (function `settle_session`)
- **Current Flawed Code**:
```python
jard_map = {}
for item in payload.inventory_jard:
    pid = item.product_id
    jard_map[pid] = jard_map.get(pid, 0) + item.actual
```
- **Impact Analysis**: `item.actual` is accepted with no non-negative check. A negative value flows straight into `actual_qty` → `inv_record.current_remaining_quantity = actual_qty` (line 545), which will violate `chk_positive_inventory` (Business Rule §1.1) at commit time, aborting the entire settlement with a raw, unhandled `IntegrityError` surfaced as a generic `500` — a poor failure mode for the single most consequential, one-time-only endpoint in the system (Business Rule §5.1).
- **Recommended Surgical Fix**:
```python
jard_map = {}
for item in payload.inventory_jard:
    if item.actual < 0:
        await db.rollback()
        raise HTTPException(status_code=400, detail="مرفوض: كمية الجرد الفعلي لا يمكن أن تكون سالبة.")
    pid = item.product_id
    jard_map[pid] = jard_map.get(pid, 0) + item.actual
```

---

## Finding #11

- **Severity**: Medium
- **Flaw Category**: Flawed Validation Formula
- **Exact File & Line Number**: `wa_backend/api/dispatch.py`, lines 891–898 (function `dispatch_route`, mid-day handshake branch)
- **Current Flawed Code**:
```python
delta_packs = new_actual_qty_packs - (current_live_packs + existing_pending_packs)

# +++ درع الميدان: فحص رصيد المندوب قبل السحب (طلب البوت المفيد الوحيد هنا) +++
if delta_packs < 0:
    if current_live_packs + delta_packs < 0:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"مرفوض: رصيد المندوب الحالي من ({variant.variant_name}) لا يكفي لتسجيل هذا السحب.")
```
- **Impact Analysis**: `existing_pending_packs` here sums **all** pending transfers regardless of sign (unlike the equivalent, correctly-scoped check in `adjust_route_inventory` at lines 1233–1245, which filters only negative/withdrawal transfers). Substituting the `delta_packs` formula into the guard reduces the check to `new_actual_qty_packs - existing_pending_packs < 0`, which is **not equivalent** to "does the driver's current live balance cover this new withdrawal." When a product has an existing **positive** pending transfer in flight (an unconfirmed addition), this formula can reject an otherwise perfectly valid dispatch adjustment — a false-positive business rejection that blocks a legitimate admin operation, inconsistent with the more correct sign-filtered logic used elsewhere in the same file for the identical business scenario.
- **Recommended Surgical Fix**:
```python
# Only pending *withdrawals* reduce what is safely available for a further withdrawal.
pending_withdrawals_only = min(existing_pending_packs, 0)
if delta_packs < 0:
    if current_live_packs + pending_withdrawals_only + delta_packs < 0:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"مرفوض: رصيد المندوب الحالي من ({variant.variant_name}) لا يكفي لتسجيل هذا السحب.")
```

---

## Finding #12

- **Severity**: Low
- **Flaw Category**: Missing Validation (Falsy-Zero Mishandling)
- **Exact File & Line Number**: `wa_backend/api/dispatch.py`, lines 2916–2921 (function `bulk_import_shops`)
- **Current Flawed Code**:
```python
try:
    raw_seq = str(s.sequence or '999').strip()
    # +++ هندسة البايثون: تحويل النص لـ float لامتصاص (1.0) ثم لـ int لجعله رقماً صحيحاً (1) +++
    safe_seq = int(float(raw_seq)) 
except Exception:
    safe_seq = 999
```
- **Impact Analysis**: `s.sequence or '999'` treats a legitimate `sequence == 0` as falsy in Python, silently replacing an admin's intended "first position" (0) with the default fallback (999), pushing that shop to the very end of the visit order instead of the front. This is precisely the same class of bug the file explicitly guards against elsewhere (see the comment at line ~1591: "سحق لغم الصفر الجغرافي: 0.0 يعتبر Falsy... يجب فحصه كـ is not None"), but the guard was not applied here.
- **Recommended Surgical Fix**:
```python
try:
    raw_seq = str(s.sequence if s.sequence is not None else '999').strip()
    safe_seq = int(float(raw_seq)) 
except Exception:
    safe_seq = 999
```

---

## Finding #13

- **Severity**: Low
- **Flaw Category**: Inconsistent Error Handling (Connection/Lock Leak Risk)
- **Exact File & Line Number**: `wa_backend/api/dispatch.py`, lines 734–742 (function `dispatch_route`)
- **Current Flawed Code**:
```python
stmt_wh_lock = select(SystemSetting).filter_by(setting_key='warehouse_status')
lock_setting = (await db.execute(stmt_wh_lock)).scalar_one_or_none()
if lock_setting and lock_setting.setting_value == 'AUDIT_LOCK':
    raise HTTPException(status_code=403, detail="مرفوض: المستودع مقفل حالياً لغايات الجرد (Stocktake). يرجى فتح المستودع أولاً.")

stmt_driver_lock = select(Driver).with_for_update().filter_by(id=payload.driver_id)
driver_lock = (await db.execute(stmt_driver_lock)).scalar_one_or_none()
if not driver_lock:
    raise HTTPException(status_code=404, detail="المندوب غير موجود.")
```
- **Impact Analysis**: Every subsequent check in this same function (lines 744–757) calls `await db.rollback()` immediately before raising, and the codebase explicitly documents this as closing a "Connection Leak" vulnerability (see identical comments in `authorize_session`, line 50). These first two checks in `dispatch_route` — including one that has already taken a row lock via `with_for_update()` on the `Driver` table — omit the rollback, inconsistent with the pattern the rest of the file (and this very function) considers mandatory.
- **Recommended Surgical Fix**:
```python
if lock_setting and lock_setting.setting_value == 'AUDIT_LOCK':
    await db.rollback()
    raise HTTPException(status_code=403, detail="مرفوض: المستودع مقفل حالياً لغايات الجرد (Stocktake). يرجى فتح المستودع أولاً.")

stmt_driver_lock = select(Driver).with_for_update().filter_by(id=payload.driver_id)
driver_lock = (await db.execute(stmt_driver_lock)).scalar_one_or_none()
if not driver_lock:
    await db.rollback()
    raise HTTPException(status_code=404, detail="المندوب غير موجود.")
```

---

## Finding #14

- **Severity**: Low
- **Flaw Category**: Missing Validation (Silent No-Op)
- **Exact File & Line Number**: `wa_backend/api/dispatch.py`, line 1955 (function `update_route_status`)
- **Current Flawed Code**:
```python
if payload.inventory is not None and route.vehicle_id:
    ...
```
- **Impact Analysis**: If an admin submits an inventory adjustment (`payload.inventory`) for a route that has no `vehicle_id` assigned yet, the `and route.vehicle_id` guard causes the entire block to be skipped **silently** — the endpoint still returns `{"message": "تم تحديث خط السير بنجاح"}` (success) even though the requested inventory change was never applied. This is a data-loss-by-silence bug: the caller has no way to know their inventory payload was discarded.
- **Recommended Surgical Fix**:
```python
if payload.inventory is not None:
    if not route.vehicle_id:
        await db.rollback()
        raise HTTPException(status_code=400, detail="مرفوض: يجب تعيين سيارة لخط السير أولاً قبل تعديل الحمولة.")
    ...
```

---

## Finding #15

- **Severity**: Low
- **Flaw Category**: Race Condition (TOCTOU)
- **Exact File & Line Number**: `wa_backend/api/dispatch.py`, lines 2286–2292 (function `add_zone`) and lines 2401–2403 (function `update_zone`)
- **Current Flawed Code**:
```python
# add_zone
stmt_existing = select(Zone).filter_by(name=name)
existing_zone = (await db.execute(stmt_existing)).scalars().first()
if existing_zone:
    ...
    raise HTTPException(status_code=409, detail="المنطقة موجودة ونشطة مسبقاً")
```
- **Impact Analysis**: The uniqueness check is a plain, unlocked `SELECT`. Two concurrent requests to create (or rename) a zone with the same name can both pass this check before either commits, resulting in two `Zone` rows with an identical name unless an underlying unique DB index enforces it independently (not confirmed in this file).
- **Recommended Surgical Fix**:
```python
stmt_existing = select(Zone).with_for_update().filter_by(name=name)
existing_zone = (await db.execute(stmt_existing)).scalars().first()
```
(Note: a true fix requires a DB-level `UNIQUE` constraint on `Zone.name`, which is outside this file's scope to verify/add.)

---

## Summary Table

| # | Severity | Category | Function |
|---|----------|----------|----------|
| 1 | Critical | Missing Validation / Phantom Stock | `update_route_status` |
| 2 | High | Deadlock Risk / Lock Ordering | `settle_session` |
| 3 | High | Logic Bug (dict overwrite) | `add_shortages` |
| 4 | Medium | Missing Validation → DB crash | `dispatch_route` |
| 5 | Medium | Data Integrity / Reporting | `settle_session` |
| 6 | Medium | Race Condition (stale read) | `settle_session` |
| 7 | Medium | Race Condition (TOCTOU) | `dispatch_route` |
| 8 | Medium | Race Condition (lost update) | `update_route_status` |
| 9 | Medium | Asymmetric Cascade | `restore_zone` / `archive_zone` |
| 10 | Medium | Missing Validation | `settle_session` |
| 11 | Medium | Flawed Validation Formula | `dispatch_route` |
| 12 | Low | Falsy-Zero Bug | `bulk_import_shops` |
| 13 | Low | Inconsistent Error Handling | `dispatch_route` |
| 14 | Low | Silent No-Op | `update_route_status` |
| 15 | Low | Race Condition (TOCTOU) | `add_zone` / `update_zone` |
