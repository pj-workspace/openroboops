"use client";

import Image from "next/image";
import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  post,
  type Audit,
  type CameraPreview,
  type Collection,
  type Command,
  type Episode,
  type Robot,
  type SyncJob,
  type Telemetry,
  type User,
} from "@/lib/api";
import { I18nProvider, LanguageToggle, useI18n } from "@/lib/i18n";

type View = "overview" | "data" | "collection" | "operations" | "audit";
type Json = Record<string, unknown>;

const views: Array<{ id: View; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "data", label: "Data" },
  { id: "collection", label: "Collection" },
  { id: "operations", label: "Operations" },
  { id: "audit", label: "Audit" },
];

const cameraPreviewSlots = [
  { channel: "hand_left_color", label: "Left hand camera" },
  { channel: "head_color", label: "Head camera" },
  { channel: "hand_right_color", label: "Right hand camera" },
] as const;

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

function episodeCapturedAt(metadata: Json): string | null {
  const createTime = metadata.create_time;
  if (typeof createTime === "string" && createTime.trim()) {
    return createTime.includes("T") ? createTime : createTime.replace(" ", "T");
  }
  const clipStartTime = metadata.clip_start_time;
  if (typeof clipStartTime === "number" && Number.isFinite(clipStartTime)) {
    return new Date(clipStartTime * 1_000).toISOString();
  }
  return null;
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

function LoadingLabel({ children }: { children: ReactNode }) {
  return <span className="loading-label"><span className="button-spinner" aria-hidden="true" />{children}</span>;
}

function EpisodePreviewCard({ src, label }: { src: string; label: string }) {
  const { t } = useI18n();
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  return <article className="camera-card"><div className="camera-frame">
    {state !== "ready" && <span className="camera-unavailable">{state === "loading" ? <LoadingLabel>{t("Loading preview…")}</LoadingLabel> : t("Preview unavailable")}</span>}
    <Image src={src} alt={label} width={1280} height={720} unoptimized onLoad={() => setState("ready")} onError={() => setState("error")} style={state === "error" ? { display: "none" } : undefined} />
  </div><div className="camera-meta"><strong>{label}</strong></div></article>;
}

function AuthGate({ onReady }: { onReady: (user: User) => void }) {
  const { t } = useI18n();
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
      setError(reason instanceof Error ? reason.message : t("Authentication failed"));
    } finally { setBusy(false); }
  }

  if (mode === "loading") {
    return <div className="boot-screen"><span className="spinner" />{t("Loading control plane…")}</div>;
  }
  return <main className="auth-page"><section className="auth-card">
    <div className="auth-tools"><LanguageToggle /></div>
    <div className="brand-mark"><Icon name="robot" /></div>
    <p className="eyebrow">{t("Open source robot operations").toUpperCase()}</p>
    <h1>{mode === "setup" ? t("Initialize OpenRoboOps") : t("Welcome back")}</h1>
    <p className="muted">{mode === "setup"
      ? t("Use the one-time token printed by the API container, then create the administrator account.")
      : t("Sign in to access fleet telemetry, datasets, and safety-gated operations.")}</p>
    <form onSubmit={submit} className="form-stack">
      {mode === "setup" && <label>{t("Bootstrap token")}<input name="bootstrapToken" required autoComplete="off" /></label>}
      <label>{t("Username")}<input name="username" defaultValue="admin" required autoComplete="username" /></label>
      <label>{t("Password")}<input name="password" type="password" minLength={12} required autoComplete={mode === "setup" ? "new-password" : "current-password"} /></label>
      {error && <p className="form-error">{error}</p>}
      <button className="button primary" disabled={busy}>{busy ? t("Working…") : mode === "setup" ? t("Create administrator") : t("Sign in")}</button>
    </form>
  </section></main>;
}

function AddRobot({ onClose, onCreated }: { onClose: () => void; onCreated: (robot: Robot) => void }) {
  const { t } = useI18n();
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
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Could not add robot")); }
    finally { setBusy(false); }
  }
  return <div className="modal-backdrop" onMouseDown={onClose}><section className="modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
    <div className="section-heading"><div><p className="eyebrow">{t("Fleet registry").toUpperCase()}</p><h2>{t("Add a robot")}</h2></div><button className="icon-button" onClick={onClose}>×</button></div>
    <form className="form-grid" onSubmit={submit}>
      <label>{t("Name")}<input name="name" placeholder="Lab G1" required /></label>
      <label>{t("Model")}<input name="model" placeholder="AGI G1" required /></label>
      <label>{t("Adapter")}<select value={adapter} onChange={(event) => setAdapter(event.target.value as "simulator" | "a2d")}><option value="simulator">{t("Simulator")}</option><option value="a2d">A2D / AGI G1</option></select></label>
      {adapter === "simulator" ? <label>{t("Seed")}<input name="seed" defaultValue="local-demo" /></label> : <>
        <label>{t("SSH host")}<input name="host" placeholder="robot.lan" required /></label>
        <label>{t("SSH port")}<input name="port" type="number" defaultValue="22" required /></label>
        <label>{t("SSH username")}<input name="sshUsername" required /></label>
        <label>{t("Data root")}<input name="dataRoot" defaultValue="/data/record" required /></label>
        <label className="wide">{t("Pinned known_hosts file")}<input name="knownHosts" placeholder="/run/secrets/robot_known_hosts" required /></label>
        <label className="wide">{t("Private key file")}<input name="privateKey" placeholder="/run/secrets/robot_key" required /></label>
      </>}
      <div className="notice wide">{t("New robots are observe-only. Credentials remain server-side and are never returned to this browser.")}</div>
      {error && <p className="form-error wide">{error}</p>}
      <div className="modal-actions wide"><button type="button" className="button" onClick={onClose}>{t("Cancel")}</button><button className="button primary" disabled={busy}>{busy ? t("Adding…") : t("Add robot")}</button></div>
    </form>
  </section></div>;
}

