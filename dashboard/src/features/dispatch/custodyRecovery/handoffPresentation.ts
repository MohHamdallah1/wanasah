import type { StockLine } from "./contract";

/** UI grouping only. Signed stock_lines remain unmodified for all authority and POSTs. */
const decimals = (input: string): bigint | null => {
  const m=/^(\d+)(?:\.(\d{1,6}))?$/.exec(input);
  return m?BigInt(m[1])*1000000n+BigInt((m[2]??"").padEnd(6,"0")||"0"):null;
};
const str=(number:bigint)=>{
  const whole=number/1000000n, frac=(number%1000000n).toString().padStart(6,"0").replace(/0+$/,"");
  return frac?`${whole}.${frac}`:String(whole);
};
export function visibleCustodyLines(lines: readonly StockLine[]): StockLine[] {
  const result:StockLine[]=[], index=new Map<string,number>();
  for (const line of lines) {
    const physicalLot=line.batch_number.trim();
    const amount=decimals(line.on_hand_base), reserved=decimals(line.reserved_base);
    // Never combine real printed lots, differing UOM/status/expiry or invalid quantities.
    if(physicalLot || amount===null || reserved===null){result.push(line);continue;}
    const key=JSON.stringify([line.sku,line.product_name,line.expiry_date,line.base_uom,
      line.base_uom_name,line.display_uom_name,line.display_factor_to_base,line.stock_status]);
    const position=index.get(key);
    if(position===undefined){index.set(key,result.length);result.push(line);continue;}
    const prev=result[position], old=decimals(prev.on_hand_base), prevReserved=decimals(prev.reserved_base);
    if(old===null||prevReserved===null){result.push(line);continue;}
    result[position]={...prev,on_hand_base:str(old+amount),reserved_base:str(prevReserved+reserved)};
  }
  return result;
}
