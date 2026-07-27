# Wanasah — Unregistered Issues Remediation Tracker (Checklist Version)

## Phase A: Authentication & Authorization (`auth.py`)
- [x] **A-01**: No Token Revocation / Logout Mechanism
- [x] **A-02**: In-Memory Dummy Password Hash Computed at Module Import
- [x] **A-03**: Admin Login Endpoint Verifies Password Before Checking `is_admin` Flag
- [x] **A-04**: `get_current_driver` Uses `getattr` with Unsafe Default `True`
- [x] **A-05**: No Centralized Resource-Ownership Guard (Systemic IDOR Risk)
- [x] **A-06**: `log_failed_attempt` Silently Swallows Database Exceptions
- [x] **A-07**: Hardcoded Token Expiry Duration

## Phase B: Dispatch Module (`dispatch.py`)
- [x] **B-01**: Missing Validation → Unhandled DB Constraint Violation (Negative Qty)
- [x] **B-02**: Data Integrity / Reporting Corruption (sellable_qty)
- [x] **B-03**: Asymmetric Cascade (restore_zone) لا يستعيد المحلات
- [x] **B-04**: Missing Validation (item.actual negative) في التسوية
- [x] **B-05**: Flawed Validation Formula (existing_pending_packs)
- [x] **B-06**: Falsy-Zero Bug in `bulk_import_shops`
- [x] **B-07**: Inconsistent Error Handling (Missing Rollback on Lock Leak)
- [x] **B-08**: Silent No-Op in `update_route_status` (vehicle_id missing)
- [x] **B-09**: Race Condition (TOCTOU) in `add_zone`/`update_zone`

## Phase C: Warehouse Module (`warehouse.py`)
- [x] **C-01**: Deadlock Risk / Unnecessary Lock Acquisition
- [x] **C-02**: Missing Validation (Negative `new_total_packs`)
- [x] **C-03**: Missing Validation (Negative `skip`/`limit` Pagination)
- [x] **C-04**: Missing Error Handling in Unauthorized Adjustment Audit Log

## Phase D: Driver Module (`driver.py`)
- [x] **D-01**: Daily Sample Cap Double-Counting on Cancelled Items
- [x] **D-02**: Unsafe Comparison of Potentially `None` Type
- [x] **D-03**: Unvalidated Response Input in `respond_to_transfer` (Status Hijacking)
- [x] **D-04**: Duplicated Loop Code Smell
- [x] **D-05**: Missing `with_for_update()` on `active_session` During Sale

## Phase E: Dashboard Frontend (React)
- [x] **E-01**: Login Stores Sensitive Session Data in localStorage (XSS Surface)
- [x] **E-02**: `SalesDetailsModal` Defined Inside Component — Re-created Every Render
- [x] **E-03**: Silent Catch With Only `console.error` — No User Feedback
- [x] **E-04**: `fetchInitialData` useCallback Missing Dependency
- [x] **E-05**: `Promise.all` Without Rollback — Partial Zone Scheduling Updates
- [x] **E-06**: Arabic Pluralization Logic Bug for Product Counts > 10
- [x] **E-07**: `setInterval` in DispatchBoard Does Not Refresh Zones or Shops
- [x] **E-08**: `handleConfirmSettlement` Error Handling — Undefined `.message`
- [x] **E-09**: Clock `setInterval` in Login Page — Unnecessary 1-Second Render
- [x] **E-10**: `mousemove` Listener DOM Query on Every Pixel Movement
- [x] **E-11**: `QueryClient` Instantiated at Module Scope Without Error Handling

## Phase F: Flutter Mobile
- [x] **F-01**: Race Condition in Database Singleton Getter (SQLITE_BUSY Crash)
- [x] **F-02**: Assert-Based Singleton Initialization Causes Release Crash
- [x] **F-03**: Stream Subscription Leak in RefreshIndicator onRefresh
- [x] **F-04**: Inventory Validation Race Condition on Rapid Cart Additions
- [x] **F-05**: JSON Built with String Interpolation (Injection Risk)
- [x] **F-06**: Missing Default `sendTimeout` on Base Dio Options
- [x] **F-07**: Debt/Cash Fields Sent for Postponed Visits (Duplicate of I-01)
- [x] **F-08**: False Success Feedback on Refresh Timeout
- [x] **F-09**: SQLite Divide by Zero Crash in Revert Logic
- [x] **F-10**: Incomplete Custody Reversal on Offline Visit Edit (Returns Ignored)
- [x] **F-11**: 401 Unauthorized Interceptor Leaks Sensitive Offline Data

## Phase G: Database Schema (`models.py`)
- [x] **G-01**: `OfferRule` Table Has No Product Association — Global-Only Offers
- [x] **G-02**: `Product.base_name` Missing Unique Constraint
- [x] **G-03**: `VisitReturn.visit_id` FK Lacks DB-Level `ondelete` Clause
- [x] **G-04**: `InventoryLedger.difference` Missing Check Constraints

## Phase I: Cross-Stack Integration
- [x] **I-01**: Flutter Sends Debt/Cash Fields for Postponed Visits (Contract Mismatch)
- [x] **I-02**: Missing `sendTimeout` + `pool_size=50` = Combinatorial DoS
- [x] **I-03**: Dashboard Aggressive 10s Polling + No Rate Limiting = Self-DoS
- [x] **I-04**: DispatchBoard Partial Refresh Creates Multi-Admin Split-Brain
- [x] **I-05**: Flutter `revertOfflineVisit` Ignores Returns
- [x] **I-06**: No `packs_per_carton` Zero Guard Offline
- [x] **I-07**: Flutter Returns Handling Asymmetry
- [x] **I-08**: 401 Interceptor Doesn't Guarantee Cross-Account Data Wipe
- [x] **I-09**: `ledgerFetchedRef` Cache Never Invalidated on Stocktake
- [x] **I-10**: Warehouse Low-Stock Threshold Alerts — No Notification Mechanism