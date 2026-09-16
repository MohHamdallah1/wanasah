import i18n from "@/i18n";

export function apiErrorCode(
  error: unknown
): string | undefined {
  if (
    !error ||
    typeof error !== "object"
  ) {
    return undefined;
  }

  if (
    "code" in error &&
    typeof error.code ===
      "string"
  ) {
    return error.code;
  }

  if ("data" in error) {
    const data = (
      error as {
        data?: unknown;
      }
    ).data;
    if (
      data &&
      typeof data ===
        "object" &&
      "detail" in data
    ) {
      const detail = (
        data as {
          detail?: unknown;
        }
      ).detail;
      if (
        detail &&
        typeof detail ===
          "object" &&
        "code" in detail &&
        typeof detail.code ===
          "string"
      ) {
        return detail.code;
      }
    }
  }

  return undefined;
}

export function apiErrorMessage(
  error: unknown,
  fallback: string
): string {
  const code =
    apiErrorCode(error);
  if (code) {
    const key =
      `errors.codes.${code}`;
    if (i18n.exists(key)) {
      return i18n.t(key);
    }
  }

  if (
    error instanceof Error &&
    !(
      "status" in
      (error as object)
    ) &&
    error.message
  ) {
    return error.message;
  }

  return fallback;
}

export function apiErrorStatus(
  error: unknown
): number | undefined {
  if (
    error &&
    typeof error === "object" &&
    "status" in error &&
    typeof error.status ===
      "number"
  ) {
    return error.status;
  }
  return undefined;
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
