import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { type Job, cancelJob, eventsUrl, getJob } from "../api";

export default function Processing(): JSX.Element {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<Job | null>(null);

  useEffect(() => {
    let stop = false;
    async function poll(): Promise<void> {
      try {
        const next = await getJob(id);
        if (stop) return;
        setJob(next);
        if (next.status === "succeeded") {
          navigate(`/jobs/${id}/sheet`, { replace: true });
          return;
        }
        if (["queued", "running"].includes(next.status)) {
          window.setTimeout(poll, 1000);
        }
      } catch {
        if (!stop) window.setTimeout(poll, 2000);
      }
    }
    void poll();
    const events = new EventSource(eventsUrl(id));
    events.onerror = () => events.close();
    return () => {
      stop = true;
      events.close();
    };
  }, [id, navigate]);

  if (!job) return <p className="muted">{t("processing.waiting")}</p>;
  return (
    <section>
      <h1>
        {t("processing.title")} — {job.name}
      </h1>
      <p>
        <span className={`status ${job.status}`}>{job.status}</span>{" "}
        {job.status === "running" || job.status === "queued" ? (
          <button type="button" onClick={() => void cancelJob(id)}>
            {t("processing.cancel")}
          </button>
        ) : null}
        {job.status === "succeeded" ? <Link to={`/jobs/${id}/sheet`}>{t("processing.open")}</Link> : null}
      </p>
      {job.error ? (
        <p className="error">
          {t("processing.error")}: {job.error}
        </p>
      ) : null}
      <h2>{t("processing.stages")}</h2>
      <ul className="stages">
        {job.stages.map((stage) => (
          <li key={stage.stage}>
            <code>{stage.stage}</code> {stage.engine} — {stage.cache_hit ? "cache" : `${stage.duration_s.toFixed(1)}s`}
          </li>
        ))}
      </ul>
    </section>
  );
}
