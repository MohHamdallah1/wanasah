type DurableRecordKind =
  | "request"
  | "command";

type DurableRecord = {
  kind?: DurableRecordKind;
  requestId: string;
  payloadHash: string;
  payload?: unknown;
  createdAt: number;
};

export type DurableCommand<T> = {
  requestId: string;
  payload: T;
  createdAt: number;
};

const PREFIX = "wanasah:durable:v1";
const LEGACY_MAX_AGE_MS =
  7 * 24 * 60 * 60 * 1000;

const durableError = (
  code:
    | "DURABLE_OPERATION_PENDING"
    | "DURABLE_OPERATION_CORRUPT",
): Error & { code: string } => {
  const error = new Error() as Error & {
    code: string;
  };
  error.code = code;
  return error;
};

const canonicalize = (
  value: unknown,
): unknown => {
  if (Array.isArray(value)) {
    return value.map(canonicalize);
  }
  if (
    value !== null &&
    typeof value === "object"
  ) {
    return Object.fromEntries(
      Object.entries(
        value as Record<
          string,
          unknown
        >,
      )
        .filter(
          ([, item]) =>
            item !== undefined,
        )
        .sort(([a], [b]) =>
          a.localeCompare(b),
        )
        .map(([key, item]) => [
          key,
          canonicalize(item),
        ]),
    );
  }
  return value;
};

const sha256Hex = async (
  data: ArrayBuffer,
): Promise<string> => {
  const digest =
    await crypto.subtle.digest(
      "SHA-256",
      data,
    );
  return Array.from(
    new Uint8Array(digest),
    (byte) =>
      byte
        .toString(16)
        .padStart(2, "0"),
  ).join("");
};

export const hashPayload = async (
  value: unknown,
): Promise<string> => {
  const encoded =
    new TextEncoder().encode(
      JSON.stringify(
        canonicalize(value),
      ),
    );
  return sha256Hex(
    encoded.buffer,
  );
};

export const fileFingerprint = async (
  file: File,
): Promise<string> => {
  const bytes =
    await file.arrayBuffer();
  const contentHash =
    await sha256Hex(bytes);
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
  target:
    | string
    | number = "default",
) =>
  `${PREFIX}:${companyId}:${driverId}:${operation}:${target}`;

type DurableExpectation =
  | "request"
  | "command"
  | "any";

const hasOwnPayload = (
  record: DurableRecord,
): boolean =>
  Object.prototype.hasOwnProperty.call(
    record,
    "payload",
  );

const readRecord = (
  scope: string,
  expectation:
    DurableExpectation = "any",
): DurableRecord | null => {
  let raw: string | null;
  try {
    raw =
      localStorage.getItem(scope);
  } catch {
    throw durableError(
      "DURABLE_OPERATION_CORRUPT",
    );
  }

  if (raw === null) {
    return null;
  }
  if (raw.trim() === "") {
    throw durableError(
      "DURABLE_OPERATION_CORRUPT",
    );
  }

  let candidate: unknown;
  try {
    candidate =
      JSON.parse(raw);
  } catch {
    throw durableError(
      "DURABLE_OPERATION_CORRUPT",
    );
  }

  if (
    candidate === null ||
    typeof candidate !==
      "object" ||
    Array.isArray(candidate)
  ) {
    throw durableError(
      "DURABLE_OPERATION_CORRUPT",
    );
  }

  const parsed =
    candidate as DurableRecord;
  if (
    (parsed.kind !== undefined &&
      parsed.kind !== "request" &&
      parsed.kind !== "command") ||
    typeof parsed.requestId !==
      "string" ||
    !parsed.requestId ||
    typeof parsed.payloadHash !==
      "string" ||
    !parsed.payloadHash ||
    typeof parsed.createdAt !==
      "number" ||
    !Number.isFinite(
      parsed.createdAt,
    )
  ) {
    throw durableError(
      "DURABLE_OPERATION_CORRUPT",
    );
  }

  const payloadPresent =
    hasOwnPayload(parsed);
  const effectiveKind:
    DurableRecordKind =
    parsed.kind ??
    (payloadPresent
      ? "command"
      : "request");

  if (
    effectiveKind ===
      "command" &&
    !payloadPresent
  ) {
    throw durableError(
      "DURABLE_OPERATION_CORRUPT",
    );
  }
  if (
    effectiveKind ===
      "request" &&
    payloadPresent
  ) {
    throw durableError(
      "DURABLE_OPERATION_CORRUPT",
    );
  }
  if (
    expectation !== "any" &&
    effectiveKind !==
      expectation
  ) {
    throw durableError(
      "DURABLE_OPERATION_CORRUPT",
    );
  }

  // Only request-id-only records
  // keep the legacy expiry policy.
  // Unresolved full commands never
  // expire silently.
  if (
    expectation === "request" &&
    effectiveKind === "request" &&
    Date.now() -
      parsed.createdAt >
      LEGACY_MAX_AGE_MS
  ) {
    localStorage.removeItem(
      scope,
    );
    return null;
  }

  return {
    ...parsed,
    kind: effectiveKind,
  };
};

