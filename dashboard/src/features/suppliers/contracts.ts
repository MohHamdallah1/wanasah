import { z } from "zod";

const optional = (max: number) => z.string().min(1).max(max).nullable();
export const supplierSchema = z.object({
  id: z.number().int().positive(), name: z.string().min(1).max(300),
  code: optional(50), contact_person: optional(150), phone: optional(50),
  email: optional(254), address: optional(1000), notes: optional(4000),
  is_active: z.boolean(), version: z.number().int().positive(),
  created_at: z.string().datetime({ offset: true }), updated_at: z.string().datetime({ offset: true }),
});
export type Supplier = z.infer<typeof supplierSchema>;
export type SupplierDetails = Pick<Supplier, "name" | "code" | "contact_person" | "phone" | "email" | "address" | "notes">;
export const supplierPageSchema = z.object({
  items: z.array(supplierSchema).max(100), next_cursor: z.string().min(1).max(512).nullable(), has_more: z.boolean(),
}).refine(page => page.has_more === (page.next_cursor !== null)
  && new Set(page.items.map(row => row.id)).size === page.items.length);
function parse<T>(schema: z.ZodType<T>, raw: unknown): T {
  const result = schema.safeParse(raw);
  if (!result.success) throw Object.assign(new Error("SUPPLIER_RESPONSE_INVALID"), { code: "SUPPLIER_RESPONSE_INVALID" });
  return result.data;
}
export const parseSupplier = (raw: unknown) => parse(supplierSchema, raw);
export const parseSupplierPage = (raw: unknown) => parse(supplierPageSchema, raw);
export const emptySupplier: SupplierDetails = {
  name: "", code: null, contact_person: null, phone: null, email: null, address: null, notes: null,
};
export const supplierDraftKey = (companyId: number | undefined, actorId: number | undefined, target: string | number = "new") =>
  `wanasah:supplier-draft:${companyId}:${actorId}:${target}`;
export const isConfirmedSupplierRejection = (code: string | undefined) =>
  ["SUPPLIER_REQUIRED", "SUPPLIER_INACTIVE", "SUPPLIER_NOT_FOUND", "SUPPLIER_VERSION_CONFLICT", "SUPPLIER_DATA_CONFLICT"].includes(code ?? "");
