import { useCallback } from "react";
import { useNavigate } from "react-router-dom";

const API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
if (!API) {
    throw new Error("VITE_API_URL is not set.");
}

// +++ العقل المدبر لـ (Silent Refresh) بمنع التكرار (Race Condition) +++
let isRefreshing = false;
let failedQueue: Array<{ resolve: (token: string) => void, reject: (err: any) => void }> = [];

const processQueue = (error: Error | null, token: string | null = null) => {
    failedQueue.forEach(prom => {
        if (error) prom.reject(error);
        else prom.resolve(token!);
    });
    failedQueue = [];
};

export function useAuthFetch() {
    const navigate = useNavigate();

    const forceLogout = useCallback((message: string) => {
        localStorage.removeItem("admin_token");
        localStorage.removeItem("refresh_token");
        navigate("/login", { replace: true });
        // لا داعي لرمي خطأ مرعب، التوجيه يكفي
    }, [navigate]);

    return useCallback(async (path: string, opts: RequestInit = {}) => {
        const token = localStorage.getItem("admin_token");
        if (!token) {
            forceLogout("انتهت الجلسة");
            throw new Error("انتهت الجلسة");
        }

        const cleanPath = path.startsWith("/") ? path : `/${path}`;
        const timeoutController = new AbortController();
        const timeoutId = setTimeout(() => timeoutController.abort(), 15_000);

        try {
            let res = await fetch(`${API}${cleanPath}`, {
                ...opts,
                signal: opts.signal ?? timeoutController.signal,
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
                    throw new Error("جلسة منتهية");
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

                        if (!refreshRes.ok) throw new Error("فشل تجديد الجلسة");
                        const data = await refreshRes.json();
                        
                        localStorage.setItem("admin_token", data.token);
                        isRefreshing = false;
                        // سيقوم هذا السطر بفك تعليق جميع الطلبات بما فيها الطلب الحالي
                        processQueue(null, data.token); 
                    } catch (refreshErr) {
                        isRefreshing = false;
                        processQueue(refreshErr as Error, null);
                        forceLogout("فشل التجديد");
                        throw new Error("تم تسجيل خروجك بسبب انتهاء الصلاحية الكلية");
                    }
                }

                // انتظار الحصول على التوكن الجديد من الطابور (سواء كان هذا الطلب هو من جدد أو غيره)
                const newToken = await newTokenPromise;

                res = await fetch(`${API}${cleanPath}`, {
                    ...opts,
                    signal: opts.signal ?? timeoutController.signal,
                    headers: {
                        "Content-Type": "application/json",
                        Authorization: `Bearer ${newToken}`,
                        ...(opts.headers ?? {})
                    },
                });
            }

            clearTimeout(timeoutId);

            // xử lý lỗi bình thường
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
                // إذا كان 403 (تم إيقافه إدارياً) نوجهه للخروج فوراً
                if (res.status === 403 && data?.detail?.includes("موقوف")) {
                    forceLogout("موقوف إدارياً");
                }
                const errorInstance: any = new Error(data?.detail || data?.message || `خطأ سيرفر (${res.status})`);
                throw errorInstance;
            }

            return data;
        } catch (err: any) {
            clearTimeout(timeoutId);
            if (err.name === 'AbortError') {
                throw new Error("انتهت مهلة الاتصال بالسيرفر. يرجى المحاولة مرة أخرى.");
            }
            throw err;
        }
    }, [forceLogout]);
}