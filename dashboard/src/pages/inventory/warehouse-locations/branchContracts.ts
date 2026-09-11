import { z } from "zod";

export const branchItemSchema = z.object({
  id: z.number().int().positive(),
  name: z.string().min(1),
  code: z.string().min(1),
  is_active: z.boolean(),
  created_at: z.string().min(1),
});

export const branchPageSchema = z.object({
  items: z.array(branchItemSchema),
  next_cursor: z.string().nullable(),
  has_more: z.boolean(),
  total: z.number().int().nonnegative().nullable(),
});

export const branchMutationSchema = z.object({
  message: z.string().min(1),
  branch: branchItemSchema,
});

export type BranchItem = z.infer<typeof branchItemSchema>;
export type BranchPage = z.infer<typeof branchPageSchema>;

export function parseBranchPage(value: unknown): BranchPage {
  const parsed = branchPageSchema.safeParse(value);
  if (!parsed.success) throw new Error("تنسيق قائمة الفروع غير صالح.");
  return parsed.data;
}

export function parseBranchMutation(value: unknown) {
  const parsed = branchMutationSchema.safeParse(value);
  if (!parsed.success) throw new Error("استجابة عملية الفرع غير صالحة.");
  return parsed.data;
}

