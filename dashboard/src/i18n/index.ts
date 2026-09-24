import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import {
  resources,
  supportedLanguages,
  type SupportedLanguage,
} from "./resources";
import {
  resolveI18nLocale,
} from "@/lib/locale";

const STORAGE_KEY = "wanasah.language";

const storedLanguage =
  typeof window !== "undefined"
    ? window.localStorage.getItem(STORAGE_KEY)
    : null;

const initialLanguage: SupportedLanguage =
  storedLanguage &&
  supportedLanguages.includes(
    storedLanguage as SupportedLanguage
  )
    ? (storedLanguage as SupportedLanguage)
    : "ar";

void i18n.use(initReactI18next).init({
  resources,
  lng: initialLanguage,
  fallbackLng: "en",
  supportedLngs: supportedLanguages,
  defaultNS: "translation",
  interpolation: {
    escapeValue: false,
  },
  returnNull: false,
});

const applyDocumentLocale = (
  language: string
) => {
  if (typeof document === "undefined") {
    return;
  }

  const normalized =
    language.split("-")[0] || "ar";
  document.documentElement.lang =
    normalized;
  document.documentElement.dir =
    i18n.dir(language);
};

applyDocumentLocale(i18n.language);

i18n.on(
  "languageChanged",
  (language) => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(
        STORAGE_KEY,
        language.split("-")[0]
      );
    }
    applyDocumentLocale(language);
  }
);

export const setAppLanguage = async (
  language: SupportedLanguage
) => {
  await i18n.changeLanguage(language);
};

export const currentLocale = () =>
  resolveI18nLocale(i18n);

export default i18n;
