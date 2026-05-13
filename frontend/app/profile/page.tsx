"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "";

type Profile = {
  full_name: string;
  email: string;
  phone: string;
  location_city: string;
  location_state: string;
  location_country: string;
  linkedin_url: string;
  github_url: string;
  portfolio_url: string;
  work_auth_status: string;
  requires_visa_sponsorship_now_or_future: boolean;
  gender: string;
  ethnicity: string;
  veteran_status: string;
  disability_status: string;
  salary_expectation_usd: number | null;
  earliest_start_date: string;
  willing_to_relocate: boolean;
  how_did_you_hear: string;
  pronouns: string;
};

const WORK_AUTH_OPTIONS = [
  "us_citizen",
  "permanent_resident",
  "h1b",
  "f1_opt",
  "tn_visa",
  "other_authorized",
  "needs_sponsorship",
];

const GENDER_OPTIONS = ["male", "female", "non_binary", "prefer_not_to_say"];
const ETHNICITY_OPTIONS = [
  "hispanic_or_latino",
  "white",
  "black_or_african_american",
  "asian",
  "native_american_or_alaska_native",
  "native_hawaiian_or_pacific_islander",
  "two_or_more_races",
  "prefer_not_to_say",
];
const VETERAN_OPTIONS = ["veteran", "not_a_veteran", "prefer_not_to_say"];
const DISABILITY_OPTIONS = ["has_disability", "no_disability", "prefer_not_to_say"];

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs text-zinc-400 uppercase tracking-wider">
        {label}
      </label>
      {children}
    </div>
  );
}

const inputCls =
  "px-3 py-2 rounded bg-zinc-900 border border-zinc-700 text-white placeholder-zinc-500 focus:outline-none focus:border-indigo-500 text-sm";

