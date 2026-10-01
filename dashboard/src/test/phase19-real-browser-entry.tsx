import { useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import i18n, { setAppLanguage } from "@/i18n";
import "@/index.css";
import ProductsPage from "@/pages/products/ProductsPage";

// Only the independent throwaway PostgreSQL/HTTP runner may launch this entry.
// The JWT is set from a private CDP command (never from a URL or bundle).
if (import.meta.env.VITE_P19_REAL_BROWSER !== "isolated-only" ||
    window.location.origin !== "http://127.0.0.1:5188") {
  throw new Error("DISPOSABLE_REAL_BROWSER_ORIGIN_REQUIRED");
}

i18n.addResourceBundle("ar", "acceptanceReal", {
  language: "اللغة", arabic: "العربية", english: "الإنجليزية",
});
i18n.addResourceBundle("en", "acceptanceReal", {
  language: "Language", arabic: "Arabic", english: "English",
});
const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
export default function Acceptance() {
  const [, redraw] = useState(0);
  const t = (key: string) => i18n.t(key, { ns: "acceptanceReal" });
  return <>
    <div className="border-b bg-white p-2 text-xs">
      <label htmlFor="p19-real-language">{t("language")}</label>
      <select id="p19-real-language" value={i18n.language.slice(0, 2)}
        onChange={async (event) => {
          await setAppLanguage(event.target.value as "ar" | "en");
          redraw((value) => value + 1);
        }}>
        <option value="ar">{t("arabic")}</option><option value="en">{t("english")}</option>
      </select>
    </div>
    <main className="min-h-screen bg-slate-100 p-2 sm:p-6">
      <ProductsPage />
    </main>
    <Toaster richColors dir={i18n.dir()} />
  </>;
}
createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={query}>
    <MemoryRouter><Acceptance /></MemoryRouter>
  </QueryClientProvider>
);