function Overview({ robot }: { robot: Robot }) {
  const { t } = useI18n();
  const [history, setHistory] = useState<Telemetry[]>([]);
  useEffect(() => {
    api<Telemetry[]>(`/api/v1/robots/${robot.id}/telemetry?limit=30`).then(setHistory).catch(() => setHistory([]));
  }, [robot.id]);
  const status = asObject(robot.status);
  const battery = asObject(status.battery); const disk = asObject(status.disk);
  const collision = asObject(status.collisionProtection); const poses = asObject(status.resetPoses);
  const services = asObject(status.services); const bodyParams = asObject(status.bodyParams);
  const alerts = Array.isArray(status.alerts) ? status.alerts : [];
  const vrActive = typeof status.vrActive === "boolean" ? status.vrActive : null;
  return <>
    <div className="metric-grid">
      <article className="metric"><span>{t("Battery")}</span><strong>{battery.available === false ? t("Unavailable") : `${text(battery.percent)}%`}</strong><small>{text(battery.statusText, bool(battery.charging) ? t("Charging") : t("Not charging"))}</small></article>
      <article className="metric"><span>{t("Data disk")}</span><strong>{bytes(disk.free)} {t("free")}</strong><small>{bytes(disk.used)} {t("used")} · {bytes(disk.total)} {t("of")}</small></article>
      <article className="metric"><span>{t("Collection stack")}</span><strong>{bool(asObject(status.stack).ready) ? t("Ready") : t("Not ready")}</strong><small>{bool(status.recording) ? t("Recording now") : t("Idle")}</small></article>
      <article className="metric"><span>{t("Collision protection")}</span><strong>{bool(collision.enabled) ? t("Enabled") : t("Not confirmed")}</strong><small>{t("Level")} {text(collision.level)}</small></article>
      <article className="metric"><span>{t("PICO / VR")}</span><strong>{vrActive === true ? t("Active") : vrActive === false ? t("Idle") : t("Unknown")}</strong><small>{vrActive === true ? t("Live input detected") : vrActive === false ? t("No live input detected") : t("Detection unavailable")}</small></article>
    </div>
    <div className="two-column"><section className="panel">
      <p className="eyebrow">{t("Reset poses").toUpperCase()}</p><h2>{t("Arm readiness")}</h2>
      {(["left", "right"] as const).map((side) => { const pose = asObject(poses[side]); const ready = bool(pose.available); return <div className="pose-row" key={side}><div className="arm-glyph">{side[0].toUpperCase()}</div><div><strong>{t(side === "left" ? "Left arm" : "Right arm")}</strong><p>{ready ? t("Saved reset pose available") : t("No saved reset pose")}</p></div><Badge tone={ready ? "success" : "warning"}>{ready ? t("Configured") : t("Unavailable")}</Badge></div>; })}
    </section><section className="panel"><p className="eyebrow">{t("Services").toUpperCase()}</p><h2>{t("Robot-side health")}</h2>
      {Object.keys(services).length ? Object.entries(services).map(([name, value]) => <div className="service-row" key={name}><span>{name}</span><Badge tone={value === "active" ? "success" : "warning"}>{text(value)}</Badge></div>) : <Empty>{t("No service telemetry reported.")}</Empty>}
    </section></div>
    <section className="panel"><div className="section-heading"><div><p className="eyebrow">{t("Alerts").toUpperCase()}</p><h2>{t("Active conditions")}</h2></div><Badge tone={alerts.length ? "danger" : "success"}>{alerts.length || t("Clear")}</Badge></div>
      {alerts.length ? <div className="alert-list">{alerts.map((alert, index) => <div className="alert-item" key={index}>{t(text(alert))}</div>)}</div> : <Empty>{t("No active alerts reported by the adapter.")}</Empty>}
    </section>
    <section className="panel"><div className="section-heading"><div><p className="eyebrow">{t("Body parameters").toUpperCase()}</p><h2>{t("Reported configuration")}</h2></div><Badge>{Object.keys(bodyParams).length} {t("values")}</Badge></div>
      {Object.keys(bodyParams).length ? <div className="parameter-grid">{Object.entries(bodyParams).map(([name, value]) => <div key={name}><span>{name}</span><strong>{text(value)}</strong></div>)}</div> : <Empty>{t("No body parameters reported.")}</Empty>}
    </section>
    <section className="panel"><div className="section-heading"><div><p className="eyebrow">{t("Persisted telemetry").toUpperCase()}</p><h2>{t("Status history")}</h2></div><Badge>{history.length} {t("snapshots")}</Badge></div>
      {history.length ? <div className="history-chart" aria-label={t("Battery history")}>{history.slice().reverse().map((snapshot) => { const percent = Number(asObject(asObject(snapshot.payload).battery).percent); return <span key={`${snapshot.id}-${snapshot.recorded_at}`} style={{ height: `${Number.isFinite(percent) ? Math.max(5, percent) : 5}%` }} title={`${date(snapshot.recorded_at)} · ${Number.isFinite(percent) ? `${percent}%` : t("battery unavailable")}`} />; })}</div> : <Empty>{t("Status snapshots will appear after the worker persists telemetry.")}</Empty>}
    </section>
  </>;
}