const selectCls =
  "px-3 py-2 rounded bg-zinc-900 border border-zinc-700 text-white focus:outline-none focus:border-indigo-500 text-sm";

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [msgError, setMsgError] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/profile`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) setProfile(data as Profile);
        else
          setProfile({
            full_name: "",
            email: "",
            phone: "",
            location_city: "",
            location_state: "",
            location_country: "US",
            linkedin_url: "",
            github_url: "",
            portfolio_url: "",
            work_auth_status: "us_citizen",
            requires_visa_sponsorship_now_or_future: false,
            gender: "prefer_not_to_say",
            ethnicity: "prefer_not_to_say",
            veteran_status: "prefer_not_to_say",
            disability_status: "prefer_not_to_say",
            salary_expectation_usd: null,
            earliest_start_date: "",
            willing_to_relocate: false,
            how_did_you_hear: "",
            pronouns: "",
          });
        setLoading(false);
      });
  }, []);

  function update<K extends keyof Profile>(key: K, val: Profile[K]) {
    setProfile((p) => (p ? { ...p, [key]: val } : p));
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!profile) return;
    setSaving(true);
    setMsg("");
    try {
      const res = await fetch(`${API}/api/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profile),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(d.detail ?? "Save failed");
      }
      setMsg("Saved.");
      setMsgError(false);
    } catch (err: unknown) {
      setMsg(String(err));
      setMsgError(true);
    } finally {
      setSaving(false);
    }
  }

  if (loading)
    return (
      <div className="flex-1 flex items-center justify-center text-zinc-500">
        Loading…
      </div>
    );

  if (!profile) return null;

  return (
    <div className="flex-1 flex flex-col max-w-2xl w-full mx-auto px-4 py-8 gap-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Profile</h1>
        <p className="text-zinc-500 text-sm mt-1">
          Your personal info is used to fill ATS forms automatically.
        </p>
      </div>

      <form onSubmit={handleSave} className="flex flex-col gap-5">
        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-zinc-300 border-b border-zinc-800 pb-1">
            Identity
          </h2>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Full name">
              <input
                className={inputCls}
                value={profile.full_name}
                onChange={(e) => update("full_name", e.target.value)}
                required
              />
            </Field>
            <Field label="Email">
              <input
                type="email"
                className={inputCls}
                value={profile.email}
                onChange={(e) => update("email", e.target.value)}
                required
              />
            </Field>
            <Field label="Phone (with country code)">
              <input
                className={inputCls}
                placeholder="+1 555 123 4567"
                value={profile.phone}
                onChange={(e) => update("phone", e.target.value)}
                required
              />
            </Field>
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-zinc-300 border-b border-zinc-800 pb-1">
            Location
          </h2>
          <div className="grid grid-cols-3 gap-3">
            <Field label="City">
              <input
                className={inputCls}
                value={profile.location_city}
                onChange={(e) => update("location_city", e.target.value)}
                required
              />
            </Field>
            <Field label="State">
              <input
                className={inputCls}
                placeholder="CA"
                value={profile.location_state}
                onChange={(e) => update("location_state", e.target.value)}
                required
              />
            </Field>
            <Field label="Country">
              <input
                className={inputCls}
                placeholder="US"
                value={profile.location_country}
                onChange={(e) => update("location_country", e.target.value)}
                required
              />
            </Field>
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-zinc-300 border-b border-zinc-800 pb-1">
            Links
          </h2>
          <div className="grid grid-cols-1 gap-3">
            <Field label="LinkedIn URL">
              <input
                type="url"
                className={inputCls}
                placeholder="https://linkedin.com/in/..."
                value={profile.linkedin_url ?? ""}
                onChange={(e) => update("linkedin_url", e.target.value)}
              />
            </Field>
            <Field label="GitHub URL">
              <input
                type="url"
                className={inputCls}
                placeholder="https://github.com/..."
                value={profile.github_url ?? ""}
                onChange={(e) => update("github_url", e.target.value)}
              />
            </Field>
            <Field label="Portfolio URL">
              <input
                type="url"
                className={inputCls}
                placeholder="https://..."
                value={profile.portfolio_url ?? ""}
                onChange={(e) => update("portfolio_url", e.target.value)}
              />
            </Field>
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-zinc-300 border-b border-zinc-800 pb-1">
            Work Authorization
          </h2>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Status">
              <select
                className={selectCls}
                value={profile.work_auth_status}
                onChange={(e) => update("work_auth_status", e.target.value)}
              >
                {WORK_AUTH_OPTIONS.map((o) => (
                  <option key={o} value={o}>
                    {o.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Requires sponsorship?">
              <label className="flex items-center gap-2 mt-2 cursor-pointer">
                <input
                  type="checkbox"
                  className="accent-indigo-500 w-4 h-4"
                  checked={profile.requires_visa_sponsorship_now_or_future}
                  onChange={(e) =>
                    update(
                      "requires_visa_sponsorship_now_or_future",
                      e.target.checked
                    )
                  }
                />
                <span className="text-sm text-zinc-300">
                  Now or in the future
                </span>
              </label>
            </Field>
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-zinc-300 border-b border-zinc-800 pb-1">
            EEOC Disclosures (defaults to prefer not to say)
          </h2>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Gender">
              <select
                className={selectCls}
                value={profile.gender}
                onChange={(e) => update("gender", e.target.value)}
              >
                {GENDER_OPTIONS.map((o) => (
                  <option key={o} value={o}>
                    {o.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Ethnicity">
              <select
                className={selectCls}
                value={profile.ethnicity}
                onChange={(e) => update("ethnicity", e.target.value)}
              >
                {ETHNICITY_OPTIONS.map((o) => (
                  <option key={o} value={o}>
                    {o.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Veteran status">
              <select
                className={selectCls}
                value={profile.veteran_status}
                onChange={(e) => update("veteran_status", e.target.value)}
              >
                {VETERAN_OPTIONS.map((o) => (
                  <option key={o} value={o}>
                    {o.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Disability status">
              <select
                className={selectCls}
                value={profile.disability_status}
                onChange={(e) => update("disability_status", e.target.value)}
              >
                {DISABILITY_OPTIONS.map((o) => (
                  <option key={o} value={o}>
                    {o.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-zinc-300 border-b border-zinc-800 pb-1">
            Logistics
          </h2>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Salary expectation (USD/year)">
              <input
                type="number"
                className={inputCls}
                placeholder="Leave blank for 'Negotiable'"
                value={profile.salary_expectation_usd ?? ""}
                onChange={(e) =>
                  update(
                    "salary_expectation_usd",
                    e.target.value ? parseInt(e.target.value) : null
                  )
                }
              />
            </Field>
            <Field label="Earliest start date">
              <input
                type="date"
                className={inputCls}
                value={profile.earliest_start_date ?? ""}
                onChange={(e) => update("earliest_start_date", e.target.value)}
              />
            </Field>
            <Field label="Willing to relocate?">
              <label className="flex items-center gap-2 mt-2 cursor-pointer">
                <input
                  type="checkbox"
                  className="accent-indigo-500 w-4 h-4"
                  checked={profile.willing_to_relocate}
                  onChange={(e) => update("willing_to_relocate", e.target.checked)}
                />
                <span className="text-sm text-zinc-300">Yes</span>
              </label>
            </Field>
            <Field label="Pronouns">
              <input
                className={inputCls}
                placeholder="e.g. he/him"
                value={profile.pronouns ?? ""}
                onChange={(e) => update("pronouns", e.target.value)}
              />
            </Field>
          </div>
        </section>

        <div className="flex items-center gap-4 pt-2">
          <button
            type="submit"
            disabled={saving}
            className="px-5 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed font-medium transition-colors"
          >
            {saving ? "Saving…" : "Save Profile"}
          </button>
          {msg && (
            <span className={`text-sm ${msgError ? "text-red-400" : "text-emerald-400"}`}>
              {msg}
            </span>
          )}
        </div>
      </form>
    </div>
  );
}
