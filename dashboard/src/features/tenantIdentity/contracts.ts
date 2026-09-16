import { z } from "zod";

const tenantIdentitySchema = z
  .object({
    company_id: z.number().int().positive(),
    company_name: z
      .string()
      .min(1)
      .max(150),
    company_code: z
      .string()
      .min(1)
      .max(50),
    currency_code: z
      .string()
      .min(1)
      .max(10),
    timezone: z
      .string()
      .min(1)
      .max(50),
    country_id: z
      .number()
      .int()
      .positive()
      .nullable(),
    country_name: z
      .string()
      .min(1)
      .max(100)
      .nullable(),
    display_location: z
      .string()
      .min(1)
      .max(100),
  })
  .strict();

export type TenantIdentity =
  z.infer<
    typeof tenantIdentitySchema
  >;

export function parseTenantIdentity(
  value: unknown
): TenantIdentity {
  const parsed =
    tenantIdentitySchema.safeParse(
      value
    );
  if (!parsed.success) {
    throw new Error(
      "TENANT_IDENTITY_CONTRACT_INVALID"
    );
  }
  return parsed.data;
}

export function formatTenantDate(
  timezone?: string,
  locale = "ar-JO"
): string {
  const options: Intl.DateTimeFormatOptions = {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    ...(timezone
      ? { timeZone: timezone }
      : {}),
  };

  try {
    return new Intl.DateTimeFormat(
      locale,
      options
    ).format(new Date());
  } catch {
    return new Intl.DateTimeFormat(
      locale,
      {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
      }
    ).format(new Date());
  }
}
