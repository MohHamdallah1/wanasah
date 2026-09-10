import { useCallback } from "react";
import { useNavigate } from "react-router-dom";

const API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
if (!API) {
    throw new Error("VITE_API_URL is not set.");
}

// +++ العقل المدبر لـ (Silent Refresh) بمنع التكرار (Race Condition) +++
let isRefreshing = false;
let failedQueue: Array<{ resolve: (token: string) => void, reject: (err: unknown) => void }> = [];

const processQueue = (error: Error | null, token: string | null = null) => {
    failedQueue.forEach(prom => {
        if (error) prom.reject(error);
        else prom.resolve(token!);
    });
    failedQueue = [];
};

type HttpError = Error & {
    status: number;
    data: unknown;
};

const makeHttpError = (
    message: string,
    status: number,
    data: unknown = null
): HttpError => {
    const error = new Error(message) as HttpError;
    error.status = status;
    error.data = data;
    return error;
};

const getErrorStatus = (error: unknown): number | undefined => {
    if (typeof error !== "object" || error === null || !("status" in error)) {
        return undefined;
    }
    const status = (error as { status?: unknown }).status;
    return typeof status === "number" ? status : undefined;
};

export function useAuthFetch() {
    const navigate = useNavigate();

    const forceLogout = useCallback((message: string) => {
        // +++ الكي الجراحي (Security): إبلاغ السيرفر بحرق التوكنات (Blacklist & Revoke) قبل مسحها محلياً +++
        const currentToken = localStorage.getItem("admin_token");
        const currentRefresh = localStorage.getItem("refresh_token");
        if (currentToken) {
            fetch(`${API}/logout`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${currentToken}`,
                    'X-Refresh-Token': currentRefresh || ''
                }
            }).catch(() => {}); // Fire and forget: لا ننتظر الرد لكي لا نؤخر خروج المدير
        }

        localStorage.removeItem("admin_token");
        localStorage.removeItem("refresh_token");
        navigate("/login", { replace: true });
    }, [navigate]);

    return useCallback(async (path: string, opts: RequestInit = {}) => {
        const token = localStorage.getItem("admin_token");
        if (!token) {
            forceLogout("انتهت الجلسة");
            throw makeHttpError("انتهت الجلسة", 401);
        }

        const cleanPath = path.startsWith("/") ? path : `/${path}`;
        const timeoutController = new AbortController();
        const timeoutId = setTimeout(() => timeoutController.abort(), 15_000);

        try {
            let res = await fetch(`${API}${cleanPath}`, {
                ...opts,
                signal: opts.signal
                    ? AbortSignal.any([opts.signal, timeoutController.signal])
                    : timeoutController.signal,
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`,
                    ...(opts.headers ?? {})
                },
            });

            // +++ محرك التجديد التلقائي (Silent Refresh) +++
            if (res.status === 401) {
                const refreshToken = localStorage.getItem("refresh_token");
                if (!refreshToken) {
                    forceLogout("جلسة منتهية تماماً");
                    throw makeHttpError("جلسة منتهية", 401);
                }

                // +++   حجز مكان في الطابور *قبل* التجديد لجميع الطلبات +++
                const newTokenPromise = new Promise<string>((resolve, reject) => {
                    failedQueue.push({ resolve, reject });
                });

                if (!isRefreshing) {
                    isRefreshing = true;
                    try {
                        const refreshRes = await fetch(`${API}/refresh`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ refresh_token: refreshToken })
                        });

                        if (!refreshRes.ok) {
                            throw makeHttpError("فشل تجديد الجلسة", refreshRes.status);
                        }
                        const data = await refreshRes.json();
                        
                        localStorage.setItem("admin_token", data.token);
                        // +++ إغلاق حلقة الـ RTR: حفظ الـ refresh_token الجديد المُدار فوراً (الباكند يبطل القديم — عدم الحفظ هنا = طرد قسري كل 30 دقيقة) +++
                        if (data.refresh_token) {
                            localStorage.setItem("refresh_token", data.refresh_token);
                        }
                        isRefreshing = false;
                        // سيقوم هذا السطر بفك تعليق جميع الطلبات بما فيها الطلب الحالي
                        processQueue(null, data.token); 
                    } catch (refreshErr) {
                        isRefreshing = false;
                        processQueue(refreshErr as Error, null);
                        forceLogout("فشل التجديد");
                        throw makeHttpError(
                            "تم تسجيل خروجك بسبب انتهاء الصلاحية الكلية",
                            getErrorStatus(refreshErr) || 401
                        );
                    }
                }

                // انتظار الحصول على التوكن الجديد من الطابور
                const newToken = await newTokenPromise;

                // +++ الكي الجراحي (UX): إيقاف العداد القديم وبناء عداد جديد للطلب المعوّض لمنع الانقطاع التعسفي +++
                clearTimeout(timeoutId); 
                const retryTimeoutController = new AbortController();
                const retryTimeoutId = setTimeout(() => retryTimeoutController.abort(), 15_000);

                try {
                    res = await fetch(`${API}${cleanPath}`, {
                        ...opts,
                        signal: opts.signal
                            ? AbortSignal.any([opts.signal, retryTimeoutController.signal])
                            : retryTimeoutController.signal,
                        headers: {
                            "Content-Type": "application/json",
                            Authorization: `Bearer ${newToken}`,
                            ...(opts.headers ?? {})
                        },
                    });

                    if (res.status === 401) {
                        forceLogout("فشل التحقق بعد تجديد الجلسة");
                    }
                } finally {
                    clearTimeout(retryTimeoutId);
                }
            } else {
                // +++ تنظيف العداد للطلب السليم الذي لم يمر بمسار التجديد +++
                clearTimeout(timeoutId);
            }

            
            // Endpoint payload shape varies by route; keep this transport boundary dynamic.
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            let data: any = null;
            const text = await res.text();
            if (text) {
                try {
                    data = JSON.parse(text);
                } catch {
                    throw new Error("استجابة غير صالحة من السيرفر.");
                }
            }

            if (!res.ok) {
                if (res.status === 403 && !cleanPath.startsWith('/inventory/access/me')) {
                    window.dispatchEvent(new Event('inventory-permission-denied'));
                }
                const serverMessage =
                    data?.message || data?.detail || `خطأ سيرفر (${res.status})`;

                if (
                    res.status === 403 &&
                    typeof serverMessage === "string" &&
                    serverMessage.includes("تم إيقاف حسابك")
                ) {
                    forceLogout("تم إيقاف حسابك من قبل الإدارة");
                }

                throw makeHttpError(serverMessage, res.status, data);
            }

            return data;
        } catch (err: unknown) {
            clearTimeout(timeoutId);
            if (err instanceof Error && err.name === 'AbortError') {
                if (opts.signal?.aborted) {
                    throw err;
                }
                throw makeHttpError(
                    "انتهت مهلة الاتصال بالسيرفر. يرجى المحاولة مرة أخرى.",
                    408
                );
            }
            throw err;
        }
    }, [forceLogout]);
}