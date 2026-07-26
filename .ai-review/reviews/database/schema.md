# Database Schema Audit Report — `wa_backend/models.py`

> Phase 9 Deliverable — Database & Data Layer Audit  
> Sources analyzed: `wa_backend/models.py` cross-referenced against `.ai-review/04_BUSINESS_RULES.md`  
> Date: 2026-07-24

---

## Executive Summary

| Severity | Count |
|----------|-------|
| Critical | 1 |
| High     | 4 |
| Medium   | 5 |
| Low      | 3 |
| **Total** | **13** |

---

## 🔴 Critical

### C-01: Missing `text` Import — Runtime `NameError` on Module Load

- **Severity**: **Critical**
- **Flaw Category**: Missing Import (Runtime Crash)
- **Exact Table & Line Number**: `DispatchRoute` — `models.py`, line 1 (import) vs. lines 252–254 (usage)
- **Current Flawed Code**:
  ```python
  # Line 1 — text is NOT imported:
  from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Numeric, Float, Text, ForeignKey, CheckConstraint, UniqueConstraint, Index, MetaData

  # Lines 252–254 — text() is called:
  Index('uq_active_route_per_driver', 'driver_id', unique=True, postgresql_where=text("status = 'active'")),
  Index('uq_active_route_per_vehicle', 'vehicle_id', unique=True, postgresql_where=text("status = 'active'")),
  Index('uq_active_route_per_zone', 'zone_id', unique=True, postgresql_where=text("status = 'active'")),
  ```
- **Impact Analysis**: `text` is referenced inside `__table_args__` at class-definition time. When Python evaluates the `DispatchRoute` class body, `text` is an unresolved name → immediate `NameError` at import, crashing the entire application before any request is served. This also means all three partial unique indexes guarding route concurrency **do not exist** in any deployed database, fully bypassing the race-condition protection described in Business Rule 2.1.
- **Recommended Surgical Fix**: Add `text` to the import line:
  ```python
  from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Numeric, Float, Text, ForeignKey, CheckConstraint, UniqueConstraint, Index, MetaData, text
  ```

---

## 🟠 High

### H-01: Partial Unique Indexes Only Cover `active` — Missing `waiting` and `postponed` Statuses

- **Severity**: **High**
- **Flaw Category**: Missing Index / Constraint Gap (Race Condition)
- **Exact Table & Line Number**: `DispatchRoute` — `models.py`, lines 251–255; `.ai-review/04_BUSINESS_RULES.md` §2.1 lines 62–65
- **Current Flawed Code**:
  ```python
  __table_args__ = (
      Index('uq_active_route_per_driver', 'driver_id', unique=True, postgresql_where=text("status = 'active'")),
      Index('uq_active_route_per_vehicle', 'vehicle_id', unique=True, postgresql_where=text("status = 'active'")),
      Index('uq_active_route_per_zone', 'zone_id', unique=True, postgresql_where=text("status = 'active'")),
  )
  ```
- **Business Rule Violated**: BR §2.1 explicitly states:
  - "A **zone** can have at most one route in `{active, waiting, postponed}` status"
  - "A **driver** can have at most one route in `{active, waiting}` status"
  - "A **vehicle** can have at most one route in `{active, waiting}` status"
- **Impact Analysis**: The three partial unique indexes only constrain `status = 'active'`. A zone, driver, or vehicle can accumulate **unlimited concurrent routes** in `waiting` or `postponed` statuses—the database will permit all of them. The API-layer checks referenced in BR §2.1 ("enforced both defensively at the API layer … and structurally in the database") are therefore **absent at the database level** for these two statuses, opening a race-condition window where two concurrent API calls can both pass the application-layer check before either commits, producing multiple `waiting`/`postponed` rows for the same entity.
- **Recommended Surgical Fix**: Widen the partial unique indexes to cover all statuses that should be mutually exclusive:
  ```python
  __table_args__ = (
      Index('uq_active_route_per_driver', 'driver_id', unique=True,
            postgresql_where=text("status IN ('active', 'waiting')")),
      Index('uq_active_route_per_vehicle', 'vehicle_id', unique=True,
            postgresql_where=text("status IN ('active', 'waiting')")),
      Index('uq_active_route_per_zone', 'zone_id', unique=True,
            postgresql_where=text("status IN ('active', 'waiting', 'postponed')")),
  )
  ```

---

### H-02: `Zone.governorate_id` FK Lacks `ondelete` — Orphan-Row or Crash on Governorate Deletion

