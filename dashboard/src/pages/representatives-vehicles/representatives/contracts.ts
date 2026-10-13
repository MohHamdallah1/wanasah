export type RepresentativeStatusFilter = "active" | "inactive" | "all";

export interface Representative {
  id: number;
  username: string;
  name: string;
  phone: string | null;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface RepresentativeListResult {
  items: Representative[];
}

export interface CreateRepresentativeInput {
  username: string;
  name: string;
  phone: string | null;
}

export interface UpdateRepresentativeInput {
  name: string;
  phone: string | null;
}

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
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") throw new RepresentativeContractError();
  return value;
};

export function parseRepresentative(value: unknown): Representative {
  const row = asRecord(value);
  if (
    typeof row.id !== "number" ||
    !Number.isSafeInteger(row.id) ||
    row.id <= 0 ||
    typeof row.username !== "string" ||
    !row.username.trim() ||
    typeof row.name !== "string" ||
    !row.name.trim() ||
    typeof row.is_active !== "boolean"
  ) {
    throw new RepresentativeContractError();
  }

  return {
    id: row.id,
    username: row.username,
    name: row.name,
    phone: optionalString(row.phone),
    is_active: row.is_active,
    created_at: optionalString(row.created_at),
    updated_at: optionalString(row.updated_at),
  };
}

/**
 * The frozen plan fixes the endpoint but not the list envelope. Keep the
 * compatibility boundary here until the backend contract is published.
 */
export function parseRepresentativeList(value: unknown): RepresentativeListResult {
  if (Array.isArray(value)) {
    return { items: value.map(parseRepresentative) };
  }

  const envelope = asRecord(value);
  if (!Array.isArray(envelope.items)) {
    throw new RepresentativeContractError();
  }
  return { items: envelope.items.map(parseRepresentative) };
}

/** Same isolation for mutation/detail wrappers: components only see Representative. */
export function parseRepresentativeResponse(value: unknown): Representative {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    if (record.representative !== undefined) {
      return parseRepresentative(record.representative);
    }
  }
  return parseRepresentative(value);
}

export function normalizeRepresentativeFormValue(value: string): string {
  return value.trim();
}

export function normalizeOptionalPhone(value: string): string | null {
  const normalized = value.trim();
  return normalized || null;
}
