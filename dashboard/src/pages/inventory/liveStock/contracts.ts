import { parseQuantity, type Quantity } from "../quantity";

export interface WarehouseProduct {
  id: number; name: string; sku: string | null;
  base_uom_id: number; base_uom_code: string; base_uom_name: string;
  display_uom_id:number; display_uom_code:string; display_uom_name:string;
  display_factor_to_base:Quantity; currency_code:string; average_cost_display:string|null;
  quantity_scale: number; quantity_step: Quantity;
  available_quantity: Quantity; reserved_quantity: Quantity; blocked_quantity: Quantity;
  total_quantity: Quantity; damaged_quantity: Quantity; minimum_quantity: Quantity;
}
export interface WarehouseInventoryCursorPage { items: WarehouseProduct[]; next_cursor: string | null; has_more: boolean; total: number | null; alert_count: number | null; alert_samples: string[] }
const record = (value: unknown): Record<string,unknown> => { if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("عقد الرصيد الحي غير صالح."); return value as Record<string,unknown>; };
const int = (value: unknown, field: string, min=0): number => { if(typeof value!=="number"||!Number.isSafeInteger(value)||value<min) throw new Error(`حقل ${field} غير صالح.`); return value; };
const str = (value: unknown, field: string, max=200): string => { if(typeof value!=="string"||!value.trim()||value.length>max) throw new Error(`حقل ${field} غير صالح.`); return value; };
const optional = (value: unknown): string|null => value===null ? null : str(value,"sku",100);
const moneyOrNull=(value:unknown,field:string):string|null=>{if(value===null)return null;const text=str(value,field,64);if(!/^\d+(?:\.\d{1,6})?$/.test(text))throw new Error(`حقل ${field} غير صالح.`);return text;};
export function parseLiveStockPage(raw: unknown): WarehouseInventoryCursorPage {
  const page=record(raw); if(!Array.isArray(page.items)||page.items.length>200||typeof page.has_more!=="boolean") throw new Error("صفحة المخزون غير صالحة.");
  const ids=new Set<number>(); const items=page.items.map((rawItem)=>{const row=record(rawItem); const id=int(row.id,"id",1); if(ids.has(id)) throw new Error("صنف مكرر في الرصيد الحي."); ids.add(id); const scale=int(row.quantity_scale,"quantity_scale"); if(scale>6) throw new Error("دقة كمية غير صالحة."); return {
    id,name:str(row.name,"name"),sku:optional(row.sku),base_uom_id:int(row.base_uom_id,"base_uom_id",1),base_uom_code:str(row.base_uom_code,"base_uom_code",20),base_uom_name:str(row.base_uom_name,"base_uom_name",50),display_uom_id:int(row.display_uom_id,"display_uom_id",1),display_uom_code:str(row.display_uom_code,"display_uom_code",20),display_uom_name:str(row.display_uom_name,"display_uom_name",50),display_factor_to_base:parseQuantity(row.display_factor_to_base,"display_factor_to_base"),currency_code:str(row.currency_code,"currency_code",10),average_cost_display:moneyOrNull(row.average_cost_display,"average_cost_display"),quantity_scale:scale,quantity_step:parseQuantity(row.quantity_step,"quantity_step"),available_quantity:parseQuantity(row.available_quantity,"available_quantity",{allowZero:true}),reserved_quantity:parseQuantity(row.reserved_quantity,"reserved_quantity",{allowZero:true}),blocked_quantity:parseQuantity(row.blocked_quantity,"blocked_quantity",{allowZero:true}),total_quantity:parseQuantity(row.total_quantity,"total_quantity",{allowZero:true}),damaged_quantity:parseQuantity(row.damaged_quantity,"damaged_quantity",{allowZero:true}),minimum_quantity:parseQuantity(row.minimum_quantity,"minimum_quantity",{allowZero:true}),
  };});
  const next=page.next_cursor===null?null:str(page.next_cursor,"next_cursor",1024); if(page.has_more!==(next!==null)) throw new Error("ترقيم المخزون غير متسق.");
  const nullableCount=(value:unknown):number|null=>value===null?null:int(value,"count"); const samples=page.alert_samples; if(!Array.isArray(samples)||!samples.every((v)=>typeof v==="string")) throw new Error("عينات التنبيه غير صالحة.");
  return {items,next_cursor:next,has_more:page.has_more,total:nullableCount(page.total),alert_count:nullableCount(page.alert_count),alert_samples:[...samples] as string[]};
}