- **Severity**: **High**
- **Flaw Category**: Missing `ondelete` / Referential Integrity Gap
- **Exact Table & Line Number**: `Zone` — `models.py`, line 64
- **Current Flawed Code**:
  ```python
  governorate_id = Column(Integer, ForeignKey('governorates.id'), nullable=True)
  ```
- **Impact Analysis**: The FK on `governorate_id` has no `ondelete` clause and the column is `nullable=True`. If an admin deletes a `Governorate` row, PostgreSQL will **raise an `IntegrityError` and roll back the transaction** because child `Zone` rows still reference the deleted parent. This blocks any governorate cleanup (e.g., geo-restructuring) entirely. Compare with `Shop.zone_id` (line 229) which correctly specifies `ondelete='SET NULL'`. The hierarchy is: `Country → Governorate → Zone → Shop`. The middle link (`Governorate → Zone`) is the only one missing the cascade strategy, creating a brittle deletion path where either: (a) an admin must manually nullify all zone FK references first, or (b) the deletion crashes.
- **Recommended Surgical Fix**: Mirror the same pattern used on `Shop.zone_id`:
  ```python
  governorate_id = Column(Integer, ForeignKey('governorates.id', ondelete='SET NULL'), nullable=True)
  ```

---

### H-03: `ShortageRequest.quantity` Missing `CHECK >= 0` — Negative-Quantity Injection Vector

- **Severity**: **High**
- **Flaw Category**: Missing CheckConstraint
- **Exact Table & Line Number**: `ShortageRequest` — `models.py`, line 379
- **Current Flawed Code**:
  ```python
  quantity = Column(Integer, nullable=False)
  ```
- **Impact Analysis**: Every other quantity column in the entire schema carries an explicit `CheckConstraint('… >= 0', …)` guard (see BR §1.1, lines 16–19 for the full inventory: `VehicleLoad.quantity`, `SessionInventory.current_remaining_quantity`, `VisitItem.quantity`/`packs_quantity`/`bonus_quantity`/`sample_quantity`/`sample_packs_quantity`, `VisitReturn.quantity`/`packs_quantity`, `DamagedItemLog.quantity_packs`, `MainWarehouse.available_quantity_packs`/`reserved_quantity_packs`). `ShortageRequest.quantity` is the **sole exception** — a negative number can be inserted directly via raw SQL or a compromised client, polluting shortage reports, inventory reconciliation, and any downstream aggregate that sums this field. This is inconsistent with the "negative-stock prevention" invariant documented across BR §1.3.
- **Recommended Surgical Fix**: Add the standard guard, consistent with every other quantity column:
  ```python
  quantity = Column(Integer, CheckConstraint('quantity >= 0', name='chk_shortage_qty'), nullable=False)
  ```

---

### H-04: `WorkSession` Missing Composite Index for "Pending Unsettled Session" Query

- **Severity**: **High**
- **Flaw Category**: Missing Index (N+1 / Full-Table-Scan Risk)
- **Exact Table & Line Number**: `WorkSession` — `models.py`, lines 176–193; BR §2.3 lines 76–78
- **Current Flawed Code**:
  ```python
  # Existing indexes (lines 179, 183):
  driver_id    = Column(Integer, ForeignKey('drivers.id'), nullable=False, index=True)   # single-col
  session_date = Column(Date, ..., index=True)                                            # single-col
  is_settled   = Column(Boolean, ..., index=True)                                         # single-col
  end_time     = Column(DateTime, nullable=True, index=True)                              # single-col
  ```
- **Business Rule Violated**: BR §2.3 line 76: "A driver **cannot start** a new work session while they have a previous session that has ended (`end_time` set) but is **not yet settled**" — this check runs on **every session-start**. The query is equivalent to:
  ```sql
  SELECT 1 FROM work_sessions
  WHERE driver_id = ? AND end_time IS NOT NULL AND is_settled = FALSE
  LIMIT 1;
  ```
- **Impact Analysis**: With only single-column indexes, PostgreSQL must choose one index (likely `driver_id`) and then perform an **index-scan + filter** on the remaining two predicates. As `work_sessions` grows (one row per driver per day = hundreds of thousands of rows over months), the filter phase scans every session row for that driver to find an unsettled one. While a single driver's history may be modest, the missing composite index forces the planner into suboptimal bitmap scans when multiple drivers start sessions concurrently during morning rush. A composite `(driver_id, is_settled, end_time)` index lets PostgreSQL jump directly to the first unsettled ended session in O(log n) time.
- **Recommended Surgical Fix**: Add a covering composite index:
  ```python
  __table_args__ = (
      Index('ix_ws_driver_unsettled', 'driver_id', 'is_settled', 'end_time'),
  )
  ```
  Alternatively, add it as a `__table_args__` tuple on `WorkSession` alongside the existing column-level indexes.