export const getOrCreateDurableRequestId =
  async (
    scope: string,
    payload: unknown,
  ): Promise<string> => {
    const payloadHash =
      await hashPayload(payload);
    const existing =
      readRecord(
        scope,
        "request",
      );
    if (
      existing &&
      existing.payloadHash ===
        payloadHash
    ) {
      return existing.requestId;
    }

    const record:
      DurableRecord = {
        kind: "request",
        requestId:
          crypto.randomUUID(),
        payloadHash,
        createdAt: Date.now(),
      };
    localStorage.setItem(
      scope,
      JSON.stringify(record),
    );
    return record.requestId;
  };

export const readDurableCommand =
  async <T>(
    scope: string,
  ): Promise<
    DurableCommand<T> | null
  > => {
    const existing =
      readRecord(
        scope,
        "command",
      );
    if (!existing) {
      return null;
    }

    const actualHash =
      await hashPayload(
        existing.payload,
      );
    if (
      actualHash !==
      existing.payloadHash
    ) {
      throw durableError(
        "DURABLE_OPERATION_CORRUPT",
      );
    }

    return {
      requestId:
        existing.requestId,
      payload:
        existing.payload as T,
      createdAt:
        existing.createdAt,
    };
  };

export const getOrCreateDurableCommand =
  async <T>(
    scope: string,
    payload: T,
  ): Promise<
    DurableCommand<T>
  > => {
    const payloadHash =
      await hashPayload(payload);
    const existing =
      readRecord(scope);

    if (existing) {
      if (
        existing.kind ===
        "request"
      ) {
        if (
          existing.payloadHash !==
          payloadHash
        ) {
          throw durableError(
            "DURABLE_OPERATION_PENDING",
          );
        }

        const promotedPayload =
          canonicalize(
            payload,
          ) as T;
        const promoted:
          DurableRecord = {
            ...existing,
            kind: "command",
            payload:
              promotedPayload,
          };
        localStorage.setItem(
          scope,
          JSON.stringify(
            promoted,
          ),
        );
        return {
          requestId:
            promoted.requestId,
          payload:
            promotedPayload,
          createdAt:
            promoted.createdAt,
        };
      }

      const storedHash =
        await hashPayload(
          existing.payload,
        );
      if (
        storedHash !==
        existing.payloadHash
      ) {
        throw durableError(
          "DURABLE_OPERATION_CORRUPT",
        );
      }

      if (
        existing.payloadHash !==
        payloadHash
      ) {
        throw durableError(
          "DURABLE_OPERATION_PENDING",
        );
      }

      return {
        requestId:
          existing.requestId,
        payload:
          existing.payload as T,
        createdAt:
          existing.createdAt,
      };
    }

    const storedPayload =
      canonicalize(
        payload,
      ) as T;
    const record:
      DurableRecord = {
        kind: "command",
        requestId:
          crypto.randomUUID(),
        payloadHash,
        payload:
          storedPayload,
        createdAt:
          Date.now(),
      };
    localStorage.setItem(
      scope,
      JSON.stringify(record),
    );
    return {
      requestId:
        record.requestId,
      payload:
        storedPayload,
      createdAt:
        record.createdAt,
    };
  };

export const completeDurableOperation =
  (
    scope: string,
    requestId: string,
  ) => {
    const existing =
      readRecord(scope);
    if (
      existing?.requestId ===
      requestId
    ) {
      localStorage.removeItem(
        scope,
      );
    }
  };

export const abandonDurableOperation =
  (scope: string) => {
    localStorage.removeItem(
      scope,
    );
  };
