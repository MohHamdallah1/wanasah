### RAW MARKDOWN — Backend Module Audit: `wa_backend/api/warehouse.py`

```markdown
# Audit Report — wa_backend/api/warehouse.py
Scope: Phase 6.1 Backend Module Audit (read-only). Cross-referenced against `.ai-review/04_BUSINESS_RULES.md`.

---

## Finding 1

- **Severity**: Critical
- **Flaw Category**: Race Condition (TOCTOU) / Business Rule Violation (Rule 1.5 — invoice idempotency)
- **Exact File & Line Number**: `wa_backend/api/warehouse.py`, lines 57–67 (`warehouse_inbound`)
- **Current Flawed Code**:
```python
    if reference_id and reference_id.strip() and reference_id != "بدون فاتورة":
        stmt_ref = select(WarehouseLedger.id).filter(
            WarehouseLedger.transaction_type.in_(['INBOUND_SUPPLIER', 'INBOUND_CORRECTION']), 
            func.lower(func.trim(WarehouseLedger.reference_id)) == func.lower(reference_id.strip())
        )
        existing_ref = (await db.execute(stmt_ref)).first()
        
        if existing_ref:
            raise HTTPException(status_code=409, detail=f"مرفوض: رقم الفاتورة '{reference_id}' مسجل مسبقاً في النظام. يرجى التحقق لمنع تكرار إدخال البضاعة.")
```
- **Impact Analysis**: The duplicate-invoice check is a plain unlocked `SELECT`. Two concurrent `POST /warehouse/inbound` calls with the same `reference_id` (double-click, network retry, or two admins) can both read "not found" before either commits, and both proceed to insert. There is no unique DB constraint backing this rule (per `04_BUSINESS_RULES.md` §1.5 the rule is enforced only "in application logic"). Result: the same supplier invoice is booked twice — the exact fraud/duplication scenario this "financial shield" comment explicitly claims to prevent — silently inflating `available_quantity_packs` and corrupting the audit trail.
- **Recommended Surgical Fix**:
```python
    if reference_id and reference_id.strip() and reference_id != "بدون فاتورة":
        normalized_ref = reference_id.strip().lower()
        # +++ قفل استشاري ذري (Postgres advisory lock) يغلق نافذة TOCTOU لنفس رقم الفاتورة +++
        await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(normalized_ref))))
        stmt_ref = select(WarehouseLedger.id).filter(
            WarehouseLedger.transaction_type.in_(['INBOUND_SUPPLIER', 'INBOUND_CORRECTION']),
            func.lower(func.trim(WarehouseLedger.reference_id)) == normalized_ref
        )
        existing_ref = (await db.execute(stmt_ref)).first()
        if existing_ref:
            raise HTTPException(status_code=409, detail=f"مرفوض: رقم الفاتورة '{reference_id}' مسجل مسبقاً في النظام. يرجى التحقق لمنع تكرار إدخال البضاعة.")
```
`pg_advisory_xact_lock` serializes any concurrent request sharing the same normalized invoice number for the duration of the transaction and is auto-released on commit/rollback — no schema migration required.

---

## Finding 2

- **Severity**: High
- **Flaw Category**: Race Condition / Transaction Isolation (stale read used for financial delta)
- **Exact File & Line Number**: `wa_backend/api/warehouse.py`, lines 611–630 (`adjust_warehouse_entry`)
- **Current Flawed Code**:
```python
        ref_id = original_entry.reference_id
        if ref_id and ref_id.strip() and ref_id != "بدون فاتورة":
            stmt_sum = select(func.sum(WarehouseLedger.quantity_packs)).filter(
                WarehouseLedger.reference_id == ref_id,
                WarehouseLedger.product_variant_id == original_entry.product_variant_id,
                WarehouseLedger.transaction_type.in_(['INBOUND_SUPPLIER', 'INBOUND_CORRECTION'])
            )
            current_invoice_total_packs = (await db.execute(stmt_sum)).scalar() or 0
        else:
            current_invoice_total_packs = original_entry.quantity_packs

        delta = int(payload.new_total_packs) - int(current_invoice_total_packs)
        if delta == 0:
            return {"message": "لا يوجد تغيير في الكمية. الصافي الحالي مطابق لما أدخلته."}

        stmt_variant = select(ProductVariant).with_for_update().filter_by(id=original_entry.product_variant_id)
        variant = (await db.execute(stmt_variant)).scalar_one_or_none()