---

## 🟡 Medium

### M-01: `Governorate` Missing Unique Constraint on `(name, country_id)`

- **Severity**: **Medium**
- **Flaw Category**: Missing UniqueConstraint (Data Quality)
- **Exact Table & Line Number**: `Governorate` — `models.py`, lines 46–52
- **Current Flawed Code**:
  ```python
  class Governorate(Base):
      __tablename__ = 'governorates'
      id         = Column(Integer, primary_key=True)
      name       = Column(String(100), nullable=False)
      country_id = Column(Integer, ForeignKey('countries.id'), nullable=False)
  ```
- **Impact Analysis**: The same governorate name can be inserted multiple times under the same country (e.g., two rows with `name='Amman', country_id=1`). There is no database-level guard preventing this. The API may or may not deduplicate — but the schema itself is permissive, making the application the sole gatekeeper. If duplicates creep in (bulk import, migration, direct DB access), `Zone` rows referencing ambiguous governorate IDs become semantically broken.
- **Recommended Surgical Fix**:
  ```python
  __table_args__ = (
      UniqueConstraint('name', 'country_id', name='uq_governorate_name_per_country'),
  )
  ```

---

### M-02: `Zone` Missing Unique Constraint on `(name, governorate_id)`

- **Severity**: **Medium**
- **Flaw Category**: Missing UniqueConstraint (Data Quality)
- **Exact Table & Line Number**: `Zone` — `models.py`, lines 55–76
- **Current Flawed Code**:
  ```python
  class Zone(Base):
      __tablename__ = 'zones'
      id             = Column(Integer, primary_key=True)
      name           = Column(String(100), nullable=False)
      governorate_id = Column(Integer, ForeignKey('governorates.id'), nullable=True)  # H-02 above
  ```
- **Impact Analysis**: Identical logic to M-01 — two zones with the same name under the same governorate are permitted at the schema level. Zone names are used in dispatch route assignment (BR §2.5: "A driver may only record a sale for a shop inside the zone of their currently active route"), and duplicate zone names under the same governorate would make territory enforcement ambiguous in any UI dropdown or report.
- **Recommended Surgical Fix**:
  ```python
  __table_args__ = (
      UniqueConstraint('name', 'governorate_id', name='uq_zone_name_per_governorate'),
  )
  ```

---

### M-03: Missing Composite Index on `Visit(shop_id, visit_timestamp)` for Shop History Queries

- **Severity**: **Medium**
- **Flaw Category**: Missing Index (N+1 Risk)
- **Exact Table & Line Number**: `Visit` — `models.py`, lines 275–313
- **Current Flawed Code**:
  ```python
  # Existing: two separate single-column indexes
  shop_id         = Column(..., index=True)   # line 284
  visit_timestamp = Column(..., index=True)   # line 286
  ```
- **Impact Analysis**: The dashboard and mobile client frequently query "all visits for shop X ordered by time DESC." With only single-column indexes, PostgreSQL must either: (a) use `shop_id` index + sort (heap-scan the timestamp), or (b) bitmap-AND both indexes. A composite `(shop_id, visit_timestamp)` index serves this query with a single index-only scan. As the `visits` table grows to millions of rows across all shops, the sort overhead becomes measurable on every shop-detail page load.
- **Recommended Surgical Fix**:
  ```python
  __table_args__ = (
      Index('ix_visit_shop_timestamp', 'shop_id', 'visit_timestamp'),
  )
  ```

---

### M-04: Missing Composite Index on `Visit(work_session_id, outcome)` for Settlement Queries

- **Severity**: **Medium**
- **Flaw Category**: Missing Index (N+1 Risk)
- **Exact Table & Line Number**: `Visit` — `models.py`, lines 275–313; BR §5.2 line 167
- **Current Flawed Code**:
  ```python
  work_session_id = Column(..., index=True)   # line 285 — single col
  outcome         = Column(..., index=True)   # line 288 — single col
  ```
- **Business Rule Context**: BR §5.2 line 167: `expected_cash = sum(cash_collected) + sum(debt_paid)` across all `Completed` visits in the session — this aggregation runs on every settlement.
- **Impact Analysis**: The settlement cash-reconciliation query filters on `work_session_id = ? AND outcome = 'Sale'` (or `status = 'Completed'`). PostgreSQL must either index-scan `work_session_id` and then filter `outcome` row-by-row, or bitmap-AND. A composite index makes this a direct range scan. Settlement is a critical end-of-day operation where latency directly impacts the admin's workflow.
- **Recommended Surgical Fix**:
  ```python
  Index('ix_visit_session_outcome', 'work_session_id', 'outcome'),
  ```
  (Add to a `__table_args__` tuple on `Visit`.)

