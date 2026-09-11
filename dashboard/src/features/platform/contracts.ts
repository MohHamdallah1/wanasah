import { z } from "zod";

export const platformSubscriptionSchema = z.enum([
  "active",
  "suspended",
  "expired",
  "trial",
]);

export const platformLoginResponseSchema = z.object({
  token: z.string().min(1),
  admin: z.string().min(1),
  role: z.literal("PlatformAdmin"),
});

export const platformCompanySchema = z.object({
  id: z.number().int().positive(),
  name: z.string().min(1),
  code: z.string().min(1),
  subscription: platformSubscriptionSchema,
  is_active: z.boolean(),
  created_at: z.string().nullable(),
});

export const platformCompanyPageSchema = z.object({
  items: z.array(platformCompanySchema),
  total: z.number().int().nonnegative(),
  page: z.number().int().positive(),
  page_size: z.number().int().positive(),
  pages: z.number().int().positive(),
});

export const createPlatformCompanyResponseSchema = z.object({
  message: z.string().min(1),
  company_id: z.number().int().positive(),
  company_code: z.string().min(1),
});

export type PlatformSubscription = z.infer<typeof platformSubscriptionSchema>;
export type PlatformCompany = z.infer<typeof platformCompanySchema>;
export type PlatformCompanyPage = z.infer<typeof platformCompanyPageSchema>;

export interface CreatePlatformCompanyPayload {
  name: string;
  company_code: string;
  admin_username: string;
  admin_password: string;
  admin_full_name: string;
  currency_code: string;
  subscription_status: PlatformSubscription;
}

