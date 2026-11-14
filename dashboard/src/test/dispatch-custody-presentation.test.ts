import {describe,expect,it} from "vitest";
import {visibleCustodyLines} from "@/features/dispatch/custodyRecovery/handoffPresentation";
import type {StockLine} from "@/features/dispatch/custodyRecovery/contract";
const base:StockLine={
  product_name:"Rice",sku:"R",batch_number:"",expiry_date:null,
  base_uom:"EACH",base_uom_name:"حبة",display_uom_name:null,
  display_factor_to_base:null,stock_status:"AVAILABLE",
  on_hand_base:"5.000000",reserved_base:"0",
};
describe("CUSTODY P0 physical grouping does not change signed stock",()=>{
  it("merges only indistinguishable unlabelled same SKU/status/UOM and preserves input",()=>{
    const rows=[base,{...base,on_hand_base:"20"},{
      ...base,product_name:"Vermicelli",sku:"V",batch_number:"LOT11",
      on_hand_base:"10",display_uom_name:"باكيت",display_factor_to_base:"8",
    },{
      ...base,product_name:"Vermicelli",sku:"V",batch_number:"LOT12",
      on_hand_base:"15",display_uom_name:"باكيت",display_factor_to_base:"8",
    },{...base,stock_status:"DAMAGED",on_hand_base:"2"}];
    const visible=visibleCustodyLines(rows);
    expect(visible).toHaveLength(4);
    expect(visible[0].on_hand_base).toBe("25");
    expect(visible[1].batch_number).toBe("LOT11");
    expect(visible[2].batch_number).toBe("LOT12");
    expect(visible[3].stock_status).toBe("DAMAGED");
    expect(rows[0].on_hand_base).toBe("5.000000");
    expect(rows[1].on_hand_base).toBe("20");
  });
});