function DataView({ robot, notify }: { robot: Robot; notify: (message: string) => void }) {
  const { t } = useI18n();
  const [episodes, setEpisodes] = useState<Episode[]>([]); const [jobs, setJobs] = useState<SyncJob[]>([]);
  const [busy, setBusy] = useState(false); const [filter, setFilter] = useState("all");
  const [managedId, setManagedId] = useState(""); const [deleteArmed, setDeleteArmed] = useState(false);
  const [deletePassword, setDeletePassword] = useState(""); const [deleteUid, setDeleteUid] = useState("");
  const [deleting, setDeleting] = useState(false); const [syncingId, setSyncingId] = useState("");
  const [cancellingId, setCancellingId] = useState("");
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
  async function sync(episode: Episode) { setSyncingId(episode.id); try { await post(`/api/v1/episodes/${episode.id}/sync`); notify(`Sync queued for ${episode.uid}. Source data will not be deleted.`); await load(); } catch (error) { notify(error instanceof Error ? error.message : "Sync failed"); } finally { setSyncingId(""); } }
  async function cancel(job: SyncJob) { setCancellingId(job.id); try { await post(`/api/v1/sync-jobs/${job.id}/cancel`); notify("Queued sync cancelled. Source and target data were left untouched."); await load(); } catch (error) { notify(error instanceof Error ? error.message : "Cancellation failed"); } finally { setCancellingId(""); } }
  function closeManager() { setManagedId(""); setDeleteArmed(false); setDeletePassword(""); setDeleteUid(""); }
  async function deleteEpisode(episode: Episode) {
    setDeleting(true);
    try {
      await post(`/api/v1/episodes/${episode.id}/delete`, { password: deletePassword, confirm_uid: deleteUid });
      notify(t("Episode data was deleted and audited."));
      closeManager();
      await load();
    } catch (error) { notify(error instanceof Error ? error.message : t("Deletion failed")); }
    finally { setDeleting(false); }
  }
  const visible = episodes.filter((row) => filter === "all" || row.sync_status === filter || row.validation_status === filter || (filter === "aligned" && row.aligned));
  const managed = episodes.find((episode) => episode.id === managedId);
  const managedJob = managed ? jobs.find((item) => item.episode_id === managed.id && ["queued", "running", "verifying"].includes(item.status)) : undefined;
  return <><section className="panel table-panel"><div className="section-heading"><div><p className="eyebrow">{t("Dataset catalog").toUpperCase()}</p><h2>{t("Episodes")}</h2><p className="muted">{t("Indexed directly from each episode's meta_info.json.")}</p></div><div className="actions"><select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">{t("All episodes")}</option><option value="aligned">{t("Aligned")}</option><option value="valid">{t("Valid")}</option><option value="warning">{t("Warnings")}</option><option value="completed">{t("Synced")}</option><option value="not_synced">{t("Not synced")}</option></select><button className="button" onClick={scan} disabled={busy}>{busy ? <LoadingLabel>{t("Scanning…")}</LoadingLabel> : <><Icon name="refresh" />{t("Rescan")}</>}</button></div></div>
    {visible.length ? <div className="table-wrap"><table><thead><tr><th>{t("Episode")}</th><th>{t("Task")}</th><th>{t("Channels")}</th><th>{t("Size / duration")}</th><th>{t("Quality")}</th><th>{t("Sync")}</th><th /></tr></thead><tbody>{visible.map((episode) => {
      const metadata = asObject(episode.metadata); const job = jobs.find((item) => item.episode_id === episode.id && ["queued", "running", "verifying"].includes(item.status));
      const inspection = asObject(metadata._openroboops); const fileTree = Array.isArray(inspection.file_tree) ? inspection.file_tree : []; const missing = Array.isArray(inspection.missing_items) ? inspection.missing_items : [];
      const capturedAt = episodeCapturedAt(metadata);
      return <tr key={episode.id}><td><strong className="mono">{episode.uid}</strong><small>{t("Collected")} {capturedAt ? date(capturedAt) : t("Unknown")}</small><small>{t("Last scanned")} {date(episode.last_scanned_at)}</small>{fileTree.length > 0 && <details className="file-tree"><summary>{fileTree.length} {t("files")}</summary>{fileTree.slice(0, 40).map((entry, index) => <span key={index}>{text(asObject(entry).path)}</span>)}{fileTree.length > 40 && <span>…{t("and {count} more", { count: fileTree.length - 40 })}</span>}</details>}</td><td>{text(metadata.text, text(metadata.task_id))}</td><td><div className="chips">{episode.channels.map((channel) => <span key={channel}>{channel}</span>)}</div></td><td>{bytes(episode.file_size)}<small>{Math.round(episode.duration_seconds)} {t("sec")}</small></td><td><Badge tone={episode.validation_status === "valid" ? "success" : "warning"}>{episode.validation_status}</Badge><small>{episode.aligned ? t("aligned") : t("not aligned")}</small>{missing.length > 0 && <small className="warning-text">{t("Missing")}: {missing.map(String).join(", ")}</small>}</td><td>{job ? <><Badge tone="info">{job.status} {job.progress}%</Badge><div className="progress"><span style={{ width: `${job.progress}%` }} /></div></> : <Badge tone={episode.sync_status === "completed" ? "success" : "neutral"}>{episode.sync_status}</Badge>}</td><td><div className="row-actions"><button className="button small" onClick={() => setManagedId(episode.id)}>{t("Manage")}</button>{job?.status === "queued" ? <button className="button small" onClick={() => cancel(job)} disabled={cancellingId === job.id}>{cancellingId === job.id ? <LoadingLabel>{t("Cancelling…")}</LoadingLabel> : t("Cancel")}</button> : <button className="button small" onClick={() => sync(episode)} disabled={Boolean(job) || episode.sync_status === "completed" || syncingId === episode.id}>{syncingId === episode.id ? <LoadingLabel>{t("Syncing…")}</LoadingLabel> : t("Sync")}</button>}</div></td></tr>;
    })}</tbody></table></div> : <Empty>{t("No episodes match this filter.")}</Empty>}
  </section>{managed && <div className="modal-backdrop" onMouseDown={closeManager}><section className="modal dataset-manager" role="dialog" aria-modal="true" aria-labelledby="dataset-manager-title" onMouseDown={(event) => event.stopPropagation()}>
    <div className="section-heading"><div><p className="eyebrow">{t("Dataset management").toUpperCase()}</p><h2 id="dataset-manager-title">{t("Episode details")}</h2><p className="mono muted">{managed.uid}</p></div><button className="icon-button" onClick={closeManager}>×</button></div>
    <div className="review-summary"><span><small>{t("Size")}</small><strong>{bytes(managed.file_size)}</strong></span><span><small>{t("Duration")}</small><strong>{Math.round(managed.duration_seconds)} {t("sec")}</strong></span><span><small>{t("Quality")}</small><strong>{managed.validation_status}</strong></span><span><small>{t("Sync")}</small><strong>{managedJob?.status ?? managed.sync_status}</strong></span></div>
    <div className="camera-grid review-camera-grid">{cameraPreviewSlots.map((slot) => <EpisodePreviewCard key={`${managed.id}-${slot.channel}`} src={`/api/v1/episodes/${managed.id}/preview/${slot.channel}?v=${encodeURIComponent(managed.last_scanned_at)}`} label={t(slot.label)} />)}</div>
    <div className="review-actions"><button className="button" onClick={() => sync(managed)} disabled={Boolean(managedJob) || managed.sync_status === "completed" || syncingId === managed.id}>{syncingId === managed.id ? <LoadingLabel>{t("Syncing…")}</LoadingLabel> : t("Sync")}</button><button className="button danger-button" onClick={() => setDeleteArmed(true)} disabled={Boolean(managedJob) || managed.sync_status === "completed" || deleting}>{t("Delete data")}</button></div>
    {managedJob && <div className="notice">{t("Cancel the active sync before deleting data.")}</div>}
    {managed.sync_status === "completed" && <div className="notice">{t("Central synchronized copies cannot be deleted in v0.1.")}</div>}
    {deleteArmed && <div className="delete-confirm"><div className="notice danger-note">{t("This permanently deletes the robot-side source data. Type the full UID and administrator password to continue.")}</div><label>{t("Confirm UID")}<input value={deleteUid} onChange={(event) => setDeleteUid(event.target.value)} placeholder={managed.uid} /></label><label>{t("Administrator password")}<input type="password" value={deletePassword} onChange={(event) => setDeletePassword(event.target.value)} autoComplete="current-password" /></label><div className="actions"><button className="button" onClick={() => setDeleteArmed(false)} disabled={deleting}>{t("Cancel")}</button><button className="button danger-button" onClick={() => deleteEpisode(managed)} disabled={deleteUid !== managed.uid || !deletePassword || deleting}>{deleting ? <LoadingLabel>{t("Deleting…")}</LoadingLabel> : t("Permanently delete")}</button></div></div>}
  </section></div>}</>;
}

