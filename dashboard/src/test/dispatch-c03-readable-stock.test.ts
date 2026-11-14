import { describe, expect, it } from "vitest";
import { formatCustodyStockQuantity } from "../features/dispatch/custodyRecovery/stockPresentation";
import { custodyCopy, custodyStockStatus } from "../features/dispatch/custodyRecovery/copy";
import { line } from "../features/dispatch/custodyRecovery/contract";

const stock = {
  product_name: "شعيرية", sku: "S", batch_number: "11",
  expiry_date: "2028-03-02", base_uom: "EACH", base_uom_name: "حبة",
  display_uom_name: "باكيت", display_factor_to_base: "8",
  stock_status: "AVAILABLE", on_hand_base: "10.000000", reserved_base: "0.000000",
};

describe("vehicle custody presentation never changes signed inventory quantities", () => {
  it("shows the real largest product UOM plus remaining base units", () => {
    const parsed = line.parse(stock);
    expect(formatCustodyStockQuantity(parsed)).toBe("1 باكيت + 2 حبة");
    expect(formatCustodyStockQuantity({...parsed,on_hand_base:"15.000000"}))
      .toBe("1 باكيت + 7 حبة");
    expect(formatCustodyStockQuantity({...parsed,on_hand_base:"16.000000"}))
      .toBe("2 باكيت");
    expect(parsed.on_hand_base).toBe("10.000000");
  });
  it("never invents carton sizes when no largest UOM is registered", () => {
    expect(formatCustodyStockQuantity({
      ...stock,display_uom_name:null,display_factor_to_base:null,
      on_hand_base:"20.000000",
    })).toBe("20 حبة");
  });
  it("localizes status and no-lot label without displaying internal codes", () => {
    expect(custodyStockStatus("AVAILABLE","ar")).toBe("متاح");
    expect(custodyStockStatus("RECALLED","ar")).toBe("مسحوب من البيع");
    expect(custodyStockStatus("AVAILABLE","en")).toBe("Available");
    expect(custodyStockStatus("UNKNOWN_STATUS","ar")).toBe("تحتاج مراجعة");
    expect(custodyCopy("ar").noLot).toBe("بدون تشغيلة");
    expect(line.parse({...stock,batch_number:""}).batch_number).toBe("");
  });
});
