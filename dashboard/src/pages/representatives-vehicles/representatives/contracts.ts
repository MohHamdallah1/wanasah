export type RepresentativeStatusFilter = "active" | "inactive" | "all";

export interface Representative {
  id: number;
  full_name: string;
  username: string;
  phone_number: string | null;
  is_active: boolean;
  can_allow_debt: boolean;
  max_debt_limit: string;
}

export interface RepresentativeListResult {
  items: Representative[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface CreateRepresentativeInput {
  full_name: string;
  username: string;
  phone_number: string;
  password: string;
  can_allow_debt: boolean;
  max_debt_limit: string;
}

export type UpdateRepresentativeInput = Partial<
  Pick<
    Representative,
    "full_name" | "username" | "phone_number" | "can_allow_debt" | "max_debt_limit"
  >
>;

export type RepresentativeAuthFetch = (
  path: string,
  options?: RequestInit,
) => Promise<unknown>;

export class RepresentativeContractError extends Error {
  readonly code = "REPRESENTATIVE_RESPONSE_INVALID";

  constructor(message = "REPRESENTATIVE_RESPONSE_INVALID") {
    super(message);
    this.name = "RepresentativeContractError";
  }
}

const asRecord = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new RepresentativeContractError();
  }
  return value as Record<string, unknown>;
};

const optionalString = (value: unknown): string | null => {
  if (value === null) return null;
  if (typeof value !== "string") throw new RepresentativeContractError();
  return value;
};

const exactDecimal = (value: unknown): string => {
  if (typeof value !== "string" || !/^\d{1,9}(?:\.\d{1,3})?$/.test(value)) {
    throw new RepresentativeContractError();
  }
  return value;
};

export function parseRepresentative(value: unknown): Representative {
  const row = asRecord(value);
  if (
    typeof row.id !== "number" ||
    !Number.isSafeInteger(row.id) ||
    row.id <= 0 ||
    typeof row.full_name !== "string" ||
    !row.full_name.trim() ||
    typeof row.username !== "string" ||
    !row.username.trim() ||
    typeof row.is_active !== "boolean" ||
    typeof row.can_allow_debt !== "boolean"
  ) {
    throw new RepresentativeContractError();
  }

  return {
    id: row.id,
    full_name: row.full_name,
    username: row.username,
    phone_number: optionalString(row.phone_number),
    is_active: row.is_active,
    can_allow_debt: row.can_allow_debt,
    max_debt_limit: exactDecimal(row.max_debt_limit),
  };
}

export function parseRepresentativeList(value: unknown): RepresentativeListResult {
  const envelope = asRecord(value);
  if (
    !Array.isArray(envelope.items) ||
    typeof envelope.has_more !== "boolean" ||
    !(
      envelope.next_cursor === null ||
      (typeof envelope.next_cursor === "string" && envelope.next_cursor.length <= 512)
    )
  ) {
    throw new RepresentativeContractError();
  }

  return {
    items: envelope.items.map(parseRepresentative),
    next_cursor: envelope.next_cursor as string | null,
    has_more: envelope.has_more,
  };
}

export function normalizeRepresentativeText(value: string): string {
  return value.trim();
}

export function normalizeOptionalPhone(value: string): string | null {
  const normalized = value.trim();
  return normalized || null;
}

export function normalizeRequiredPhone(value: string): string {
  return value.trim();
}

export function normalizeDebtLimit(value: string): string | null {
  const normalized = value.trim();
  const match = /^(0|[1-9]\d{0,8})(?:\.(\d{1,3}))?$/.exec(normalized);
  if (!match) return null;
  return `${match[1]}.${(match[2] ?? "").padEnd(3, "0")}`;
}
