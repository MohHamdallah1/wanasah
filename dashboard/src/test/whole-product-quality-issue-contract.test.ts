import { describe, expect, it } from "vitest";

import { parseWholeProductIssueSourcesPage } from "@/pages/inventory/quality/wholeProductIssueContract";

const batch = (batchId: number) => ({
  batch_id: batchId,
  product_variant_id: 118,
  batch_number: `LOT-${batchId}`,
  production_date: "2026-09-01",
  expiry_date: "2027-09-01",
  disposition: "RELEASED",
  disposition_reason: null,
  disposition_revision: 1,
  days_to_expiry: 332,
  base_uom_id: 7,
  base_uom_code: "EA",
  operational_hold: "RECALL",
  sources: [
    {
      location_id: batchId,
      location_name: `Location ${batchId}`,
      location_type: batchId % 2 === 0 ? "VEHICLE" : "WAREHOUSE",
      can_send: true,
      statuses: [
        {
          stock_status: "AVAILABLE",
          on_hand_quantity: "10",
          reserved_quantity: "0",
          movable_quantity: "10",
          allowed_purposes: ["RECALL_RETURN", "QUARANTINE", "DISPOSAL"],
          reservation_evidence: {
            coverage: "NONE",
            reason: null,
            owners: [],
            unattributed_quantity: "0",
            owners_truncated: false,
          },
        },
      ],
    },
  ],
});

const page = {
  product_variant_id: 118,
  variant_version: 9,
  operational_hold: "RECALL",
  base_uom_id: 7,
  base_uom_code: "EA",
  batches: [batch(41), batch(42)],
  next_cursor: 42,
  has_more: true,
  ready_to_resume_sales: false,
  company_requirements_remaining: true,
};

describe("whole-product quality issue read contract", () => {
  it("keeps batches and physical sources separate", () => {
    const parsed = parseWholeProductIssueSourcesPage(page);
    expect(parsed.batches.map((item) => item.batch_id)).toEqual([41, 42]);
    expect(parsed.batches[0].sources[0].location_type).toBe("WAREHOUSE");
    expect(parsed.batches[1].sources[0].location_type).toBe("VEHICLE");
    expect(parsed.ready_to_resume_sales).toBe(false);
  });

  it("accepts backend-ready completion only when no company requirement remains", () => {
    const parsed = parseWholeProductIssueSourcesPage({
      ...page,
      batches: [],
      next_cursor: null,
      has_more: false,
      ready_to_resume_sales: true,
      company_requirements_remaining: false,
    });
    expect(parsed.ready_to_resume_sales).toBe(true);
  });

  it("fails closed on wrong hold, mixed variant, or contradictory readiness", () => {
    expect(() =>
      parseWholeProductIssueSourcesPage({ ...page, operational_hold: "NONE" }),
    ).toThrow("WHOLE_PRODUCT_ISSUE_RESPONSE_INVALID");
    expect(() =>
      parseWholeProductIssueSourcesPage({
        ...page,
        batches: [{ ...batch(41), product_variant_id: 999 }],
      }),
    ).toThrow("WHOLE_PRODUCT_ISSUE_RESPONSE_INVALID");
    expect(() =>
      parseWholeProductIssueSourcesPage({
        ...page,
        ready_to_resume_sales: true,
        company_requirements_remaining: true,
      }),
    ).toThrow("WHOLE_PRODUCT_ISSUE_RESPONSE_INVALID");
  });
});
