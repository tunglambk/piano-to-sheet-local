import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { createJob } from "../api";

export default function NewJob(): JSX.Element {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [preset, setPreset] = useState("accurate");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);

  async function upload(file: File): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const id = await createJob(file, preset, name || file.name.replace(/\.[^.]+$/, ""));
      navigate(`/jobs/${id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h1>{t("new.title")}</h1>
      <div
        className="dropzone"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          const dropped = event.dataTransfer.files.item(0);
          if (dropped) setFile(dropped);
        }}
      >
        <p>{t("new.drop")}</p>
        <button type="button" onClick={() => inputRef.current?.click()}>
          {t("new.choose")}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="audio/*,video/*,.mp3,.mp4,.m4a,.wav,.flac,.ogg,.webm"
          hidden
          onChange={(event) => {
            const chosen = event.target.files?.item(0);
            if (chosen) setFile(chosen);
          }}
        />
      </div>
      <div className="form">
        <label>
          {t("new.preset")}
          <select value={preset} onChange={(event) => setPreset(event.target.value)}>
            <option value="accurate">{t("new.preset_accurate")}</option>
            <option value="fast">{t("new.preset_fast")}</option>
          </select>
        </label>
        <label>
          {t("new.name")}
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
      </div>
      <p className="muted">{file ? file.name : ""}</p>
      <button type="button" className="primary" disabled={!file || busy} onClick={() => file && void upload(file)}>
        {busy ? t("new.uploading") : t("new.start")}
      </button>
      {busy ? <p className="muted">{t("new.uploading")}</p> : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
