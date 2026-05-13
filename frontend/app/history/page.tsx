"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "";

type ApplyRecord = {
  job_id: string;
  job_source: string;
  job_title: string;
  company: string;
  apply_url: string;
  success: boolean;
  method_used: string;
  dry_run: boolean;
  sent_at: string;
  steps_taken: number;
  screenshot_path: string | null;
  final_url: string | null;
  error_message: string | null;
};

function badge(record: ApplyRecord) {
  if (record.method_used === "duplicate") return ["Duplicate", "text-zinc-400 bg-zinc-800"];
  if (record.success) return ["Applied", "text-emerald-300 bg-emerald-900/50"];
  if (record.method_used === "manual_review") return ["Dry Run", "text-yellow-300 bg-yellow-900/40"];
  if (record.method_used === "preflight_failed") return ["Failed", "text-red-400 bg-red-900/40"];
  return ["Incomplete", "text-zinc-400 bg-zinc-800"];
}

function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function HistoryPage() {
  const [records, setRecords] = useState<ApplyRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/api/history`)
      .then((r) => r.json())
      .then((data) => {
        setRecords(Array.isArray(data) ? (data as ApplyRecord[]).reverse() : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading)
    return (
      <div className="flex-1 flex items-center justify-center text-zinc-500">
        Loading…
      </div>
    );

  return (
    <div className="flex-1 flex flex-col max-w-4xl w-full mx-auto px-4 py-8 gap-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Application History</h1>
        <p className="text-zinc-500 text-sm mt-1">
          {records.length} application{records.length !== 1 ? "s" : ""} logged.
        </p>
      </div>

      {records.length === 0 ? (
        <div className="text-zinc-600 text-sm text-center mt-8">
          No applications yet. Go search for jobs and click Apply!
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {records.map((r, i) => {
            const [label, cls] = badge(r);
            return (
              <div
                key={`${r.job_source}:${r.job_id}:${i}`}
                className="border border-zinc-800 rounded-lg p-4 flex flex-col gap-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <a
                      href={r.apply_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-semibold text-white hover:text-indigo-400 transition-colors"
                    >
                      {r.job_title}
                    </a>
                    <div className="text-sm text-zinc-400 mt-0.5">
                      {r.company}
                      <span className="ml-2 text-zinc-600 text-xs uppercase tracking-wider">
                        {r.job_source}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}
                    >
                      {label}
                    </span>
                    {r.dry_run && (
                      <span className="text-xs px-2 py-0.5 rounded-full text-zinc-400 bg-zinc-800">
                        dry run
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex flex-wrap gap-4 text-xs text-zinc-500">
                  <span>{fmtDate(r.sent_at)}</span>
                  <span>{r.steps_taken} steps</span>
                  {r.final_url && (
                    <a
                      href={r.final_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-indigo-400 hover:underline"
                    >
                      final page
                    </a>
                  )}
                </div>
                {r.error_message && (
                  <div className="text-xs text-red-400 bg-red-950/30 border border-red-900/40 rounded px-2 py-1">
                    {r.error_message}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
