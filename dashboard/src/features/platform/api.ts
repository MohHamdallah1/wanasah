import {
  createPlatformCompanyResponseSchema,
  type CreatePlatformCompanyPayload,
  platformCompanyPageSchema,
  platformLoginResponseSchema,
} from "@/features/platform/contracts";
import { clearPlatformSession, readPlatformSession } from "@/features/platform/session";

const API_URL = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
const REQUEST_TIMEOUT_MS = 15_000;

type PlatformApiError = Error & { status: number; data: unknown };

function makePlatformApiError(message: string, status: number, data: unknown): PlatformApiError {
  const error = new Error(message) as PlatformApiError;
  error.status = status;
  error.data = data;
  return error;
}

async function platformRequest(
  path: string,
  options: RequestInit = {},
  authenticated = true,
): Promise<unknown> {
  if (!API_URL) {
    throw makePlatformApiError("VITE_API_URL غير مضبوط.", 0, null);
  }

  const session = authenticated ? readPlatformSession() : null;
  if (authenticated && !session) {
    throw makePlatformApiError("انتهت جلسة مدير المنصة.", 401, null);
  }

  const timeoutController = new AbortController();
  const timeoutId = window.setTimeout(() => timeoutController.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(`${API_URL}${path}`, {
      ...options,
      signal: options.signal
        ? AbortSignal.any([options.signal, timeoutController.signal])
        : timeoutController.signal,
      headers: {
        "Content-Type": "application/json",
        ...(session ? { Authorization: `Bearer ${session.token}` } : {}),
        ...(options.headers ?? {}),
      },
    });

    const responseText = await response.text();
    let data: unknown = null;
    if (responseText) {
      try {
        data = JSON.parse(responseText);
      } catch {
        throw makePlatformApiError("استجابة غير صالحة من السيرفر.", response.status, null);
      }
    }

    if (!response.ok) {
      if (response.status === 401 && authenticated) clearPlatformSession();
      const message =
        typeof data === "object" && data !== null && "message" in data && typeof data.message === "string"
          ? data.message
          : `خطأ سيرفر (${response.status})`;
      throw makePlatformApiError(message, response.status, data);
    }
    return data;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      if (options.signal?.aborted) throw error;
      throw makePlatformApiError("انتهت مهلة الاتصال بالسيرفر.", 408, null);
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function parseContract<T>(
  parser: { safeParse: (data: unknown) => { success: true; data: T } | { success: false } },
  data: unknown,
): T {
  const parsed = parser.safeParse(data);
  if (!parsed.success) {
    throw makePlatformApiError("استجابة Platform API لا تطابق العقد المعتمد.", 502, data);
  }
  return parsed.data;
}

export async function loginPlatformAdmin(username: string, password: string) {
  const data = await platformRequest(
    "/platform/login",
    {
      method: "POST",
      body: JSON.stringify({ username, password }),
    },
    false,
  );
  return parseContract(platformLoginResponseSchema, data);
}

export async function fetchPlatformCompanies(page: number, pageSize: number, query: string) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (query) params.set("q", query);
  const data = await platformRequest(`/platform/companies?${params.toString()}`);
  return parseContract(platformCompanyPageSchema, data);
}

export async function createPlatformCompany(payload: CreatePlatformCompanyPayload) {
  const data = await platformRequest("/platform/companies", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return parseContract(createPlatformCompanyResponseSchema, data);
}

