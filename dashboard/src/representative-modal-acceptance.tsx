import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import "./index.css";
import { WorkspaceTopBar } from "./components/dashboard/WorkspaceTopBar";
import { Modal } from "./components/ui/modal";
import { representativesVehicles } from "./i18n/representativesVehicles";
import { RepresentativeForm } from "./pages/representatives-vehicles/representatives/RepresentativeForm";

type Kind = "create" | "edit" | "lifecycle" | "credentials" | null;
const lang = new URLSearchParams(location.search).get("lang") === "en" ? "en" : "ar";
const i18n = createInstance();
await i18n.init({
  lng: lang,
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  resources: {
    ar: { translation: { representativesVehicles: representativesVehicles.ar, common: { close: "إغلاق", cancel: "إلغاء", save: "حفظ", saving: "جارٍ الحفظ" } } },
    en: { translation: { representativesVehicles: representativesVehicles.en, common: { close: "Close", cancel: "Cancel", save: "Save", saving: "Saving" } } },
  },
});
document.documentElement.dir = i18n.dir();
document.documentElement.lang = lang;

const rep = {
  id: 17,
  full_name: "Ahmad Saleh",
  username: "rep17",
  phone_number: "+962790000000",
  is_active: true,
  can_allow_debt: false,
  max_debt_limit: "25.500",
};

function App() {
  const [kind, setKind] = useState<Kind>(null);
  const title = kind === "create"
    ? (lang === "ar" ? "إضافة مندوب جديد" : "Add representative")
    : kind === "edit"
      ? (lang === "ar" ? "تعديل البيانات" : "Edit details")
      : kind === "lifecycle"
        ? (lang === "ar" ? "حالة المندوب" : "Representative status")
        : (lang === "ar" ? "بيانات الدخول" : "Sign-in access");
  return (
    <main className="min-h-[1400px] bg-slate-100 p-4" dir={i18n.dir()}>
      <WorkspaceTopBar variant="page" className="shrink-0">
        <header data-testid="app-header" className="w-full text-white">APP HEADER</header>
      </WorkspaceTopBar>
      <div className="relative z-10 mt-4 flex flex-wrap gap-2">
        {(["create", "edit", "lifecycle", "credentials"] as const).map((value) => (
          <button key={value} data-testid={`open-${value}`} type="button" onClick={() => setKind(value)}>{value}</button>
        ))}
        <Modal isOpen={kind !== null} onClose={() => setKind(null)} title={title} maxWidth="max-w-lg">
          {kind === "create" ? (
            <RepresentativeForm onCancel={() => setKind(null)} onSubmit={() => undefined} />
          ) : kind === "edit" ? (
            <RepresentativeForm representative={rep} onCancel={() => setKind(null)} onSubmit={() => undefined} />
          ) : kind === "lifecycle" ? (
            <div className="space-y-3"><p>{lang === "ar" ? "تعطيل المندوب؟" : "Deactivate representative?"}</p><button type="button">confirm lifecycle</button></div>
          ) : kind === "credentials" ? (
            <div className="space-y-3"><label htmlFor="credential-test">{lang === "ar" ? "كلمة المرور الجديدة" : "New password"}</label><input id="credential-test" className="h-10 w-full border" /><button type="button">confirm credentials</button></div>
          ) : null}
        </Modal>
      </div>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<I18nextProvider i18n={i18n}><App /></I18nextProvider>);
