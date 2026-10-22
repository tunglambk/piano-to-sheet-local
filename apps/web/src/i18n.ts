import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import vi from "./locales/vi.json";

const stored = window.localStorage.getItem("p2s.lang");
const language = stored === "vi" || stored === "en" ? stored : "en";

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, vi: { translation: vi } },
  lng: language,
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export function setLanguage(language: "en" | "vi"): void {
  window.localStorage.setItem("p2s.lang", language);
  void i18n.changeLanguage(language);
}

export default i18n;
