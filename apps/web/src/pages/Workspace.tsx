import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { type Job, type SyncPayload, artifactUrl, getJob, syncPayload } from "../api";
import { currentMeasure, notesInMeasure, seekTarget } from "../lib/timemap";

const EXPORTS: { kind: string; key: string }[] = [
  { kind: "pdf", key: "pdf" },
  { kind: "musicxml", key: "musicxml" },
  { kind: "mxl", key: "mxl" },
  { kind: "mid", key: "mid" },
  { kind: "mid_quantized", key: "mid_quantized" },
  { kind: "mei", key: "mei" },
  { kind: "timemap", key: "timemap" },
];

export default function Workspace(): JSX.Element {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [job, setJob] = useState<Job | null>(null);
  const [sync, setSync] = useState<SyncPayload | null>(null);
  const [pages, setPages] = useState<string[]>([]);
  const [measure, setMeasure] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    let cancelled = false;
    async function load(): Promise<void> {
      try {
        const [nextJob, nextSync] = await Promise.all([getJob(id), syncPayload(id)]);
        const texts = await Promise.all(nextSync.pages.map((page) => fetch(page.url).then((r) => r.text())));
        if (cancelled) return;
        setJob(nextJob);
        setSync(nextSync);
        setPages(texts);
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    let frame = 0;
    const tick = (): void => {
      const audio = audioRef.current;
      if (audio && sync) {
        const seconds = audio.currentTime + (job?.origin_offset_s ?? 0);
        const next = currentMeasure(sync.timemap, seconds);
        setMeasure((previous) => (previous === next ? previous : next));
      }
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [sync, job]);

  useEffect(() => {
    const root = sheetRef.current;
    if (!root || !sync || measure === null) return;
    root.querySelectorAll(".p2s-current").forEach((element) => element.classList.remove("p2s-current"));
    const ids = notesInMeasure(sync.timemap, measure);
    let first: Element | null = null;
    for (const noteId of ids) {
      const element = root.querySelector(`[id="${noteId}"]`);
      if (element) {
        element.classList.add("p2s-current");
        first ??= element;
      }
    }
    first?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [measure, sync, pages]);

  const audioUrl = useMemo(() => (job ? artifactUrl(id, "audio") : ""), [id, job]);
  const warnings: string[] = (job?.params as { warnings?: string[] } | undefined)?.warnings ?? [];

  function onClick(event: React.MouseEvent<HTMLDivElement>): void {
    const target = (event.target as Element).closest("[id]");
    const noteId = target?.id;
    const audio = audioRef.current;
    if (!noteId || !audio || !sync) return;
    const times = sync.timemap.notes[noteId];
    if (!times) return;
    audio.currentTime = Math.max(0, times[0] - (job?.origin_offset_s ?? 0));
    void audio.play();
  }

  if (error) return <p className="error">{error}</p>;
  if (!job || !sync) return <p className="muted">{t("workspace.loading")}</p>;

  return (
    <section className="workspace">
      <header className="workspace-head">
        <h1>
          {job.name} · {job.preset}
        </h1>
        <div className="export">
          <span>{t("workspace.export")}</span>
          {EXPORTS.map((entry) => (
            <a key={entry.kind} href={artifactUrl(id, entry.kind)} download>
              {t(`workspace.${entry.key}`)}
            </a>
          ))}
        </div>
      </header>
      <div className="workspace-body">
        <div className="sheet" ref={sheetRef} onClick={onClick}>
          {pages.length === 0 ? <p className="muted">{t("workspace.not_ready")}</p> : null}
          {pages.map((svg, index) => (
            <div key={index} className="sheet-page" dangerouslySetInnerHTML={{ __html: svg }} />
          ))}
        </div>
        <aside className="info">
          <h2>{t("workspace.measure")}</h2>
          <p className="measure-number">{measure ?? "—"}</p>
          <h2>{t("workspace.warnings")}</h2>
          {warnings.length === 0 ? (
            <p className="muted">{t("workspace.no_warnings")}</p>
          ) : (
            <ul>
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
          <h2>{t("workspace.engines")}</h2>
          <ul>
            {job.stages.map((stage) => (
              <li key={stage.stage}>
                <code>{stage.stage}</code> {stage.engine}
              </li>
            ))}
          </ul>
        </aside>
      </div>
      <footer className="transport">
        <audio ref={audioRef} src={audioUrl} controls preload="auto" />
        <button
          type="button"
          onClick={() => {
            const audio = audioRef.current;
            if (!audio || measure === null || !sync) return;
            audio.currentTime = Math.max(0, seekTarget(sync.timemap, measure) - job.origin_offset_s);
            void audio.play();
          }}
        >
          {t("workspace.play")}
        </button>
      </footer>
    </section>
  );
}