---

### M-05: `OfferRule` Table Has No Product Association — Global-Only Offers

- **Severity**: **Medium**
- **Flaw Category**: Normalization Flaw / Missing FK
- **Exact Table & Line Number**: `OfferRule` — `models.py`, lines 394–402
- **Current Flawed Code**:
  ```python
  class OfferRule(Base):
      __tablename__ = 'offer_rules'
      id                 = Column(Integer, primary_key=True)
      threshold_quantity = Column(Integer, nullable=False)
      offer_type         = Column(String(50), nullable=False)
      bonus_quantity     = Column(Integer, nullable=False, default=0)
      discount_value     = Column(Numeric(12, 3), nullable=False, default=0.0)
      is_active          = Column(Boolean, nullable=False, default=True)
  ```
- **Impact Analysis**: Offers are global — they apply to **any** product meeting the threshold quantity. There is no `product_variant_id` FK, meaning: (a) a "buy 10 get 1 free" offer for cigarettes also applies to water bottles; (b) offers cannot be targeted to specific brands or categories; (c) if the business later needs per-product promotions (a near-certain requirement for FMCG), the schema must be migrated and all existing offer data restructured. The code comment on Driver (line 81) acknowledges this is "sufficient for the current phase" but this is a ticking schema-migration bomb.
- **Recommended Surgical Fix** (for future phase):
  ```python
  product_variant_id = Column(Integer, ForeignKey('product_variants.id', ondelete='CASCADE'), nullable=True)
  # NULL = global offer; non-NULL = product-specific offer
  ```
  This is a forward-compatible, non-breaking addition — existing rows with `NULL` retain their global semantics.

---

## 🟢 Low

### L-01: `Product.base_name` Missing Unique Constraint — Duplicate Product Names Allowed

- **Severity**: **Low**
- **Flaw Category**: Missing UniqueConstraint (Data Quality)
- **Exact Table & Line Number**: `Product` — `models.py`, lines 111–119
- **Current Flawed Code**:
  ```python
  base_name = Column(String(150), nullable=False)
  ```
- **Impact Analysis**: Two `Product` rows can exist with the same `base_name` (e.g., "Marlboro" twice). `ProductVariant` uniqueness is guarded by SKU (`unique=True`, line 130), but duplicate base products create confusion in dropdowns, reports, and any UI that groups variants by product. The primary key `id` guarantees technical uniqueness but not semantic uniqueness.
- **Recommended Surgical Fix**:
  ```python
  base_name = Column(String(150), nullable=False, unique=True)
  ```

---

### L-02: `VisitReturn.visit_id` FK Lacks DB-Level `ondelete` Clause

- **Severity**: **Low**
- **Flaw Category**: Missing `ondelete` (ORM-Reliant Cascade)
- **Exact Table & Line Number**: `VisitReturn` — `models.py`, line 347
- **Current Flawed Code**:
  ```python
  visit_id = Column(Integer, ForeignKey('visits.id'), nullable=False, index=True)
  ```
- **Impact Analysis**: The `Visit.returns` relationship (line 358–359) declares `cascade='all, delete-orphan'`, so SQLAlchemy will delete child `VisitReturn` rows when a `Visit` is deleted **through the ORM**. However, if a `Visit` is ever deleted via raw SQL (`DELETE FROM visits WHERE id = …`) or by a future bulk-operation endpoint that bypasses the ORM, PostgreSQL will raise an `IntegrityError` because the FK has no `ON DELETE` clause. This is a defense-in-depth gap — the ORM cascade works today, but the schema itself does not protect against raw-SQL orphans.
- **Recommended Surgical Fix**:
  ```python
  visit_id = Column(Integer, ForeignKey('visits.id', ondelete='CASCADE'), nullable=False, index=True)
  ```

---

### L-03: `InventoryLedger.difference` Missing Check Constraints

- **Severity**: **Low**
- **Flaw Category**: Missing CheckConstraint (Data Quality)
- **Exact Table & Line Number**: `InventoryLedger` — `models.py`, line 446
- **Current Flawed Code**:
  ```python
  difference = Column(Integer, nullable=False)  # سالب للعجز، موجب للزيادة
  ```
