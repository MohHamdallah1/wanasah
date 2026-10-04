import { describe, expect, it } from "vitest";

import { parseBatchStockSources } from "@/pages/inventory/batches/batchStockSourcesContract";

const response = {
  batch_id: 41,
  product_variant_id: 118,
  batch_number: "LOT-41",
  production_date: "2026-09-01",
  expiry_date: "2027-09-01",
  disposition: "QUARANTINED",
  disposition_reason: "اشتباه في تاريخ الصلاحية",
  disposition_revision: 3,
  days_to_expiry: 332,
  base_uom_id: 7,
  base_uom_code: "EA",
  operational_hold: "NONE",
  sources: [
    {
      location_id: 901,
      location_name: "Vehicle 12",
      location_type: "VEHICLE",
      can_send: true,
      statuses: [
        {
          stock_status: "QUARANTINED",
          on_hand_quantity: "12.000000",
          reserved_quantity: "2.000000",
          movable_quantity: "10.000000",
          allowed_purposes: ["QUARANTINE", "DISPOSAL"],
          special_actions: [
            { purpose: "QUARANTINE", allowed: true, eligible_quantity: "10", reason_code: "ALLOWED" },
            { purpose: "DISPOSAL", allowed: true, eligible_quantity: "10", reason_code: "ALLOWED" },
            { purpose: "RECALL_RETURN", allowed: false, eligible_quantity: "0", reason_code: "STATE_RESTRICTION" },
            { purpose: "RETURN_TO_VENDOR", allowed: false, eligible_quantity: "0", reason_code: "NO_CONFIGURED_DESTINATION" },
          ],
          terminal_actions: [],
          reservation_evidence: {
            coverage: "COMPLETE",
            reason: null,
            unattributed_quantity: "0",
            owners_truncated: false,
            owners: [
              {
                owner_type: "DISPATCH_HANDSHAKE",
                module: "DISPATCH",
                transfer_id: 77,
                reference_number: "HS-77",
                transfer_purpose: "ROUTE_RETURN",
                work_session_id: 18,
                route_id: 9,
                expected_receiver_id: 5,
                created_by: 3,
                quantity: "2.000000",
                operation_status: "PENDING",
                navigation_target: "DISPATCH_ROUTE_TRANSFERS",
                action: "FORCE_CANCEL_HANDSHAKE",
              },
            ],
          },
        },
      ],
    },
  ],
};

describe("batch stock-source action contract", () => {
  it("carries authoritative batch metadata even when the only physical source is a vehicle", () => {
    const parsed = parseBatchStockSources(response);

    expect(parsed.batch).toEqual({
      batch_id: 41,
      batch_number: "LOT-41",
      production_date: "2026-09-01",
      expiry_date: "2027-09-01",
      disposition: "QUARANTINED",
      disposition_reason: "اشتباه في تاريخ الصلاحية",
      disposition_revision: 3,
      days_to_expiry: 332,
    });
    expect(parsed.base_uom_code).toBe("EA");
    expect(parsed.sources).toHaveLength(1);
    expect(parsed.sources[0].location_type).toBe("VEHICLE");
    expect(parsed.sources[0].statuses[0]).toMatchObject({
      on_hand_quantity: "12",
      reserved_quantity: "2",
      movable_quantity: "10",
      allowed_purposes: ["QUARANTINE", "DISPOSAL"],
      reservation_evidence: {
        coverage: "COMPLETE",
        unattributed_quantity: "0",
        owners_truncated: false,
        owners: [
          {
            transfer_id: 77,
            reference_number: "HS-77",
            transfer_purpose: "ROUTE_RETURN",
            route_id: 9,
            quantity: "2",
            action: "FORCE_CANCEL_HANDSHAKE",
          },
        ],
      },
    });
  });

  it("fails closed when action-critical batch revision or metadata is invalid", () => {
    expect(() =>
      parseBatchStockSources({ ...response, disposition_revision: 0 }),
    ).toThrow("BATCH_STOCK_SOURCES_RESPONSE_INVALID");
    expect(() =>
      parseBatchStockSources({ ...response, batch_number: "" }),
    ).toThrow("BATCH_STOCK_SOURCES_RESPONSE_INVALID");
    expect(() =>
      parseBatchStockSources({ ...response, base_uom_code: "" }),
    ).toThrow("BATCH_STOCK_SOURCES_RESPONSE_INVALID");
  });

  it("fails closed when reservation-owner evidence is malformed or contradictory", () => {
    const badRoute = structuredClone(response);
    badRoute.sources[0].statuses[0].reservation_evidence.owners[0].route_id = 0;
    expect(() => parseBatchStockSources(badRoute)).toThrow(
      "BATCH_STOCK_SOURCES_RESPONSE_INVALID",
    );

    const contradictory = structuredClone(response);
    contradictory.sources[0].statuses[0].reservation_evidence.unattributed_quantity = "1";
    expect(() => parseBatchStockSources(contradictory)).toThrow(
      "BATCH_STOCK_SOURCES_RESPONSE_INVALID",
    );
  });

  it("keeps availability/reasons server-derived and rejects contradictory purpose evidence", () => {
    const parsed = parseBatchStockSources(response);
    expect(parsed.sources[0].statuses[0].special_actions).toEqual(response.sources[0].statuses[0].special_actions);
    const contradictory = structuredClone(response);
    contradictory.sources[0].statuses[0].special_actions[0].allowed = false;
    expect(() => parseBatchStockSources(contradictory)).toThrow("BATCH_STOCK_SOURCES_RESPONSE_INVALID");
    const inconsistentList = structuredClone(response);
    inconsistentList.sources[0].statuses[0].allowed_purposes = [];
    expect(() => parseBatchStockSources(inconsistentList)).toThrow("BATCH_STOCK_SOURCES_RESPONSE_INVALID");
  });
});
