import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { type Job, deleteJob, listJobs } from "../api";

export default function Library(): JSX.Element {
  const { t } = useTranslation();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [query, setQuery] = useState("");

  async function refresh(search = query): Promise<void> {
    setJobs(await listJobs(search));
  }

  useEffect(() => {
    void refresh("");
  }, []);

  return (
    <section>
      <h1>{t("library.title")}</h1>
      <div className="toolbar">
        <input
          type="search"
          placeholder={t("library.search")}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void refresh();
          }}
        />
        <Link className="button" to="/new">
          {t("library.new")}
        </Link>
      </div>
      {jobs.length === 0 ? (
        <p className="muted">{t("library.empty")}</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>{t("library.name")}</th>
              <th>{t("library.status")}</th>
              <th>{t("library.preset")}</th>
              <th>{t("library.duration")}</th>
              <th>{t("library.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td>
                  <Link to={job.status === "succeeded" ? `/jobs/${job.id}/sheet` : `/jobs/${job.id}`}>
                    {job.name || job.id.slice(0, 8)}
                  </Link>
                </td>
                <td>
                  <span className={`status ${job.status}`}>{job.status}</span>
                </td>
                <td>{job.preset}</td>
                <td>{job.duration_s ? `${job.duration_s.toFixed(0)}s` : "—"}</td>
                <td className="actions">
                  <Link to={job.status === "succeeded" ? `/jobs/${job.id}/sheet` : `/jobs/${job.id}`}>
                    {t("library.open")}
                  </Link>
                  <button
                    type="button"
                    onClick={async () => {
                      await deleteJob(job.id);
                      await refresh();
                    }}
                  >
                    {t("library.delete")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