- **Impact Analysis**: The comment states negative = deficit, positive = surplus, but there is no database-level constraint enforcing any range. A value of `NULL` or a nonsensical extreme (e.g., ±2,147,483,647) passes through unchecked. While `nullable=False` prevents NULL, no `CHECK` constraint validates that `difference` is logically consistent with `expected_quantity` and `actual_quantity` (i.e., `difference = actual_quantity - expected_quantity`). In practice the application computes this correctly, but a raw-SQL insert or a bug in a future endpoint could insert a ledger row where `difference ≠ actual - expected`, silently corrupting audit trails.
- **Recommended Surgical Fix**: At minimum, add a range sanity check; ideally, add a multi-column CHECK:
  ```python
  # Minimal: prevent absurd values
  difference = Column(Integer, CheckConstraint('difference BETWEEN -1000000 AND 1000000', name='chk_ledger_diff_range'), nullable=False)
  ```
  For full referential integrity, add in `__table_args__`:
  ```python
  CheckConstraint('difference = actual_quantity - expected_quantity', name='chk_ledger_diff_math'),
  ```

---

## Summary of Findings by Category

| Category | Count | Issues |
|----------|-------|--------|
| Missing Import (Runtime Crash) | 1 | C-01 |
| Missing/Incomplete Unique Index (Race Condition) | 1 | H-01 |
| Missing `ondelete` (Referential Integrity) | 2 | H-02, L-02 |
| Missing CheckConstraint | 2 | H-03, L-03 |
| Missing Index (Performance/Scan Risk) | 3 | H-04, M-03, M-04 |
| Missing UniqueConstraint (Data Quality) | 3 | M-01, M-02, L-01 |
| Normalization Flaw | 1 | M-05 |

---

*End of Phase 9 Schema Audit*

## Issue #14 — Missing Database-Level Guards Against Negative Money

- **Severity**: **High**
- **Flaw Category**: Missing CheckConstraint (Financial Vulnerability)
- **Exact Table & Line Number**: `Visit` — `models.py`, lines 293–294
- **Current Flawed Code**:
  ```python
  cash_collected                 = Column(Numeric(12, 3), nullable=True, default=0.0)
  debt_paid                      = Column(Numeric(12, 3), nullable=False, default=0.0)


  Impact Analysis: While inventory quantities (e.g., VisitItem.quantity) are heavily protected with CheckConstraint('... >= 0') in the database, the actual financial columns in the Visit table lack any database-level guards. If a bug in the application layer (or a direct DB manipulation) pushes a negative value to cash_collected or debt_paid, PostgreSQL will blindly accept it. This causes immediate, silent corruption of shop balances and end-of-day cash settlements. Furthermore, cash_collected allows NULL while debt_paid does not, creating an inconsistent schema that can lead to TypeError during mathematical aggregations.

Recommended Surgical Fix: Enforce NOT NULL on both and add positive-value check constraints:

cash_collected                 = Column(Numeric(12, 3), CheckConstraint('cash_collected >= 0', name='chk_visit_cash_positive'), nullable=False, default=0.0)
debt_paid                      = Column(Numeric(12, 3), CheckConstraint('debt_paid >= 0', name='chk_visit_debt_positive'), nullable=False, default=0.0)

Issue #15 — Destructive Cascade on Financial Handshakes
Severity: High

Flaw Category: Dangerous Cascade (Audit Trail Destruction)

Exact Table & Line Number: InventoryTransfer — models.py, lines 504–505

Current Flawed Code:
work_session_id    = Column(Integer, ForeignKey('work_sessions.id',    ondelete='CASCADE'), nullable=False)
product_variant_id = Column(Integer, ForeignKey('product_variants.id', ondelete='CASCADE'), nullable=False)

Impact Analysis: InventoryTransfer rows represent highly sensitive mid-day financial handshakes between the dispatch admin and the driver. The WarehouseLedger directly references these transfers via reference_id='TRANS_X'. If an admin accidentally (or maliciously) deletes a WorkSession or a ProductVariant, the ondelete='CASCADE' directive tells PostgreSQL to silently wipe all related transfer records. This permanently destroys the handshake audit trail, leaving the immutable WarehouseLedger pointing to ghost records that no longer exist. Financial and custody records must strictly block parent deletion.

Recommended Surgical Fix: Change the cascade strategy to RESTRICT to protect the audit trail:

work_session_id    = Column(Integer, ForeignKey('work_sessions.id',    ondelete='RESTRICT'), nullable=False)
product_variant_id = Column(Integer, ForeignKey('product_variants.id', ondelete='RESTRICT'), nullable=False)