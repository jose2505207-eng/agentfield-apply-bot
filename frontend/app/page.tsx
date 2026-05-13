"use client";

import { useState, useEffect } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "";

type Job = {
  id: string;
  url: string;
  source: string;
  title: string;
  company: string;
  location: string | null;
  is_remote: boolean;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  description: string;
};

type ApplyState = "idle" | "applying" | "done" | "error";

function fmtSalary(job: Job): string {
  if (!job.salary_min) return "";
  const fmt = (n: number) =>
    n >= 1000 ? `$${Math.round(n / 1000)}k` : `$${n}`;
  return `${fmt(job.salary_min)} – ${fmt(job.salary_max ?? job.salary_min)}`;
}

function JobCard({
  job,
  onApply,
  applyState,
  applyMsg,
  actionbookAvailable,
}: {
  job: Job;
  onApply: (job: Job) => void;
  applyState: ApplyState;
  applyMsg: string;
  actionbookAvailable: boolean;
}) {
  const salary = fmtSalary(job);
  return (
    <div className="border border-zinc-800 rounded-lg p-4 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <a
            href={job.url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-semibold text-white hover:text-indigo-400 transition-colors"
          >
            {job.title}
          </a>
          <div className="text-sm text-zinc-400 mt-0.5">
            {job.company}
            {job.location && (
              <span className="ml-2 text-zinc-500">· {job.location}</span>
            )}
            {job.is_remote && (
              <span className="ml-2 text-emerald-500">Remote</span>
            )}
            {salary && (
              <span className="ml-2 text-zinc-300">{salary}</span>
            )}
          </div>
        </div>
        <span className="text-xs text-zinc-600 mt-1 shrink-0 uppercase tracking-wider">
          {job.source}
        </span>
      </div>
      <div className="flex items-center gap-3">
        {actionbookAvailable ? (
          <button
            onClick={() => onApply(job)}
            disabled={applyState === "applying"}
            className="text-sm px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {applyState === "applying" ? "Applying…" : "Apply (dry run)"}
          </button>
        ) : (
          <a
            href={job.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 transition-colors"
          >
            Open Job →
          </a>
        )}
        {applyMsg && (
          <span
            className={`text-xs ${
              applyState === "error" ? "text-red-400" : "text-emerald-400"
            }`}
          >
            {applyMsg}
          </span>
        )}
      </div>
    </div>
  );
}

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [sources, setSources] = useState<string[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [actionbookAvailable, setActionbookAvailable] = useState(false);

  const [applyStates, setApplyStates] = useState<Record<string, ApplyState>>({});
  const [applyMsgs, setApplyMsgs] = useState<Record<string, string>>({});

  useEffect(() => {
    fetch(`${API}/api/status`)
      .then((r) => r.json())
      .then((d) => setActionbookAvailable(!!d.actionbook_available))
      .catch(() => {});
  }, []);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError("");
    setJobs([]);
    try {
      const res = await fetch(`${API}/api/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: query.trim(),
          sources: sources.length ? sources : null,
          max_per_source: 20,
        }),
      });
      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg);
      }
      const data: Job[] = await res.json();
      setJobs(data);
    } catch (err: unknown) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleApply(job: Job) {
    const key = `${job.source}:${job.id}`;
    setApplyStates((s) => ({ ...s, [key]: "applying" }));
    setApplyMsgs((s) => ({ ...s, [key]: "" }));
    try {
      const res = await fetch(`${API}/api/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job, dry_run: true }),
      });
      const text = await res.text();
      let data: Record<string, unknown> = { detail: text };
      try { data = JSON.parse(text); } catch { /* plain text error */ }
      if (!res.ok) {
        throw new Error((data.detail as string) ?? text);
      }
      const label = data.success ? "Applied!" : `Done: ${data.method_used}`;
      setApplyStates((s) => ({ ...s, [key]: "done" }));
      setApplyMsgs((s) => ({ ...s, [key]: label }));
    } catch (err: unknown) {
      setApplyStates((s) => ({ ...s, [key]: "error" }));
      setApplyMsgs((s) => ({ ...s, [key]: String(err) }));
    }
  }

  const SOURCE_OPTIONS = ["remoteok", "wellfound"];

  return (
    <div className="flex-1 flex flex-col max-w-3xl w-full mx-auto px-4 py-8 gap-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Job Search</h1>
        <p className="text-zinc-500 text-sm mt-1">
          Search across RemoteOK and Wellfound, then apply with one click.
        </p>
      </div>

      <form onSubmit={handleSearch} className="flex flex-col gap-3">
        <div className="flex gap-2">
          <input
            type="text"
            placeholder="e.g. AI engineer remote python"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="flex-1 px-3 py-2 rounded bg-zinc-900 border border-zinc-700 text-white placeholder-zinc-500 focus:outline-none focus:border-indigo-500"
          />
          <button
            type="submit"
            disabled={loading}
            className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed font-medium transition-colors"
          >
            {loading ? "Searching…" : "Search"}
          </button>
        </div>
        <div className="flex gap-4 text-sm text-zinc-400">
          {SOURCE_OPTIONS.map((s) => (
            <label key={s} className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={sources.includes(s) || sources.length === 0}
                onChange={(e) => {
                  if (e.target.checked) {
                    setSources((prev) =>
                      prev.length === 0
                        ? SOURCE_OPTIONS.filter((x) => x !== s)
                        : [...prev, s]
                    );
                  } else {
                    setSources((prev) => {
                      const next = prev.filter((x) => x !== s);
                      return next.length === SOURCE_OPTIONS.length - 1
                        ? []
                        : next;
                    });
                  }
                }}
                className="accent-indigo-500"
              />
              {s}
            </label>
          ))}
          {sources.length > 0 && (
            <button
              type="button"
              onClick={() => setSources([])}
              className="text-zinc-500 hover:text-zinc-300 ml-1"
            >
              reset
            </button>
          )}
        </div>
      </form>

      {error && (
        <div className="text-red-400 text-sm bg-red-950/40 border border-red-900 rounded px-3 py-2">
          {error}
        </div>
      )}

      {jobs.length > 0 && (
        <div className="flex flex-col gap-3">
          <p className="text-zinc-500 text-sm">{jobs.length} jobs found</p>
          {jobs.map((job) => {
            const key = `${job.source}:${job.id}`;
            return (
              <JobCard
                key={key}
                job={job}
                onApply={handleApply}
                applyState={applyStates[key] ?? "idle"}
                applyMsg={applyMsgs[key] ?? ""}
                actionbookAvailable={actionbookAvailable}
              />
            );
          })}
        </div>
      )}

      {!loading && jobs.length === 0 && !error && (
        <div className="text-zinc-600 text-sm text-center mt-8">
          Search for jobs to get started.
        </div>
      )}
    </div>
  );
}
