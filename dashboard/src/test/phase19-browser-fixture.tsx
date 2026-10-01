import { useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import i18n, { setAppLanguage } from "@/i18n";
import "@/index.css";
import ProductsPage from "@/pages/products/ProductsPage";
import { productImportSessionKey } from "@/pages/products/import/productImportSessionKey";

if (import.meta.env.VITE_BROWSER_ACCEPTANCE !== "synthetic-only" ||
    window.location.origin !== "http://127.0.0.1:5187") {
  throw new Error("SYNTHETIC_ONLY_ORIGIN_REQUIRED");
}
const JOB = "11111111-1111-4111-8111-111111111111";
const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
i18n.addResourceBundle("en", "acceptance", {
  arLabel: "Arabic", enLabel: "English", title: "Synthetic browser acceptance — no database", language: "Language", company: "Company",
  role: "Role", admin: "Administrator", operator: "Importer without price view",
  viewer: "Price viewer", restricted: "Restricted", scenario: "Rejected rows",
  start: "Start scenario", guide: "Start guide", hold: "Hold correction response",
  release: "Release response", trace: "HTTP evidence", a: "Synthetic A", b: "Synthetic B",
});
i18n.addResourceBundle("ar", "acceptance", {
  arLabel: "العربية", enLabel: "الإنجليزية", title: "قبول متصفح صناعي — دون قاعدة بيانات", language: "اللغة", company: "الشركة",
  role: "الدور", admin: "مسؤول", operator: "مستورد دون عرض أسعار",
  viewer: "مشاهد أسعار", restricted: "مقيّد", scenario: "الصفوف المرفوضة",
  start: "بدء السيناريو", guide: "بدء الدليل", hold: "تعليق رد التصحيح",
  release: "إرسال الرد", trace: "أدلة HTTP", a: "شركة صناعية A", b: "شركة صناعية B",
});
let initialCompany = Number(localStorage.getItem("company_id")) || 91001;
if (![91001, 91002].includes(initialCompany)) initialCompany = 91001;
localStorage.setItem("admin_token", "synthetic-" + initialCompany);
localStorage.setItem("company_id", String(initialCompany));
localStorage.setItem("driver_id", "91011");
const bootstrap = await fetch("/acceptance-api/fixture", { method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ company: initialCompany, role: "admin", hold: false }) });
if (!bootstrap.ok) throw new Error("SYNTHETIC_CONTROL_FAILED");
export default function Acceptance() {
  const [company, setCompany] = useState(initialCompany);
  const [role, setRole] = useState("admin");
  const [count, setCount] = useState("1");
  const [generation, setGeneration] = useState(0);
  const [held, setHeld] = useState(false);
  const [trace, setTrace] = useState("");
  const [, renderLocale] = useState(0);
  const t = (key: string) => i18n.t(key, { ns: "acceptance" });
  const control = async (body: object) => {
    const res = await fetch("/acceptance-api/fixture", { method: "POST", headers: {
      "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error("SYNTHETIC_CONTROL_FAILED");
    return res.json();
  };
  const changeIdentity = async (nextCompany: number, nextRole = role) => {
    await control({ company: nextCompany, role: nextRole });
    localStorage.setItem("admin_token", "synthetic-" + nextCompany);
    localStorage.setItem("company_id", String(nextCompany));
    setCompany(nextCompany); setRole(nextRole);
    await query.invalidateQueries();
  };
  const start = async (guide: boolean) => {
    await control({ count: Number(count), reset: true, company, role, hold: held });
    const key = productImportSessionKey(company, 91011)!;
    if (guide) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, JOB);
    query.clear(); setGeneration((value) => value + 1);
  };
  return <>
    <details open className="relative z-[100] [&:not([open])]:z-0 border-b bg-white p-2 text-xs"
      aria-label={t("title")}>
      <summary className="cursor-pointer font-bold">{t("title")}</summary>
      <div className="flex flex-wrap gap-2">
      <label>{t("language")}<select aria-label={t("language")} value={i18n.language}
        onChange={async (e) => { await setAppLanguage(e.target.value as "ar" | "en"); renderLocale((v) => v + 1); }}>
        <option value="ar">{t("arLabel")}</option><option value="en">{t("enLabel")}</option></select></label>
      <label>{t("company")}<select aria-label={t("company")} value={company}
        onChange={(e) => void changeIdentity(Number(e.target.value))}>
        <option value="91001">{t("a")}</option><option value="91002">{t("b")}</option></select></label>
      <label>{t("role")}<select aria-label={t("role")} value={role}
        onChange={(e) => void changeIdentity(company, e.target.value)}>
        {["admin", "operator", "viewer", "restricted"].map((r) => <option key={r} value={r}>{t(r)}</option>)}
      </select></label>
      <label>{t("scenario")}<select aria-label={t("scenario")} value={count} onChange={(e) => setCount(e.target.value)}>
        {[1, 25, 26].map((n) => <option key={n} value={n}>{new Intl.NumberFormat(i18n.language).format(n)}</option>)}
      </select></label>
      <button onClick={() => void start(false)}>{t("start")}</button>
      <button onClick={() => void start(true)}>{t("guide")}</button>
      <label><input type="checkbox" checked={held} onChange={async (e) => {
        const hold = e.target.checked; setHeld(hold); await control({ hold }); }} />{t("hold")}</label>
      <button onClick={() => void control({ release: true })}>{t("release")}</button>
      <button onClick={async () => setTrace(trace ? "" : JSON.stringify(await control({}), null, 2))}>{t("trace")}</button>
      </div>
    </details>
    <main className="min-h-screen bg-slate-100 p-2 sm:p-6"><ProductsPage key={generation} /></main>
    {trace ? <pre className="overflow-auto" dir={i18n.dir()}>{trace}</pre> : null}
    <Toaster richColors dir={i18n.dir()} />
  </>;
}
createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={query}><MemoryRouter><Acceptance /></MemoryRouter></QueryClientProvider>);
