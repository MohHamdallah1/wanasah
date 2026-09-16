type DurableRecord = {
  requestId: string;
  payloadHash: string;
  createdAt: number;
};

const PREFIX = "wanasah:durable:v1";
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

const canonicalize = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map(canonicalize);
  }
  if (
    value !== null &&
    typeof value === "object"
  ) {
    return Object.fromEntries(
      Object.entries(
        value as Record<string, unknown>
      )
        .filter(([, item]) => item !== undefined)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, item]) => [
          key,
          canonicalize(item),
        ])
    );
  }
  return value;
};

const sha256Hex = async (
  data: ArrayBuffer
): Promise<string> => {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    data
  );
  return Array.from(
    new Uint8Array(digest),
    (byte) => byte.toString(16).padStart(2, "0")
  ).join("");
};

export const hashPayload = async (
  value: unknown
): Promise<string> => {
  const encoded = new TextEncoder().encode(
    JSON.stringify(canonicalize(value))
  );
  return sha256Hex(encoded.buffer);
};

export const fileFingerprint = async (
  file: File
): Promise<string> => {
  const bytes = await file.arrayBuffer();
  const contentHash = await sha256Hex(bytes);
  return hashPayload({
    name: file.name,
    size: file.size,
    type: file.type,
    contentHash,
  });
};

export const durableScope = (
  companyId: number,
  driverId: number,
  operation: string,
  target: string | number = "default"
) =>
  `${PREFIX}:${companyId}:${driverId}:${operation}:${target}`;

const readRecord = (
  scope: string
): DurableRecord | null => {
  try {
    const raw = localStorage.getItem(scope);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as DurableRecord;
    if (
      typeof parsed.requestId !== "string" ||
      typeof parsed.payloadHash !== "string" ||
      typeof parsed.createdAt !== "number" ||
      Date.now() - parsed.createdAt > MAX_AGE_MS
    ) {
      localStorage.removeItem(scope);
      return null;
    }
    return parsed;
  } catch {
    localStorage.removeItem(scope);
    return null;
  }
};

export const getOrCreateDurableRequestId = async (
  scope: string,
  payload: unknown
): Promise<string> => {
  const payloadHash = await hashPayload(payload);
  const existing = readRecord(scope);
  if (
    existing &&
    existing.payloadHash === payloadHash
  ) {
    return existing.requestId;
  }

  const record: DurableRecord = {
    requestId: crypto.randomUUID(),
    payloadHash,
    createdAt: Date.now(),
  };
  localStorage.setItem(
    scope,
    JSON.stringify(record)
  );
  return record.requestId;
};

export const completeDurableOperation = (
  scope: string,
  requestId: string
) => {
  const existing = readRecord(scope);
  if (existing?.requestId === requestId) {
    localStorage.removeItem(scope);
  }
};

export const abandonDurableOperation = (
  scope: string
) => {
  localStorage.removeItem(scope);
};
