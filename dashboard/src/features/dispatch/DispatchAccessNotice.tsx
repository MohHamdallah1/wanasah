import { useTranslation } from "react-i18next";

export type DispatchAccessDisplay = "loading" | "denied" | "error";

const messages = {
  ar: {
    loading: ["جارٍ التحقق من صلاحيات الوصول", "سيظهر المحتوى بعد التحقق من صلاحيات حسابك."],
    denied: ["لا تملك صلاحية عرض هذه البيانات", "قد تكون الصلاحية قد سُحبت. اطلب من مسؤول الشركة مراجعة الصلاحيات."],
    error: ["تعذّر التحقق من الصلاحيات", "لم نعرض أي بيانات قديمة. تحقق من الاتصال وأعد المحاولة."],
    retry: "إعادة المحاولة",
  },
  en: {
    loading: ["Checking access permissions", "Content will appear after this account's permissions are verified."],
    denied: ["You do not have access to this data", "Access may have been revoked. Ask your company administrator to review your permissions."],
    error: ["Unable to verify access", "Previously loaded data is hidden. Check your connection and try again."],
    retry: "Try again",
  },
} as const;

/** No prior-authority rows, financial data, or internal error codes in denied UI. */
export function DispatchAccessNotice({ state, onRetry }: {
  state: DispatchAccessDisplay;
  onRetry?: () => void;
}) {
  const { i18n } = useTranslation();
  const copy = messages[i18n.language.toLowerCase().startsWith("ar") ? "ar" : "en"];
  return (
    <section role={state === "loading" ? "status" : "alert"}
      className="m-4 rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm"
      dir={i18n.dir()}>
      <h2 className="font-bold text-slate-800">{copy[state][0]}</h2>
      <p className="mt-2 text-sm text-slate-600">{copy[state][1]}</p>
      {state !== "loading" && onRetry && (
        <button type="button" onClick={onRetry}
          className="mt-4 rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold hover:bg-slate-50">
          {copy.retry}
        </button>
      )}
    </section>
  );
}
