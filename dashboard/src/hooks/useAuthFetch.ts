import { useCallback } from "react";
import { useNavigate } from "react-router-dom";

export function useAuthFetch() {
    const navigate = useNavigate();
    const API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

    return useCallback(async (path: string, opts: RequestInit = {}) => {
        const token = localStorage.getItem("admin_token") || localStorage.getItem("token");
        const cleanPath = path.startsWith("/") ? path : `/${path}`;

        const res = await fetch(`${API}${cleanPath}`, {
            ...opts,
            headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${token}`,
                ...(opts.headers ?? {})
            },
        });

        if (res.status === 401) {
            localStorage.removeItem("admin_token");
            localStorage.removeItem("token");
            navigate("/login");
            throw new Error("انتهت الجلسة، يرجى تسجيل الدخول مجدداً");
        }

        const text = await res.text();
        const data = text ? JSON.parse(text) : null;

        if (!res.ok) {
            // +++ الكي الجراحي: رمي كائن يحتوي على البيانات الكاملة وليس مجرد نص +++
            const errorInstance: any = new Error(data?.message || `خطأ سيرفر (${res.status})`);
            errorInstance.status = res.status;
            errorInstance.data = data;
            throw errorInstance;
        }

        return data;
    }, [navigate, API]);
}