```
- **Impact Analysis**: `current_invoice_total_packs` is read with **no lock** and BEFORE any row is locked. Two concurrent corrections on the same invoice/product both read the same stale total, each computes its own `delta` against that stale baseline, and both deltas get applied sequentially once the (later-acquired) `MainWarehouse` lock is obtained one after another. The final ledger sum silently diverges from what either admin intended (classic lost-update), corrupting the append-only ledger's reconstructed invoice totals — directly undermining Rule 1.6 ("Ledger integrity").
- **Recommended Surgical Fix**: Acquire the `MainWarehouse` lock **first**, then compute the invoice sum, so any concurrent adjustment on the same product is serialized before its read:
```python
        stmt_wh = select(MainWarehouse).with_for_update().filter_by(product_variant_id=original_entry.product_variant_id)
        wh_record = (await db.execute(stmt_wh)).scalar_one_or_none()
        if not wh_record:
            await db.rollback()
            raise HTTPException(status_code=404, detail="سجل المستودع غير موجود.")

        ref_id = original_entry.reference_id
        if ref_id and ref_id.strip() and ref_id != "بدون فاتورة":
            stmt_sum = select(func.sum(WarehouseLedger.quantity_packs)).filter(
                WarehouseLedger.reference_id == ref_id,
                WarehouseLedger.product_variant_id == original_entry.product_variant_id,
                WarehouseLedger.transaction_type.in_(['INBOUND_SUPPLIER', 'INBOUND_CORRECTION'])
            )
            current_invoice_total_packs = (await db.execute(stmt_sum)).scalar() or 0
        else:
            current_invoice_total_packs = original_entry.quantity_packs

        delta = int(payload.new_total_packs) - int(current_invoice_total_packs)
        if delta == 0:
            return {"message": "لا يوجد تغيير في الكمية. الصافي الحالي مطابق لما أدخلته."}
```
(Note: this reorder also renders the separate `ProductVariant` lock in Finding 3 unnecessary — see below.)

---

## Finding 3

- **Severity**: Medium
- **Flaw Category**: Deadlock Risk / Unnecessary Lock Acquisition
- **Exact File & Line Number**: `wa_backend/api/warehouse.py`, line 629 (`adjust_warehouse_entry`)
- **Current Flawed Code**:
```python
        stmt_variant = select(ProductVariant).with_for_update().filter_by(id=original_entry.product_variant_id)
        variant = (await db.execute(stmt_variant)).scalar_one_or_none()
```
- **Impact Analysis**: No field on `ProductVariant` is ever written in this function — `variant` is only used to reference `.id` (already known from `original_entry.product_variant_id`). Taking an exclusive `FOR UPDATE` lock on a row that is never mutated needlessly blocks any other concurrent transaction that also needs to lock/read that same `ProductVariant` row (e.g., a `respond_to_transfer` check on `is_active`), widening lock contention and deadlock surface for no functional benefit, and outside the documented lock hierarchy of Rule 1.8.
- **Recommended Surgical Fix**:
```python
        stmt_variant = select(ProductVariant).filter_by(id=original_entry.product_variant_id)
        variant = (await db.execute(stmt_variant)).scalar_one_or_none()
```
(Drop `.with_for_update()` — a plain read is sufficient since only `MainWarehouse` is mutated.)

---

## Finding 4

- **Severity**: Medium
- **Flaw Category**: Missing Validation / Business Rule Violation
- **Exact File & Line Number**: `wa_backend/api/warehouse.py`, line 623 (`adjust_warehouse_entry`)
- **Current Flawed Code**:
```python
        delta = int(payload.new_total_packs) - int(current_invoice_total_packs)
```
- **Impact Analysis**: There is no check that `payload.new_total_packs >= 0`. An admin (or a compromised dashboard session) can submit a negative "new total" for a supplier invoice. While `wh_record.available_quantity_packs` itself is protected from going negative (line 642), the *logical invoice total* recorded in the ledger can end up negative — a physically meaningless state for a supplier receipt — corrupting the audit trail that Rule 1.6 depends on for balance reconstruction.
- **Recommended Surgical Fix**:
```python
        if payload.new_total_packs < 0:
            raise HTTPException(status_code=400, detail="مرفوض: لا يمكن أن يكون إجمالي الفاتورة الجديد رقماً سالباً.")
        delta = int(payload.new_total_packs) - int(current_invoice_total_packs)
```

---

## Finding 5

- **Severity**: Low
- **Flaw Category**: Missing Validation
- **Exact File & Line Number**: `wa_backend/api/warehouse.py`, lines 408–409 and 417 (`get_warehouse_ledger`)
- **Current Flawed Code**:
```python
    skip: int = 0, # +++ البداية (Pagination) +++
    limit: int = 500, # +++ عدد السجلات للـ Page الواحدة +++
    ...
    safe_limit = min(limit, 1000) # +++ الدرع الفولاذي: حماية الـ RAM من الانفجار بحد أقصى إجباري +++
