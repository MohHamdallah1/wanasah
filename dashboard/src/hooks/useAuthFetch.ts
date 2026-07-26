import { useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";

// C-02: Validate VITE_API_URL at module level — fail fast if missing
const API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
if (!API) {
    throw new Error("VITE_API_URL is not set. The dashboard cannot function without an API base URL.");
}

// H-07: Module-level flag to prevent multiple concurrent navigate("/login") calls
let isNavigatingToLogin = false;

export function useAuthFetch() {
    const navigate = useNavigate();

    return useCallback(async (path: string, opts: RequestInit = {}) => {
        // H-01: Trust ONLY admin_token — remove legacy "token" fallback
        const token = localStorage.getItem("admin_token");
        if (!token) {
            localStorage.removeItem("token"); // clean legacy key
            if (!isNavigatingToLogin) {
                isNavigatingToLogin = true;
                navigate("/login");
                // +++ سحق ثغرة الشلل الدائم: تصفير المتغير بعد ثانية ليسمح بالخروج المستقبلي +++
                setTimeout(() => { isNavigatingToLogin = false; }, 1000);
            }
            throw new Error("انتهت الجلسة، يرجى تسجيل الدخول مجدداً");
        }
        const cleanPath = path.startsWith("/") ? path : `/${path}`;

        // M-08: 15-second timeout to prevent hanging requests
        try {
            const timeoutController = new AbortController();
            const timeoutId = setTimeout(() => timeoutController.abort(), 15_000);

            try {
                const res = await fetch(`${API}${cleanPath}`, {
                    ...opts,
                    signal: opts.signal ?? timeoutController.signal,
                    headers: {
                        "Content-Type": "application/json",
                        Authorization: `Bearer ${token}`,
                        ...(opts.headers ?? {})
                    },
                });
                clearTimeout(timeoutId);

                if (res.status === 401) {
                    localStorage.removeItem("admin_token");
                    localStorage.removeItem("token");
                    if (!isNavigatingToLogin) {
                        isNavigatingToLogin = true;
                        navigate("/login");
                        // +++ سحق ثغرة الشلل الدائم: تصفير المتغير بعد ثانية ليسمح بالخروج المستقبلي +++
                        setTimeout(() => { isNavigatingToLogin = false; }, 1000);
                    }
                    throw new Error("انتهت الجلسة، يرجى تسجيل الدخول مجدداً");
                }

                // M-06: Safely parse JSON — handle non-JSON responses gracefully
                let data: any = null;
                const text = await res.text();
                if (text) {
                    try {
                        data = JSON.parse(text);
                    } catch {
                        const errorInstance: any = new Error("استجابة غير صالحة من السيرفر — ربما يوجد خطأ في الشبكة.");
                        errorInstance.status = res.status;
                        errorInstance.data = text.substring(0, 200);
                        throw errorInstance;
                    }
                }

                if (!res.ok) {
                    const errorInstance: any = new Error(data?.message || `خطأ سيرفر (${res.status})`);
                    errorInstance.status = res.status;
                    errorInstance.data = data;
                    throw errorInstance;
                }

                return data;
            } finally {
                clearTimeout(timeoutId);
            }
        } catch (err: any) {
            if (err.name === 'AbortError' && !opts.signal?.aborted) {
                throw new Error("انتهت مهلة الاتصال بالسيرفر. يرجى المحاولة مرة أخرى.");
            }
            throw err;
        }
    }, [navigate]);
}
