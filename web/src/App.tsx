import { useEffect, useState } from "react";

type Health = {
  status: string;
  odoo: string;
  odoo_version: string | null;
  version_matches_profile: boolean;
  profile_loaded: boolean;
};

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/healthz")
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return res.json() as Promise<Health>;
      })
      .then(setHealth)
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <main>
      <h1>Odoo Time Tracker</h1>
      {error && <p>Health check failed: {error}</p>}
      {!error && !health && <p>Checking health…</p>}
      {health && (
        <dl>
          <dt>status</dt>
          <dd>{health.status}</dd>
          <dt>odoo</dt>
          <dd>{health.odoo}</dd>
          <dt>odoo_version</dt>
          <dd>{health.odoo_version ?? "unknown"}</dd>
          <dt>version_matches_profile</dt>
          <dd>{String(health.version_matches_profile)}</dd>
          <dt>profile_loaded</dt>
          <dd>{String(health.profile_loaded)}</dd>
        </dl>
      )}
    </main>
  );
}