```
- **Impact Analysis**: `min(limit, 1000)` only caps the upper bound; negative `limit` or `skip` values (e.g. `?limit=-5` or `?skip=-1`) are not rejected and are passed straight to `.offset()/.limit()`, producing an unhandled SQL error caught only by the generic `except Exception` (500 instead of a clean 400).
- **Recommended Surgical Fix**:
```python
from fastapi import Query
...
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
    ...
    safe_limit = limit
```

---

## Finding 6

- **Severity**: Low
- **Flaw Category**: Missing Error Handling / Robustness
- **Exact File & Line Number**: `wa_backend/api/warehouse.py`, lines 592–600 (`adjust_warehouse_entry`)
- **Current Flawed Code**:
```python
    if not password_ok:
        audit = SystemAuditLog(
            admin_id=current_admin.id, target_id=f"Ledger_{entry_id}",
            action_type='UNAUTHORIZED_ADJUSTMENT', old_value='Wrong Password', new_value='Rejected'
        )
        db.add(audit)
        await db.commit()
        raise HTTPException(status_code=403, detail="كلمة المرور غير صحيحة. تم رفض العملية وتوثيق المحاولة.")
```
- **Impact Analysis**: This block sits outside the surrounding `try/except`. If the audit-log `commit()` itself fails (DB hiccup), the handler raises an unlogged, unhandled exception instead of the intended clean 403 — the very moment a suspicious/unauthorized attempt is happening is exactly when a silent framework-level 500 is least desirable.
- **Recommended Surgical Fix**:
```python
    if not password_ok:
        try:
            audit = SystemAuditLog(
                admin_id=current_admin.id, target_id=f"Ledger_{entry_id}",
                action_type='UNAUTHORIZED_ADJUSTMENT', old_value='Wrong Password', new_value='Rejected'
            )
            db.add(audit)
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"فشل تسجيل محاولة التلاعب: {str(e)}", exc_info=True)
        raise HTTPException(status_code=403, detail="كلمة المرور غير صحيحة. تم رفض العملية وتوثيق المحاولة.")
```

---

## Finding 7

- **Severity**: Medium
- **Flaw Category**: Architectural Flaw (Fragile Hardcoded Cross-Module Assumption)
- **Exact File & Line Number**: `wa_backend/api/warehouse.py`, lines 432–437 (`get_warehouse_ledger`)
- **Current Flawed Code**:
```python
            if log.transaction_type in ['DISPATCH_LOAD', 'HANDSHAKE_RESERVE']:
                bal_before = log.balance_after_packs + log.quantity_packs
            elif log.transaction_type == 'HANDSHAKE_COMMIT':
                bal_before = log.balance_after_packs
            else:
                bal_before = log.balance_after_packs - log.quantity_packs
```
- **Impact Analysis**: This reconstructs `balance_before` by guessing the sign convention per `transaction_type` string, most of which (`DISPATCH_LOAD`, `HANDSHAKE_RESERVE`, `HANDSHAKE_COMMIT`) are written by `api/dispatch.py`/`api/driver.py`, not this file. Any new transaction type, or any change to how `quantity_packs` sign is stored elsewhere, silently produces a **wrong** `balance_before` here with no error — a dangerous failure mode for a financial reconciliation display that admins rely on to validate Rule 1.6/5.3 audit trails (wrong numbers, no exception).
- **Recommended Surgical Fix**: Whitelist known types explicitly and fail loudly/visibly on anything unrecognized instead of silently defaulting:
```python
            DECREASE_TYPES = {'DISPATCH_LOAD', 'HANDSHAKE_RESERVE'}
            NEUTRAL_TYPES = {'HANDSHAKE_COMMIT'}
            INCREASE_TYPES = {'INBOUND_SUPPLIER', 'INBOUND_CORRECTION', 'AUDIT_ADJUSTMENT',
                               'DISPATCH_UNLOAD', 'DISPATCH_UNLOAD_FALLBACK', 'VEHICLE_ROLLOVER',
                               'END_DAY_CLEARANCE'}
            if log.transaction_type in DECREASE_TYPES:
                bal_before = log.balance_after_packs + log.quantity_packs
            elif log.transaction_type in NEUTRAL_TYPES:
                bal_before = log.balance_after_packs
            elif log.transaction_type in INCREASE_TYPES:
                bal_before = log.balance_after_packs - log.quantity_packs
            else:
                bal_before = None
                logger.warning(f"Unknown ledger transaction_type '{log.transaction_type}' (entry id={log.id}) — balance_before could not be safely reconstructed.")
```
```

---