function CollectionView({ robot, notify }: { robot: Robot; notify: (message: string) => void }) {
  const { t } = useI18n();
  const [rows, setRows] = useState<Collection[]>([]); const [busy, setBusy] = useState(false);
  const [episodes, setEpisodes] = useState<Episode[]>([]); const [reviewId, setReviewId] = useState("");
  const [deleteArmed, setDeleteArmed] = useState(false); const [deletePassword, setDeletePassword] = useState(""); const [deleteUid, setDeleteUid] = useState("");
  const [previews, setPreviews] = useState<CameraPreview[]>([]); const [previewError, setPreviewError] = useState("");
  const previousStatuses = useRef<Map<string, string> | null>(null);
  const load = useCallback(async () => {
    const [nextRows, nextEpisodes] = await Promise.all([
      api<Collection[]>(`/api/v1/robots/${robot.id}/collections`),
      api<Episode[]>(`/api/v1/robots/${robot.id}/episodes`),
    ]);
    if (previousStatuses.current) {
      const finished = nextRows.find((row) => row.record_uid && ["completed", "stopped", "failed"].includes(row.status) && ["starting", "recording", "stopping"].includes(previousStatuses.current?.get(row.id) ?? ""));
      if (finished) setReviewId(finished.id);
    }
    previousStatuses.current = new Map(nextRows.map((row) => [row.id, row.status]));
    setRows(nextRows); setEpisodes(nextEpisodes);
  }, [robot.id]);
  const loadPreviews = useCallback(async () => {
    try { setPreviews(await api<CameraPreview[]>(`/api/v1/robots/${robot.id}/camera-previews`)); setPreviewError(""); }
    catch (error) { setPreviewError(error instanceof Error ? error.message : "Camera preview unavailable"); }
  }, [robot.id]);
  useEffect(() => {
    load().catch((error) => notify(error.message));
    const interval = window.setInterval(() => load().catch((error) => notify(error.message)), 2_000);
    return () => window.clearInterval(interval);
  }, [load, notify]);
  useEffect(() => {
    // The request resolves asynchronously; this initializes server-backed camera state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadPreviews();
    const interval = window.setInterval(loadPreviews, 3_000);
    return () => window.clearInterval(interval);
  }, [loadPreviews]);
  async function start(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = new FormData(event.currentTarget); setBusy(true); try { await post(`/api/v1/robots/${robot.id}/collections`, { name: String(form.get("name")), planned_duration_seconds: Number(form.get("duration")) }); notify("Collection started and the collector UID was persisted."); await Promise.all([load(), loadPreviews()]); event.currentTarget.reset(); } catch (error) { notify(error instanceof Error ? error.message : "Collection failed"); } finally { setBusy(false); } }
  async function stop(id: string) { try { await post(`/api/v1/collections/${id}/stop`); notify("Collection stopped; indexing will resume automatically."); await load(); setReviewId(id); } catch (error) { notify(error instanceof Error ? error.message : "Stop failed"); } }
  async function forceStop(id: string) { try { await post(`/api/v1/collections/${id}/force-stop`); notify(t("Recorder was force-stopped; source data was preserved.")); await load(); setReviewId(id); } catch (error) { notify(error instanceof Error ? error.message : t("Force stop failed")); } }
  async function decide(decision: "keep" | "delete") {
    if (!reviewId) return;
    try {
      await post(`/api/v1/collections/${reviewId}/decision`, decision === "keep" ? { decision } : { decision, password: deletePassword, confirm_uid: deleteUid });
      notify(decision === "keep" ? t("Collection was kept.") : t("Collection data was deleted and audited."));
      setDeleteArmed(false); setDeletePassword(""); setDeleteUid(""); await load(); setReviewId("");
    } catch (error) { notify(error instanceof Error ? error.message : t("Review action failed")); }
  }
  const previewsByChannel = new Map(previews.map((preview) => [preview.channel, preview]));
  const review = rows.find((row) => row.id === reviewId);
  const reviewEpisode = episodes.find((episode) => episode.uid === review?.record_uid);
  return <div className="collection-page"><section className="panel camera-panel"><div className="section-heading"><div><p className="eyebrow">{t("Collector vision").toUpperCase()}</p><h2>{t("Camera preview")}</h2><p className="muted">{t("Frames are proxied through OpenRoboOps; robot addresses and credentials stay server-side.")}</p></div><button className="button small" onClick={loadPreviews}><Icon name="refresh" />{t("Refresh")}</button></div>
    {previewError && <div className="notice camera-error">{t("Camera preview unavailable")}: {previewError}</div>}
    <div className="camera-grid">{cameraPreviewSlots.map((slot) => {
      const preview = previewsByChannel.get(slot.channel);
      const available = Boolean(preview && (preview.stream_url || !preview.stale));
      return <article className={`camera-card${preview ? "" : " camera-card-placeholder"}`} key={slot.channel}><div className="camera-frame">{available && preview ? <Image src={preview.stream_url ?? preview.frame_url} alt={t(slot.label)} width={1280} height={720} unoptimized /> : <span className="camera-unavailable">{t("No live frame")}</span>}{preview?.stale && !preview.stream_url && <span className="camera-stale">{t("Stale frame")}</span>}</div><div className="camera-meta"><span><strong>{t(slot.label)}</strong><small>{preview?.captured_at ? `${t("Captured")} ${date(preview.captured_at)}` : t("Capture time unavailable")}</small></span><Badge tone={available ? "success" : "warning"}>{preview?.stream_url ? t("Real-time") : available ? t("Live") : t("Unavailable")}</Badge></div></article>;
    })}</div>
    {cameraPreviewSlots.some((slot) => { const preview = previewsByChannel.get(slot.channel); return !preview || (preview.stale && !preview.stream_url); }) && <p className="form-hint camera-hint">{t("The head camera is real-time. Hand cameras appear when the collector writes current frames; historical frames are hidden.")}</p>}
  </section>{review?.record_uid && <section className="panel collection-review"><div className="section-heading"><div><p className="eyebrow">{t("Collection review").toUpperCase()}</p><h2>{review.name}</h2><p className="mono muted">{review.record_uid}</p></div><button className="icon-button" onClick={() => { setReviewId(""); setDeleteArmed(false); }}>×</button></div>
    <div className="review-summary"><span><small>{t("Status")}</small><Badge tone={review.status === "failed" ? "danger" : "success"}>{review.status}</Badge></span><span><small>{t("Size")}</small><strong>{reviewEpisode ? bytes(reviewEpisode.file_size) : t("Indexing…")}</strong></span><span><small>{t("Duration")}</small><strong>{reviewEpisode ? `${Math.round(reviewEpisode.duration_seconds)} ${t("sec")}` : `${review.planned_duration_seconds ?? "—"} ${t("sec")}`}</strong></span><span><small>{t("Quality")}</small><strong>{reviewEpisode?.validation_status ?? t("Pending")}</strong></span></div>
    <div className="camera-grid review-camera-grid">{cameraPreviewSlots.map((slot) => <article className="camera-card" key={slot.channel}><div className="camera-frame"><span className="camera-unavailable">{t("Preview unavailable")}</span>{review.review_status !== "deleted" && <Image src={`/api/v1/collections/${review.id}/preview/${slot.channel}?v=${encodeURIComponent(review.stopped_at ?? review.id)}`} alt={t(slot.label)} width={1280} height={720} unoptimized onError={(event) => { event.currentTarget.style.display = "none"; }} />}</div><div className="camera-meta"><strong>{t(slot.label)}</strong></div></article>)}</div>
    {review.error && <div className="notice camera-error">{review.error}</div>}
    <div className="review-actions"><button className="button primary" onClick={() => decide("keep")} disabled={review.review_status === "kept"}>{review.review_status === "kept" ? t("Kept") : t("Keep data")}</button><button className="button danger-button" onClick={() => setDeleteArmed(true)} disabled={review.review_status === "deleted"}>{t("Delete data")}</button></div>
    {deleteArmed && <div className="delete-confirm"><div className="notice danger-note">{t("This permanently deletes the robot-side source data. Type the full UID and administrator password to continue.")}</div><label>{t("Confirm UID")}<input value={deleteUid} onChange={(event) => setDeleteUid(event.target.value)} placeholder={review.record_uid} /></label><label>{t("Administrator password")}<input type="password" value={deletePassword} onChange={(event) => setDeletePassword(event.target.value)} autoComplete="current-password" /></label><div className="actions"><button className="button" onClick={() => setDeleteArmed(false)}>{t("Cancel")}</button><button className="button danger-button" onClick={() => decide("delete")} disabled={deleteUid !== review.record_uid || !deletePassword}>{t("Permanently delete")}</button></div></div>}
  </section>}<div className="two-column collection-layout"><section className="panel"><p className="eyebrow">{t("Local orchestration").toUpperCase()}</p><h2>{t("Start collection")}</h2><p className="muted">{t("Allocates local task/job IDs and preserves the collector UID. Data is retained until an administrator explicitly reviews it.")}</p>
    <form className="form-stack" onSubmit={start}><label>{t("Task name")}<input name="name" placeholder="pick-and-place calibration" required minLength={2} /></label><label>{t("Planned duration")}<select name="duration" defaultValue="60"><option value="30">{t("30 seconds")}</option><option value="60">{t("1 minute")}</option><option value="300">{t("5 minutes")}</option><option value="900">{t("15 minutes")}</option></select></label><button className="button primary" disabled={busy || robot.observe_only || !robot.online}>{busy ? t("Starting…") : t("Start collection")}</button>{robot.observe_only && <p className="form-hint">{t("Disabled while this robot is observe-only.")}</p>}</form>
  </section><section className="panel"><div className="section-heading"><div><p className="eyebrow">{t("Sessions").toUpperCase()}</p><h2>{t("Recent collection jobs")}</h2></div><button className="icon-button" onClick={() => load()}><Icon name="refresh" /></button></div>
    {rows.length ? <div className="session-list">{rows.map((row) => <article key={row.id}><div><strong>{row.name}</strong><p className="mono">{row.record_uid ?? `${t("local job")} ${row.job_id}`}</p><small>{date(row.started_at)} · {row.planned_duration_seconds ?? t("manual")} {t("sec")}</small></div><div><Badge tone={row.status === "completed" || row.status === "stopped" ? "success" : row.status === "failed" ? "danger" : "info"}>{row.status}</Badge>{row.review_status !== "pending" && <Badge tone={row.review_status === "deleted" ? "danger" : "neutral"}>{row.review_status}</Badge>}{["starting", "recording", "stopping"].includes(row.status) && <button className="button small" onClick={() => stop(row.id)}>{t("Stop")}</button>}{row.status === "failed" && row.record_uid && <button className="button small" onClick={() => forceStop(row.id)}>{t("Force stop")}</button>}{["completed", "stopped", "failed"].includes(row.status) && row.record_uid && row.review_status !== "deleted" && <button className="button small" onClick={() => setReviewId(row.id)}>{t("Review")}</button>}</div></article>)}</div> : <Empty>{t("No collection sessions yet.")}</Empty>}
  </section></div></div>;
}

