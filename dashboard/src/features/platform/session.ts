const PLATFORM_TOKEN_KEY = "wanasah_platform_token";
const PLATFORM_ADMIN_KEY = "wanasah_platform_admin";

interface PlatformTokenPayload {
  exp: unknown;
  sub: unknown;
  type: unknown;
  is_platform_admin: unknown;
}

function decodeTokenPayload(token: string): PlatformTokenPayload | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;

    const base64Url = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64Url.padEnd(
      base64Url.length + ((4 - (base64Url.length % 4)) % 4),
      "=",
    );
    const payload: unknown = JSON.parse(atob(padded));
    if (typeof payload !== "object" || payload === null) return null;
    return payload as PlatformTokenPayload;
  } catch {
    return null;
  }
}

export function isPlatformTokenValid(token: string | null): token is string {
  if (!token) return false;
  const payload = decodeTokenPayload(token);
  return Boolean(
    payload &&
      payload.type === "platform_access" &&
      payload.is_platform_admin === true &&
      typeof payload.exp === "number" &&
      payload.exp * 1000 > Date.now() &&
      (typeof payload.sub === "string" || typeof payload.sub === "number"),
  );
}

export function readPlatformSession(): { token: string; admin: string } | null {
  const token = sessionStorage.getItem(PLATFORM_TOKEN_KEY);
  const admin = sessionStorage.getItem(PLATFORM_ADMIN_KEY);
  if (!isPlatformTokenValid(token) || !admin) {
    clearPlatformSession();
    return null;
  }
  return { token, admin };
}

export function savePlatformSession(token: string, admin: string): void {
  if (!isPlatformTokenValid(token)) {
    throw new Error("توكن جلسة المنصة غير صالح.");
  }
  sessionStorage.setItem(PLATFORM_TOKEN_KEY, token);
  sessionStorage.setItem(PLATFORM_ADMIN_KEY, admin);
}

export function clearPlatformSession(): void {
  sessionStorage.removeItem(PLATFORM_TOKEN_KEY);
  sessionStorage.removeItem(PLATFORM_ADMIN_KEY);
}

