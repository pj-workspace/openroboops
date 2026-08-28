"use client";

import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  post,
  type Audit,
  type Collection,
  type Command,
  type Episode,
  type Robot,
  type SyncJob,
  type Telemetry,
  type User,
} from "@/lib/api";

type View = "overview" | "data" | "collection" | "operations" | "audit";
type Json = Record<string, unknown>;

const views: Array<{ id: View; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "data", label: "Data" },
  { id: "collection", label: "Collection" },
  { id: "operations", label: "Operations" },
  { id: "audit", label: "Audit" },
];

const safeCommands = [
  ["clear_fault", "Clear faults", "Clear recoverable faults without motion."],
  ["restart_stack", "Restart collection stack", "Restart the robot-side collection services."],
  ["save_reset_pose", "Save reset pose", "Save the current arm pose as its reset target."],
  ["reset_arm", "Reset one arm", "Move one arm to its previously saved pose."],
] as const;

function asObject(value: unknown): Json {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Json) : {};
}

function text(value: unknown, fallback = "—"): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : fallback;
}

function bool(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function bytes(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1000 && unit < units.length - 1) { size /= 1000; unit += 1; }
  return `${size.toFixed(unit > 1 ? 1 : 0)} ${units[unit]}`;
}

function date(value: string | null | undefined): string {
  if (!value) return "Never";
  return new Intl.DateTimeFormat(undefined, {
    month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(new Date(value));
}

function Icon({ name }: { name: string }) {
  const paths: Record<string, ReactNode> = {
    overview: <><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></>,
    data: <><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></>,
    collection: <><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/></>,
    operations: <path d="M14.7 6.3a4 4 0 0 0-5 5L3 18l3 3 6.7-6.7a4 4 0 0 0 5-5l-2.5 2.5-3-3z"/>,
    audit: <><path d="M6 3h12v18H6z"/><path d="M9 8h6M9 12h6M9 16h4"/></>,
    robot: <><rect x="5" y="7" width="14" height="11" rx="3"/><path d="M12 3v4M8 12h.01M16 12h.01M9 18v3M15 18v3"/></>,
    plus: <path d="M12 5v14M5 12h14"/>,
    refresh: <><path d="M20 6v5h-5M4 18v-5h5"/><path d="M18 9a7 7 0 0 0-12-2L4 11M6 15a7 7 0 0 0 12 2l2-4"/></>,
    logout: <><path d="M10 4H4v16h6M14 8l4 4-4 4M8 12h10"/></>,
  };
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

function Dot({ online }: { online: boolean }) {
  return <span className={`status-dot ${online ? "online" : "offline"}`} />;
}

function Badge({ tone = "neutral", children }: { tone?: string; children: ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

function AuthGate({ onReady }: { onReady: (user: User) => void }) {
  const [mode, setMode] = useState<"loading" | "setup" | "login">("loading");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<User>("/api/v1/auth/me").then(onReady).catch(async () => {
      const status = await api<{ setup_required: boolean }>("/api/v1/auth/setup-status");
      setMode(status.setup_required ? "setup" : "login");
    });
  }, [onReady]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError("");
    const form = new FormData(event.currentTarget);
    const credentials = { username: String(form.get("username")), password: String(form.get("password")) };
    try {
      const payload = mode === "setup"
        ? { ...credentials, bootstrap_token: String(form.get("bootstrapToken")) }
        : credentials;
      const result = await post<{ user: User }>(`/api/v1/auth/${mode}`, payload);
      onReady(result.user);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Authentication failed");
    } finally { setBusy(false); }
  }

  if (mode === "loading") {
    return <div className="boot-screen"><span className="spinner" />Loading control plane…</div>;
  }
  return <main className="auth-page"><section className="auth-card">
    <div className="brand-mark"><Icon name="robot" /></div>
    <p className="eyebrow">OPEN SOURCE ROBOT OPERATIONS</p>
    <h1>{mode === "setup" ? "Initialize OpenRoboOps" : "Welcome back"}</h1>
    <p className="muted">{mode === "setup"
      ? "Use the one-time token printed by the API container, then create the administrator account."
      : "Sign in to access fleet telemetry, datasets, and safety-gated operations."}</p>
    <form onSubmit={submit} className="form-stack">
      {mode === "setup" && <label>Bootstrap token<input name="bootstrapToken" required autoComplete="off" /></label>}
      <label>Username<input name="username" defaultValue="admin" required autoComplete="username" /></label>
      <label>Password<input name="password" type="password" minLength={12} required autoComplete={mode === "setup" ? "new-password" : "current-password"} /></label>
      {error && <p className="form-error">{error}</p>}
      <button className="button primary" disabled={busy}>{busy ? "Working…" : mode === "setup" ? "Create administrator" : "Sign in"}</button>
    </form>
  </section></main>;
}

function AddRobot({ onClose, onCreated }: { onClose: () => void; onCreated: (robot: Robot) => void }) {
  const [adapter, setAdapter] = useState<"simulator" | "a2d">("simulator");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true); setError("");
    const connection = adapter === "simulator" ? { seed: String(form.get("seed") || "local-demo") } : {
      host: String(form.get("host")), port: Number(form.get("port") || 22),
      username: String(form.get("sshUsername")), data_root: String(form.get("dataRoot")),
      known_hosts_path: String(form.get("knownHosts")), private_key_path: String(form.get("privateKey")),
      collector_host: "127.0.0.1", collector_port: 8888,
    };
    try {
      const robot = await post<Robot>("/api/v1/robots", {
        name: String(form.get("name")), model: String(form.get("model")), adapter_type: adapter,
        connection, observe_only: true, enabled_commands: [],
      });
      onCreated(robot);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not add robot"); }
    finally { setBusy(false); }
  }
  return <div className="modal-backdrop" onMouseDown={onClose}><section className="modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
    <div className="section-heading"><div><p className="eyebrow">FLEET REGISTRY</p><h2>Add a robot</h2></div><button className="icon-button" onClick={onClose}>×</button></div>
    <form className="form-grid" onSubmit={submit}>
      <label>Name<input name="name" placeholder="Lab G1" required /></label>
      <label>Model<input name="model" placeholder="AGI G1" required /></label>
      <label>Adapter<select value={adapter} onChange={(event) => setAdapter(event.target.value as "simulator" | "a2d")}><option value="simulator">Simulator</option><option value="a2d">A2D / AGI G1</option></select></label>
      {adapter === "simulator" ? <label>Seed<input name="seed" defaultValue="local-demo" /></label> : <>
        <label>SSH host<input name="host" placeholder="robot.lan" required /></label>
        <label>SSH port<input name="port" type="number" defaultValue="22" required /></label>
        <label>SSH username<input name="sshUsername" required /></label>
        <label>Data root<input name="dataRoot" defaultValue="/data/record" required /></label>
        <label className="wide">Pinned known_hosts file<input name="knownHosts" placeholder="/run/secrets/robot_known_hosts" required /></label>
        <label className="wide">Private key file<input name="privateKey" placeholder="/run/secrets/robot_key" required /></label>
      </>}
      <div className="notice wide">New robots are observe-only. Credentials remain server-side and are never returned to this browser.</div>
      {error && <p className="form-error wide">{error}</p>}
      <div className="modal-actions wide"><button type="button" className="button" onClick={onClose}>Cancel</button><button className="button primary" disabled={busy}>{busy ? "Adding…" : "Add robot"}</button></div>
    </form>
  </section></div>;
}

function Overview({ robot }: { robot: Robot }) {
  const [history, setHistory] = useState<Telemetry[]>([]);
  useEffect(() => {
    api<Telemetry[]>(`/api/v1/robots/${robot.id}/telemetry?limit=30`).then(setHistory).catch(() => setHistory([]));
  }, [robot.id]);
  const status = asObject(robot.status);
  const battery = asObject(status.battery); const disk = asObject(status.disk);
  const collision = asObject(status.collisionProtection); const poses = asObject(status.resetPoses);
  const services = asObject(status.services); const bodyParams = asObject(status.bodyParams);
  const alerts = Array.isArray(status.alerts) ? status.alerts : [];
  return <>
    <div className="metric-grid">
      <article className="metric"><span>Battery</span><strong>{battery.available === false ? "Unavailable" : `${text(battery.percent)}%`}</strong><small>{text(battery.statusText, bool(battery.charging) ? "Charging" : "Not charging")}</small></article>
      <article className="metric"><span>Data disk</span><strong>{bytes(disk.free)} free</strong><small>{bytes(disk.used)} used of {bytes(disk.total)}</small></article>
      <article className="metric"><span>Collection stack</span><strong>{bool(asObject(status.stack).ready) ? "Ready" : "Not ready"}</strong><small>{bool(status.recording) ? "Recording now" : "Idle"}</small></article>
      <article className="metric"><span>Collision protection</span><strong>{bool(collision.enabled) ? "Enabled" : "Not confirmed"}</strong><small>Level {text(collision.level)}</small></article>
    </div>
    <div className="two-column"><section className="panel">
      <p className="eyebrow">RESET POSES</p><h2>Arm readiness</h2>
      {(["left", "right"] as const).map((side) => { const pose = asObject(poses[side]); const ready = bool(pose.available); return <div className="pose-row" key={side}><div className="arm-glyph">{side[0].toUpperCase()}</div><div><strong>{side[0].toUpperCase() + side.slice(1)} arm</strong><p>{ready ? "Saved reset pose available" : "No saved reset pose"}</p></div><Badge tone={ready ? "success" : "warning"}>{ready ? "Configured" : "Unavailable"}</Badge></div>; })}
    </section><section className="panel"><p className="eyebrow">SERVICES</p><h2>Robot-side health</h2>
      {Object.keys(services).length ? Object.entries(services).map(([name, value]) => <div className="service-row" key={name}><span>{name}</span><Badge tone={value === "active" ? "success" : "warning"}>{text(value)}</Badge></div>) : <Empty>No service telemetry reported.</Empty>}
    </section></div>
    <section className="panel"><div className="section-heading"><div><p className="eyebrow">ALERTS</p><h2>Active conditions</h2></div><Badge tone={alerts.length ? "danger" : "success"}>{alerts.length || "Clear"}</Badge></div>
      {alerts.length ? <div className="alert-list">{alerts.map((alert, index) => <div className="alert-item" key={index}>{text(alert)}</div>)}</div> : <Empty>No active alerts reported by the adapter.</Empty>}
    </section>
    <section className="panel"><div className="section-heading"><div><p className="eyebrow">BODY PARAMETERS</p><h2>Reported configuration</h2></div><Badge>{Object.keys(bodyParams).length} values</Badge></div>
      {Object.keys(bodyParams).length ? <div className="parameter-grid">{Object.entries(bodyParams).map(([name, value]) => <div key={name}><span>{name}</span><strong>{text(value)}</strong></div>)}</div> : <Empty>No body parameters reported.</Empty>}
    </section>
    <section className="panel"><div className="section-heading"><div><p className="eyebrow">PERSISTED TELEMETRY</p><h2>Status history</h2></div><Badge>{history.length} snapshots</Badge></div>
      {history.length ? <div className="history-chart" aria-label="Battery history">{history.slice().reverse().map((snapshot) => { const percent = Number(asObject(asObject(snapshot.payload).battery).percent); return <span key={`${snapshot.id}-${snapshot.recorded_at}`} style={{ height: `${Number.isFinite(percent) ? Math.max(5, percent) : 5}%` }} title={`${date(snapshot.recorded_at)} · ${Number.isFinite(percent) ? `${percent}%` : "battery unavailable"}`} />; })}</div> : <Empty>Status snapshots will appear after the worker persists telemetry.</Empty>}
    </section>
  </>;
}

function DataView({ robot, notify }: { robot: Robot; notify: (message: string) => void }) {
  const [episodes, setEpisodes] = useState<Episode[]>([]); const [jobs, setJobs] = useState<SyncJob[]>([]);
  const [busy, setBusy] = useState(false); const [filter, setFilter] = useState("all");
  const load = useCallback(async () => {
    const [episodeRows, syncRows] = await Promise.all([api<Episode[]>(`/api/v1/robots/${robot.id}/episodes`), api<SyncJob[]>(`/api/v1/sync-jobs?robot_id=${robot.id}`)]);
    setEpisodes(episodeRows); setJobs(syncRows);
  }, [robot.id]);
  useEffect(() => {
    // The request resolves asynchronously; this initializes server-backed view state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load().catch((error) => notify(error.message));
  }, [load, notify]);
  async function scan() { setBusy(true); try { setEpisodes(await post<Episode[]>(`/api/v1/robots/${robot.id}/episodes/scan`)); notify("Episode index refreshed from meta_info.json."); } catch (error) { notify(error instanceof Error ? error.message : "Scan failed"); } finally { setBusy(false); } }
  async function sync(episode: Episode) { try { await post(`/api/v1/episodes/${episode.id}/sync`); notify(`Sync queued for ${episode.uid}. Source data will not be deleted.`); await load(); } catch (error) { notify(error instanceof Error ? error.message : "Sync failed"); } }
  async function cancel(job: SyncJob) { try { await post(`/api/v1/sync-jobs/${job.id}/cancel`); notify("Queued sync cancelled. Source and target data were left untouched."); await load(); } catch (error) { notify(error instanceof Error ? error.message : "Cancellation failed"); } }
  const visible = episodes.filter((row) => filter === "all" || row.sync_status === filter || row.validation_status === filter || (filter === "aligned" && row.aligned));
  return <section className="panel table-panel"><div className="section-heading"><div><p className="eyebrow">DATASET CATALOG</p><h2>Episodes</h2><p className="muted">Indexed directly from each episode&apos;s meta_info.json.</p></div><div className="actions"><select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All episodes</option><option value="aligned">Aligned</option><option value="valid">Valid</option><option value="warning">Warnings</option><option value="completed">Synced</option><option value="not_synced">Not synced</option></select><button className="button" onClick={scan} disabled={busy}><Icon name="refresh" />{busy ? "Scanning…" : "Rescan"}</button></div></div>
    {visible.length ? <div className="table-wrap"><table><thead><tr><th>Episode</th><th>Task</th><th>Channels</th><th>Size / duration</th><th>Quality</th><th>Sync</th><th /></tr></thead><tbody>{visible.map((episode) => {
      const metadata = asObject(episode.metadata); const job = jobs.find((item) => item.episode_id === episode.id && ["queued", "running", "verifying"].includes(item.status));
      const inspection = asObject(metadata._openroboops); const fileTree = Array.isArray(inspection.file_tree) ? inspection.file_tree : []; const missing = Array.isArray(inspection.missing_items) ? inspection.missing_items : [];
      return <tr key={episode.id}><td><strong className="mono">{episode.uid}</strong><small>{date(episode.last_scanned_at)}</small>{fileTree.length > 0 && <details className="file-tree"><summary>{fileTree.length} files</summary>{fileTree.slice(0, 40).map((entry, index) => <span key={index}>{text(asObject(entry).path)}</span>)}{fileTree.length > 40 && <span>…and {fileTree.length - 40} more</span>}</details>}</td><td>{text(metadata.text, text(metadata.task_id))}</td><td><div className="chips">{episode.channels.map((channel) => <span key={channel}>{channel}</span>)}</div></td><td>{bytes(episode.file_size)}<small>{Math.round(episode.duration_seconds)} sec</small></td><td><Badge tone={episode.validation_status === "valid" ? "success" : "warning"}>{episode.validation_status}</Badge><small>{episode.aligned ? "aligned" : "not aligned"}</small>{missing.length > 0 && <small className="warning-text">Missing: {missing.map(String).join(", ")}</small>}</td><td>{job ? <><Badge tone="info">{job.status} {job.progress}%</Badge><div className="progress"><span style={{ width: `${job.progress}%` }} /></div></> : <Badge tone={episode.sync_status === "completed" ? "success" : "neutral"}>{episode.sync_status}</Badge>}</td><td>{job?.status === "queued" ? <button className="button small" onClick={() => cancel(job)}>Cancel</button> : <button className="button small" onClick={() => sync(episode)} disabled={Boolean(job)}>Sync</button>}</td></tr>;
    })}</tbody></table></div> : <Empty>No episodes match this filter.</Empty>}
  </section>;
}

function CollectionView({ robot, notify }: { robot: Robot; notify: (message: string) => void }) {
  const [rows, setRows] = useState<Collection[]>([]); const [busy, setBusy] = useState(false);
  const load = useCallback(() => api<Collection[]>(`/api/v1/robots/${robot.id}/collections`).then(setRows), [robot.id]);
  useEffect(() => { load().catch((error) => notify(error.message)); }, [load, notify]);
  async function start(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = new FormData(event.currentTarget); setBusy(true); try { await post(`/api/v1/robots/${robot.id}/collections`, { name: String(form.get("name")), planned_duration_seconds: Number(form.get("duration")) }); notify("Collection started and the collector UID was persisted."); await load(); event.currentTarget.reset(); } catch (error) { notify(error instanceof Error ? error.message : "Collection failed"); } finally { setBusy(false); } }
  async function stop(id: string) { try { await post(`/api/v1/collections/${id}/stop`); notify("Collection stopped; indexing will resume automatically."); await load(); } catch (error) { notify(error instanceof Error ? error.message : "Stop failed"); } }
  return <div className="two-column collection-layout"><section className="panel"><p className="eyebrow">LOCAL ORCHESTRATION</p><h2>Start collection</h2><p className="muted">Allocates local task/job IDs and preserves the collector UID. No vendor upload, discard, or auto-cleanup call is used.</p>
    <form className="form-stack" onSubmit={start}><label>Task name<input name="name" placeholder="pick-and-place calibration" required minLength={2} /></label><label>Planned duration<select name="duration" defaultValue="60"><option value="30">30 seconds</option><option value="60">1 minute</option><option value="300">5 minutes</option><option value="900">15 minutes</option></select></label><button className="button primary" disabled={busy || robot.observe_only || !robot.online}>{busy ? "Starting…" : "Start collection"}</button>{robot.observe_only && <p className="form-hint">Disabled while this robot is observe-only.</p>}</form>
  </section><section className="panel"><div className="section-heading"><div><p className="eyebrow">SESSIONS</p><h2>Recent collection jobs</h2></div><button className="icon-button" onClick={() => load()}><Icon name="refresh" /></button></div>
    {rows.length ? <div className="session-list">{rows.map((row) => <article key={row.id}><div><strong>{row.name}</strong><p className="mono">{row.record_uid ?? `local job ${row.job_id}`}</p><small>{date(row.started_at)} · {row.planned_duration_seconds ?? "manual"} sec</small></div><div><Badge tone={row.status === "completed" ? "success" : row.status === "failed" ? "danger" : "info"}>{row.status}</Badge>{["starting", "recording", "stopping"].includes(row.status) && <button className="button small" onClick={() => stop(row.id)}>Stop</button>}</div></article>)}</div> : <Empty>No collection sessions yet.</Empty>}
  </section></div>;
}

function OperationsView({ robot, notify }: { robot: Robot; notify: (message: string) => void }) {
  const [password, setPassword] = useState(""); const [confirmed, setConfirmed] = useState(false);
  const [side, setSide] = useState<"left" | "right">("left"); const [busy, setBusy] = useState("");
  const [commands, setCommands] = useState<Command[]>([]); const status = asObject(robot.status);
  const selectedPose = asObject(asObject(status.resetPoses)[side]);
  const load = useCallback(() => api<Command[]>(`/api/v1/commands?robot_id=${robot.id}`).then(setCommands), [robot.id]);
  useEffect(() => { load().catch((error) => notify(error.message)); }, [load, notify]);
  async function execute(type: string) {
    setBusy(type);
    try {
      const freshRobot = await api<Robot>(`/api/v1/robots/${robot.id}`);
      const lease = await post<{ id: string }>(`/api/v1/robots/${robot.id}/control-leases`, { password, physical_safety_confirmed: confirmed });
      await post("/api/v1/commands", { robotId: robot.id, type, params: ["save_reset_pose", "reset_arm"].includes(type) ? { side } : {}, idempotencyKey: crypto.randomUUID(), expectedRevision: freshRobot.revision, controlLeaseId: lease.id });
      setPassword(""); setConfirmed(false); notify(`${type} queued. The worker will repeat all fail-closed checks.`); await load();
    } catch (error) { notify(error instanceof Error ? error.message : "Command rejected"); }
    finally { setBusy(""); }
  }
  return <div className="operations-grid"><section className="panel safety-panel"><p className="eyebrow">SAFETY GATE</p><h2>Authorize one operation</h2><p className="muted">A fresh password check creates a 60-second exclusive control lease. Robot status must be online, fresh, idle, collision-protected, and positively free of VR input.</p><label>Administrator password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label><label className="check"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>I am physically present, the work area is clear, and the physical emergency stop is reachable.</span></label><div className="segmented"><button className={side === "left" ? "active" : ""} onClick={() => setSide("left")}>Left arm</button><button className={side === "right" ? "active" : ""} onClick={() => setSide("right")}>Right arm</button></div><div className="notice danger-note">Software controls are not an emergency stop. Keep the physical emergency stop available for every real movement test.</div></section>
    <section className="panel"><p className="eyebrow">PRESET OPERATIONS</p><h2>Command catalog</h2><div className="command-list">{safeCommands.map(([type, label, description]) => { const enabled = robot.enabled_commands.includes(type) && robot.capabilities.includes(type); const poseMissing = type === "reset_arm" && !bool(selectedPose.available); return <article key={type}><div><strong>{label}{["save_reset_pose", "reset_arm"].includes(type) ? ` · ${side}` : ""}</strong><p>{description}</p>{!enabled && <small>Not enabled in this deployment profile.</small>}{poseMissing && <small>No saved {side} arm pose is available.</small>}</div><button className="button" disabled={!enabled || !password || !confirmed || Boolean(busy) || poseMissing} onClick={() => execute(type)}>{busy === type ? "Authorizing…" : "Execute"}</button></article>; })}</div></section>
    <section className="panel wide-panel"><div className="section-heading"><div><p className="eyebrow">COMMAND HISTORY</p><h2>Latest results</h2></div><button className="icon-button" onClick={() => load()}><Icon name="refresh" /></button></div>{commands.length ? <div className="audit-list">{commands.slice(0, 10).map((row) => <div key={row.id}><span><strong>{row.command_type}</strong><small>{date(row.created_at)}</small></span><Badge tone={row.status === "completed" ? "success" : row.status === "failed" ? "danger" : "info"}>{row.status}</Badge></div>)}</div> : <Empty>No commands have been requested.</Empty>}</section>
  </div>;
}

function AuditView({ robot, notify }: { robot: Robot; notify: (message: string) => void }) {
  const [rows, setRows] = useState<Audit[]>([]);
  useEffect(() => { api<Audit[]>(`/api/v1/audit?robot_id=${robot.id}`).then(setRows).catch((error) => notify(error.message)); }, [robot.id, notify]);
  return <section className="panel"><div className="section-heading"><div><p className="eyebrow">IMMUTABLE HISTORY</p><h2>Operations audit</h2></div><Badge>{rows.length} records</Badge></div>{rows.length ? <div className="audit-list detailed">{rows.map((row) => <div key={row.id}><span><strong>{row.action}</strong><small>{row.target || "control plane"} · {date(row.created_at)}</small></span><Badge tone={row.status === "ok" ? "success" : "danger"}>{row.status}</Badge></div>)}</div> : <Empty>No audit records for this robot.</Empty>}</section>;
}

export default function Console() {
  const [user, setUser] = useState<User | null>(null); const [robots, setRobots] = useState<Robot[]>([]);
  const [selectedId, setSelectedId] = useState(""); const [view, setView] = useState<View>("overview");
  const [showAdd, setShowAdd] = useState(false); const [notice, setNotice] = useState(""); const [busy, setBusy] = useState(false);
  const loadRobots = useCallback(async () => { const rows = await api<Robot[]>("/api/v1/robots"); setRobots(rows); setSelectedId((current) => current && rows.some((robot) => robot.id === current) ? current : rows[0]?.id ?? ""); }, []);
  const selected = useMemo(() => robots.find((robot) => robot.id === selectedId), [robots, selectedId]);
  useEffect(() => {
    if (!user) return;
    // The request resolves asynchronously; this initializes server-backed fleet state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadRobots().catch((error) => setNotice(error.message));
  }, [user, loadRobots]);
  useEffect(() => {
    if (!user) return;
    const socket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/v1/ws`);
    socket.onmessage = (event) => { const payload = JSON.parse(event.data) as { robots?: Robot[]; events?: Array<{ type: string; payload: Json }> }; if (payload.robots) setRobots(payload.robots); const latest = payload.events?.at(-1); if (latest && latest.type !== "robot.status") setNotice(`${latest.type}: ${text(latest.payload.status, "updated")}`); };
    return () => socket.close();
  }, [user]);
  useEffect(() => { if (!notice) return; const timer = window.setTimeout(() => setNotice(""), 6500); return () => window.clearTimeout(timer); }, [notice]);
  async function probe() { if (!selected) return; setBusy(true); try { await post(`/api/v1/robots/${selected.id}/probe`); await loadRobots(); setNotice("Connection probe completed."); } catch (error) { setNotice(error instanceof Error ? error.message : "Probe failed"); } finally { setBusy(false); } }
  async function logout() { try { await post("/api/v1/auth/logout"); } finally { setUser(null); setRobots([]); } }
  if (!user) return <AuthGate onReady={setUser} />;
  return <div className="app-shell"><aside className="sidebar">
    <div className="brand"><div className="brand-mark small"><Icon name="robot" /></div><div><strong>OpenRoboOps</strong><span>Fleet control plane</span></div></div>
    <div className="sidebar-label"><span>ROBOTS · {robots.length}</span><button className="icon-button" onClick={() => setShowAdd(true)} title="Add robot"><Icon name="plus" /></button></div>
    <div className="robot-list">{robots.map((robot) => <button key={robot.id} className={selectedId === robot.id ? "selected" : ""} onClick={() => { setSelectedId(robot.id); setView("overview"); }}><div className="robot-avatar"><Icon name="robot" /></div><span><strong>{robot.name}</strong><small><Dot online={robot.online} />{robot.online ? "Online" : "Offline"} · {robot.model}</small></span></button>)}</div>
    <div className="sidebar-footer"><div className="user"><span>{user.username.slice(0, 2).toUpperCase()}</span><div><strong>{user.username}</strong><small>Administrator</small></div></div><button className="icon-button" onClick={logout} title="Sign out"><Icon name="logout" /></button></div>
  </aside><main className="workspace">{selected ? <>
    <header className="topbar"><div><div className="title-line"><h1>{selected.name}</h1><Badge tone={selected.online ? "success" : "danger"}><Dot online={selected.online} />{selected.online ? "Online" : "Offline"}</Badge>{selected.observe_only && <Badge tone="info">Observe only</Badge>}</div><p>{selected.model} · {selected.adapter_type} adapter · last seen {date(selected.last_seen)}</p></div><button className="button" onClick={probe} disabled={busy}><Icon name="refresh" />{busy ? "Probing…" : "Probe connection"}</button></header>
    <nav className="tabs">{views.map((item) => <button key={item.id} className={view === item.id ? "active" : ""} onClick={() => setView(item.id)}><Icon name={item.id} />{item.label}</button>)}</nav>
    <div className="content">{view === "overview" && <Overview robot={selected} />}{view === "data" && <DataView robot={selected} notify={setNotice} />}{view === "collection" && <CollectionView robot={selected} notify={setNotice} />}{view === "operations" && <OperationsView robot={selected} notify={setNotice} />}{view === "audit" && <AuditView robot={selected} notify={setNotice} />}</div>
  </> : <div className="no-robot"><div className="brand-mark"><Icon name="robot" /></div><h1>Register your first robot</h1><p>Start with the simulator or add an A2D robot in observe-only mode.</p><button className="button primary" onClick={() => setShowAdd(true)}><Icon name="plus" />Add robot</button></div>}</main>
    {notice && <div className="toast">{notice}</div>}
    {showAdd && <AddRobot onClose={() => setShowAdd(false)} onCreated={(robot) => { setRobots((items) => [...items, robot]); setSelectedId(robot.id); setShowAdd(false); setNotice("Robot registered in observe-only mode."); }} />}
  </div>;
}
