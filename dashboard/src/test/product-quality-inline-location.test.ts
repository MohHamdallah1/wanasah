import { describe, expect, it } from "vitest";

import {
  actionTotal,
  aggregateProductQualityLocations,
  allocateRequestedQuantity,
} from "@/features/inventory/quality/productQualityLocationModel";
import type { ProductQualityPage } from "@/features/inventory/quality/wholeProductQualityContract";

const page = (): ProductQualityPage => ({
  productVariantId: 44,
  baseUomId: 1,
  baseUomCode: "EACH",
  nextCursor: null,
  hasMore: false,
  batches: [
    {
      batchId: 101,
      batchNumber: "LOT-A",
      expiryDate: "2027-01-01",
      baseUomId: 1,
      baseUomCode: "EACH",
      sources: [
        {
          locationId: 7,
          locationName: "مستودع التطوير",
          locationType: "WAREHOUSE",
          statuses: [
            {
              stockStatus: "AVAILABLE",
              onHandQuantity: "60",
              reservedQuantity: "10",
              movableQuantity: "50",
              dispatchActions: [
                { action: "DISPOSAL", allowed: true, eligibleQuantity: "50", reasonCode: "ALLOWED" },
                { action: "RETURN_TO_VENDOR", allowed: true, eligibleQuantity: "50", reasonCode: "ALLOWED" },
              ],
              terminalActions: [],
            },
          ],
        },
      ],
    },
    {
      batchId: 102,
      batchNumber: "LOT-B",
      expiryDate: "2027-02-01",
      baseUomId: 1,
      baseUomCode: "EACH",
      sources: [
        {
          locationId: 7,
          locationName: "مستودع التطوير",
          locationType: "WAREHOUSE",
          statuses: [
            {
              stockStatus: "BLOCKED",
              onHandQuantity: "40",
              reservedQuantity: "0",
              movableQuantity: "40",
              dispatchActions: [
                { action: "DISPOSAL", allowed: true, eligibleQuantity: "40", reasonCode: "ALLOWED" },
                { action: "RETURN_TO_VENDOR", allowed: false, eligibleQuantity: "0", reasonCode: "STATE_RESTRICTION" },
              ],
              terminalActions: [],
            },
          ],
        },
        {
          locationId: 8,
          locationName: "المستودع الثاني",
          locationType: "WAREHOUSE",
          statuses: [
            {
              stockStatus: "AVAILABLE",
              onHandQuantity: "20",
              reservedQuantity: "0",
              movableQuantity: "20",
              dispatchActions: [
                { action: "DISPOSAL", allowed: false, eligibleQuantity: "0", reasonCode: "NO_CONFIGURED_DESTINATION" },
                { action: "RETURN_TO_VENDOR", allowed: false, eligibleQuantity: "0", reasonCode: "NO_CONFIGURED_DESTINATION" },
              ],
              terminalActions: [],
            },
          ],
        },
      ],
    },
  ],
});

describe("whole-product quality location model", () => {
  it("hides batches behind one row per physical location while preserving exact stock totals", () => {
    const locations = aggregateProductQualityLocations([page()]);
    expect(locations).toHaveLength(2);
    expect(locations[1].locationName).toBe("مستودع التطوير");
    expect(locations[1].onHandQuantity).toBe("100");
    expect(locations[1].reservedQuantity).toBe("10");
    expect(locations[1].movableQuantity).toBe("90");
    expect(locations[1].batchIds).toEqual([101, 102]);
    expect(actionTotal(locations[1].dispatch.DISPOSAL)).toBe("90");
    expect(actionTotal(locations[1].dispatch.RETURN_TO_VENDOR)).toBe("50");
    expect(locations[0].needsDestinationSetup).toBe(true);
  });

  it("allocates a location-level command across backend-approved batches deterministically", () => {
    const location = aggregateProductQualityLocations([page()]).find((item) => item.locationId === 7)!;
    const allocations = allocateRequestedQuantity(location.dispatch.DISPOSAL, "75");
    expect(allocations).toEqual([
      expect.objectContaining({ batchId: 101, stockStatus: "AVAILABLE", quantity: "50" }),
      expect.objectContaining({ batchId: 102, stockStatus: "BLOCKED", quantity: "25" }),
    ]);
  });

  it("rejects a location quantity above the backend-derived eligible total", () => {
    const location = aggregateProductQualityLocations([page()]).find((item) => item.locationId === 7)!;
    expect(() => allocateRequestedQuantity(location.dispatch.DISPOSAL, "91")).toThrow("QUALITY_ACTION_QUANTITY_OUT_OF_RANGE");
  });
});
