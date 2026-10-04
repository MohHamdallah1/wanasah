/** Read-only fixtures reusable by navigation/browser acceptance harnesses. */
export const batchSource = (id: number, name: string, type: "WAREHOUSE" | "VEHICLE" = "WAREHOUSE", canSend = true) => ({
  location_id: id, location_name: name, location_type: type, can_send: canSend,
  statuses: [{ stock_status: "QUARANTINED", on_hand_quantity: "10", reserved_quantity: "2", movable_quantity: "8",
    allowed_purposes: canSend ? ["QUARANTINE"] : [],
    special_actions: [
      { purpose: "QUARANTINE", allowed: canSend, eligible_quantity: canSend ? "8" : "0", reason_code: canSend ? "ALLOWED" : "SOURCE_CANNOT_SEND" },
      { purpose: "RECALL_RETURN", allowed: false, eligible_quantity: "0", reason_code: canSend ? "STATE_RESTRICTION" : "SOURCE_CANNOT_SEND" },
      { purpose: "RETURN_TO_VENDOR", allowed: false, eligible_quantity: "0", reason_code: canSend ? "STATE_RESTRICTION" : "SOURCE_CANNOT_SEND" },
      { purpose: "DISPOSAL", allowed: false, eligible_quantity: "0", reason_code: canSend ? "STATE_RESTRICTION" : "SOURCE_CANNOT_SEND" },
    ],
    terminal_actions: [
      { action: "CONFIRM_DISPOSAL", allowed: false, eligible_quantity: "0", reason_code: "STATE_RESTRICTION" },
      { action: "CONFIRM_VENDOR_HANDOVER", allowed: false, eligible_quantity: "0", reason_code: "STATE_RESTRICTION" },
    ],
    reservation_evidence: { coverage: "COMPLETE", reason: null, unattributed_quantity: "0", owners_truncated: false,
      owners: [{ owner_type: "DISPATCH_HANDSHAKE", module: "DISPATCH", transfer_id: id + 100, reference_number: `HS-${id}`,
        transfer_purpose: "ROUTE_LOAD", work_session_id: 80, route_id: 70, expected_receiver_id: 4, created_by: 7,
        quantity: "2", operation_status: "PENDING", navigation_target: "DISPATCH_ROUTE_TRANSFERS", action: null }] },
  }],
});

export const batchFocusPayload = (sources = [batchSource(11, "Warehouse A")]) => ({
  batch_id: 41, product_variant_id: 118, batch_number: "LOT-41", production_date: "2026-09-01", expiry_date: "2027-09-01",
  disposition: "QUARANTINED", disposition_reason: "Saved inspection reason", disposition_revision: 3,
  allowed_disposition_targets: ["RELEASED", "BLOCKED", "RECALLED"], days_to_expiry: 332,
  base_uom_id: 7, base_uom_code: "EACH", operational_hold: "NONE", sources,
});

export const inventoryReadAccess = (admin = true) => ({
  company_id: 1, driver_id: 7, is_company_admin: admin, location_id: null,
  permissions: admin ? ["inventory.read", "batch.disposition", "transfer.special.quarantine"] : [],
  any_permissions: ["inventory.read"], location_permissions: [],
});
