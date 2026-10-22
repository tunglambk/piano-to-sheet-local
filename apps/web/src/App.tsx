import { useTranslation } from "react-i18next";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { setLanguage } from "./i18n";
import Library from "./pages/Library";
import NewJob from "./pages/NewJob";
import Processing from "./pages/Processing";
import Workspace from "./pages/Workspace";

export default function App(): JSX.Element {
  const { t, i18n } = useTranslation();
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          {t("app.title")}
        </Link>
        <nav>
          <NavLink to="/" end>
            {t("app.library")}
          </NavLink>
          <NavLink to="/new">{t("app.new")}</NavLink>
        </nav>
        <div className="lang" aria-label={t("app.language")}>
          <button type="button" aria-pressed={i18n.language === "en"} onClick={() => setLanguage("en")}>
            EN
          </button>
          <button type="button" aria-pressed={i18n.language === "vi"} onClick={() => setLanguage("vi")}>
            VI
          </button>
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Library />} />
          <Route path="/new" element={<NewJob />} />
          <Route path="/jobs/:id" element={<Processing />} />
          <Route path="/jobs/:id/sheet" element={<Workspace />} />
        </Routes>
      </main>
    </div>
  );
}