function OperationsView({ robot, notify }: { robot: Robot; notify: (message: string) => void }) {
  const { t } = useI18n();
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
  return <div className="operations-grid"><section className="panel safety-panel"><p className="eyebrow">{t("Safety gate").toUpperCase()}</p><h2>{t("Authorize one operation")}</h2><p className="muted">{t("A fresh password check creates a 60-second exclusive control lease. Robot status must be online, fresh, idle, collision-protected, and positively free of VR input.")}</p><label>{t("Administrator password")}<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label><label className="check"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>{t("I am physically present, the work area is clear, and the physical emergency stop is reachable.")}</span></label><div className="segmented"><button className={side === "left" ? "active" : ""} onClick={() => setSide("left")}>{t("Left arm")}</button><button className={side === "right" ? "active" : ""} onClick={() => setSide("right")}>{t("Right arm")}</button></div><div className="notice danger-note">{t("Software controls are not an emergency stop. Keep the physical emergency stop available for every real movement test.")}</div></section>
    <section className="panel"><p className="eyebrow">{t("Preset operations").toUpperCase()}</p><h2>{t("Command catalog")}</h2><div className="command-list">{safeCommands.map(([type, label, description]) => { const enabled = robot.enabled_commands.includes(type) && robot.capabilities.includes(type); const poseMissing = type === "reset_arm" && !bool(selectedPose.available); return <article key={type}><div><strong>{t(label)}{["save_reset_pose", "reset_arm"].includes(type) ? ` · ${side === "left" ? t("Left arm") : t("Right arm")}` : ""}</strong><p>{t(description)}</p>{!enabled && <small>{t("Not enabled in this deployment profile.")}</small>}{poseMissing && <small>{t("No saved {side} arm pose is available.", { side: side === "left" ? "左" : "右" })}</small>}</div><button className="button" disabled={!enabled || !password || !confirmed || Boolean(busy) || poseMissing} onClick={() => execute(type)}>{busy === type ? t("Authorizing…") : t("Execute")}</button></article>; })}</div></section>
    <section className="panel wide-panel"><div className="section-heading"><div><p className="eyebrow">{t("Command history").toUpperCase()}</p><h2>{t("Latest results")}</h2></div><button className="icon-button" onClick={() => load()}><Icon name="refresh" /></button></div>{commands.length ? <div className="audit-list">{commands.slice(0, 10).map((row) => <div key={row.id}><span><strong>{row.command_type}</strong><small>{date(row.created_at)}</small></span><Badge tone={row.status === "completed" ? "success" : row.status === "failed" ? "danger" : "info"}>{row.status}</Badge></div>)}</div> : <Empty>{t("No commands have been requested.")}</Empty>}</section>
  </div>;
}

