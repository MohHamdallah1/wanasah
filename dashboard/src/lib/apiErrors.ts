import i18n from "@/i18n";

export type NormalizedApiErrorPayload = {
  code?: string;
  message?: string;
  context?: Record<string, unknown>;
  requestId?: string;
};

const asRecord = (
  value: unknown
): Record<string, unknown> | undefined =>
  value !== null &&
  typeof value === "object" &&
  !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;

const readStructuredError = (
  value: unknown
): NormalizedApiErrorPayload | undefined => {
  const record = asRecord(value);
  if (!record) return undefined;

  const code =
    typeof record.code === "string" &&
    record.code.trim()
      ? record.code.trim()
      : undefined;
  const message =
    typeof record.message === "string" &&
    record.message.trim()
      ? record.message.trim()
      : undefined;
  const context =
    asRecord(record.context);
  const requestIdValue =
    record.request_id ??
    record.requestId;
  const requestId =
    typeof requestIdValue === "string" &&
    requestIdValue.trim()
      ? requestIdValue.trim()
      : undefined;

  if (
    !code &&
    !message &&
    !context &&
    !requestId
  ) {
    return undefined;
  }

  return {
    code,
    message,
    context,
    requestId,
  };
};

export function normalizeApiErrorResponse(
  data: unknown
): NormalizedApiErrorPayload {
  const root = asRecord(data);
  if (!root) {
    return {};
  }

  // FastAPI/Pydantic validation payloads use an array in `detail`.
  // Normalize that framework shape to a stable client-owned code instead
  // of letting framework English become a localization contract.
  if (Array.isArray(root.detail)) {
    return { code: "VALIDATION_ERROR" };
  }

  // Canonical contract first, then all supported legacy envelopes.
  for (const candidate of [
    root.error,
    root.message,
    root.detail,
    root,
  ]) {
    const parsed =
      readStructuredError(candidate);
    if (parsed) return parsed;
  }

  const legacyMessage =
    typeof root.message === "string" &&
    root.message.trim()
      ? root.message.trim()
      : typeof root.detail === "string" &&
          root.detail.trim()
        ? root.detail.trim()
        : undefined;

  return legacyMessage
    ? { message: legacyMessage }
    : {};
}

export function apiErrorCode(
  error: unknown
): string | undefined {
  const record = asRecord(error);
  if (!record) return undefined;

  if (
    typeof record.code === "string" &&
    record.code.trim()
  ) {
    return record.code.trim();
  }

  if (
    error instanceof Error &&
    /^[A-Z][A-Z0-9_]*$/.test(
      error.message.trim()
    )
  ) {
    return error.message.trim();
  }

  return normalizeApiErrorResponse(
    record.data
  ).code;
}

export function apiErrorContext(
  error: unknown
): Record<string, unknown> | undefined {
  const record = asRecord(error);
  if (!record) return undefined;

  const direct =
    asRecord(record.context);
  if (direct) return direct;

  return normalizeApiErrorResponse(
    record.data
  ).context;
}

export function apiErrorRequestId(
  error: unknown
): string | undefined {
  const record = asRecord(error);
  if (!record) return undefined;

  const direct =
    record.requestId ??
    record.request_id;
  if (
    typeof direct === "string" &&
    direct.trim()
  ) {
    return direct.trim();
  }

  return normalizeApiErrorResponse(
    record.data
  ).requestId;
}

export function apiErrorServerMessage(
  error: unknown
): string | undefined {
  const record = asRecord(error);
  if (!record) return undefined;

  if (
    typeof record.serverMessage ===
      "string" &&
    record.serverMessage.trim()
  ) {
    return record.serverMessage.trim();
  }

  return normalizeApiErrorResponse(
    record.data
  ).message;
}

export function apiErrorMessage(
  error: unknown,
  fallback: string
): string {
  const code = apiErrorCode(error);
  const context =
    apiErrorContext(error) ?? {};
  const requestId =
    apiErrorRequestId(error);
  const status =
    apiErrorStatus(error);

  const translatedCodeKey = code
    ? `errors.codes.${code}`
    : undefined;
  const hasTranslatedCode = Boolean(
    translatedCodeKey &&
    i18n.exists(translatedCodeKey)
  );
  const safeTranslatedServerError =
    typeof status === "number" &&
    status >= 500 &&
    code !== "INTERNAL_SERVER_ERROR" &&
    hasTranslatedCode;

  // Unknown/internal 5xx errors stay redacted. A known, explicitly translated
  // service/business code is safe to show because the client owns the text.
  if (
    typeof status === "number" &&
    status >= 500 &&
    !safeTranslatedServerError
  ) {
    return requestId
      ? i18n.t(
          "errors.unexpectedWithReference",
          { requestId }
        )
      : i18n.t(
          "errors.unexpected"
        );
  }

  if (
    code &&
    translatedCodeKey &&
    hasTranslatedCode
  ) {
    const translated =
      i18n.t(translatedCodeKey, context);
    if (
      typeof status === "number" &&
      status >= 500 &&
      requestId
    ) {
      return i18n.t(
        "errors.serverReasonWithReference",
        {
          message: translated,
          requestId,
        }
      );
    }
    return translated;
  }

  const serverMessage =
    apiErrorServerMessage(error);
  if (!code && serverMessage) {
    if (requestId) {
      return i18n.t(
        "errors.serverReasonWithReference",
        {
          message: serverMessage,
          requestId,
        }
      );
    }
    return serverMessage;
  }

  if (
    !code &&
    error instanceof Error &&
    !(
      "status" in
      (error as object)
    ) &&
    error.message
  ) {
    return error.message;
  }

  if (code && requestId) {
    return i18n.t(
      "errors.fallbackWithCodeAndReference",
      {
        fallback,
        code,
        requestId,
      }
    );
  }
  if (code) {
    return i18n.t(
      "errors.fallbackWithCode",
      {
        fallback,
        code,
      }
    );
  }
  if (requestId) {
    return i18n.t(
      "errors.fallbackWithReference",
      {
        fallback,
        requestId,
      }
    );
  }

  return fallback;
}

export function apiErrorStatus(
  error: unknown
): number | undefined {
  const record = asRecord(error);
  return (
    record &&
    typeof record.status === "number"
  )
    ? record.status
    : undefined;
}

export function isAmbiguousRequestError(
  error: unknown
): boolean {
  const status =
    apiErrorStatus(error);
  const code =
    apiErrorCode(error);
  return (
    code ===
      "NETWORK_UNAVAILABLE" ||
    code === "REQUEST_TIMEOUT" ||
    status === 0 ||
    status === 408 ||
    (typeof status ===
      "number" &&
      status >= 500)
  );
}