function AuditView({ robot, notify }: { robot: Robot; notify: (message: string) => void }) {
  const { t } = useI18n();
  const [rows, setRows] = useState<Audit[]>([]);
  useEffect(() => { api<Audit[]>(`/api/v1/audit?robot_id=${robot.id}`).then(setRows).catch((error) => notify(error.message)); }, [robot.id, notify]);
  return <section className="panel"><div className="section-heading"><div><p className="eyebrow">{t("Immutable history").toUpperCase()}</p><h2>{t("Operations audit")}</h2></div><Badge>{rows.length} {t("records")}</Badge></div>{rows.length ? <div className="audit-list detailed">{rows.map((row) => <div key={row.id}><span><strong>{row.action}</strong><small>{row.target || t("control plane")} · {date(row.created_at)}</small></span><Badge tone={row.status === "ok" ? "success" : "danger"}>{row.status}</Badge></div>)}</div> : <Empty>{t("No audit records for this robot.")}</Empty>}</section>;
}

function ConsoleContent() {
  const { t } = useI18n();
  const [user, setUser] = useState<User | null>(null); const [robots, setRobots] = useState<Robot[]>([]);
  const [selectedId, setSelectedId] = useState(""); const [view, setView] = useState<View>("overview");
  const [collectionMounted, setCollectionMounted] = useState(false);
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
  async function probe() { if (!selected) return; setBusy(true); try { await post(`/api/v1/robots/${selected.id}/probe`); await loadRobots(); setNotice(t("Connection probe completed.")); } catch (error) { setNotice(error instanceof Error ? error.message : t("Probe failed")); } finally { setBusy(false); } }
  async function logout() { try { await post("/api/v1/auth/logout"); } finally { setUser(null); setRobots([]); } }
  if (!user) return <AuthGate onReady={setUser} />;
  return <div className="app-shell"><aside className="sidebar">
    <div className="brand"><div className="brand-mark small"><Icon name="robot" /></div><div className="brand-copy"><strong>OpenRoboOps</strong><span>{t("Fleet control plane")}</span></div><LanguageToggle compact /></div>
    <div className="sidebar-label"><span>{t("Robots").toUpperCase()} · {robots.length}</span><button className="icon-button" onClick={() => setShowAdd(true)} title={t("Add robot")}><Icon name="plus" /></button></div>
    <div className="robot-list">{robots.map((robot) => <button key={robot.id} className={selectedId === robot.id ? "selected" : ""} onClick={() => { setSelectedId(robot.id); setView("overview"); setCollectionMounted(false); }}><div className="robot-avatar"><Icon name="robot" /></div><span><strong>{robot.name}</strong><small><Dot online={robot.online} />{robot.online ? t("Online") : t("Offline")} · {robot.model}</small></span></button>)}</div>
    <div className="sidebar-footer"><div className="user"><span>{user.username.slice(0, 2).toUpperCase()}</span><div><strong>{user.username}</strong><small>{t("Administrator")}</small></div></div><button className="icon-button" onClick={logout} title={t("Sign out")}><Icon name="logout" /></button></div>
  </aside><main className="workspace">{selected ? <>
    <header className="topbar"><div><div className="title-line"><h1>{selected.name}</h1><Badge tone={selected.online ? "success" : "danger"}><Dot online={selected.online} />{selected.online ? t("Online") : t("Offline")}</Badge>{selected.observe_only && <Badge tone="info">{t("Observe only")}</Badge>}</div><p>{selected.model} · {selected.adapter_type} {t("adapter")} · {t("last seen")} {date(selected.last_seen)}</p></div><button className="button" onClick={probe} disabled={busy}><Icon name="refresh" />{busy ? t("Probing…") : t("Probe connection")}</button></header>
    <nav className="tabs">{views.map((item) => <button key={item.id} className={view === item.id ? "active" : ""} onClick={() => { setView(item.id); if (item.id === "collection") setCollectionMounted(true); }}><Icon name={item.id} />{t(item.label)}</button>)}</nav>
    <div className="content">{view === "overview" && <Overview robot={selected} />}{view === "data" && <DataView robot={selected} notify={setNotice} />}{collectionMounted && <div hidden={view !== "collection"}><CollectionView robot={selected} notify={setNotice} /></div>}{view === "operations" && <OperationsView robot={selected} notify={setNotice} />}{view === "audit" && <AuditView robot={selected} notify={setNotice} />}</div>
  </> : <div className="no-robot"><div className="brand-mark"><Icon name="robot" /></div><h1>{t("Register your first robot")}</h1><p>{t("Start with the simulator or add an A2D robot in observe-only mode.")}</p><button className="button primary" onClick={() => setShowAdd(true)}><Icon name="plus" />{t("Add robot")}</button></div>}</main>
    {notice && <div className="toast">{notice}</div>}
    {showAdd && <AddRobot onClose={() => setShowAdd(false)} onCreated={(robot) => { setRobots((items) => [...items, robot]); setSelectedId(robot.id); setShowAdd(false); setNotice(t("Robot registered in observe-only mode.")); }} />}
  </div>;
}

export default function Console() {
  return <I18nProvider><ConsoleContent /></I18nProvider>;
}
