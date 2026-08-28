import type { components } from "./api-types";

export type Robot = components["schemas"]["RobotResponse"];
export type Episode = components["schemas"]["EpisodeResponse"];
export type Collection = components["schemas"]["CollectionResponse"];
export type CameraPreview = components["schemas"]["CameraPreviewResponse"];
export type SyncJob = components["schemas"]["SyncJobResponse"];
export type Command = components["schemas"]["CommandResponse"];
export type Audit = components["schemas"]["AuditResponse"];
export type User = components["schemas"]["UserResponse"];
export type Telemetry = components["schemas"]["TelemetryResponse"];

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

function cookie(name: string): string | undefined {
  if (typeof document === "undefined") return undefined;
  const prefix = `${name}=`;
  return document.cookie.split("; ").find((item) => item.startsWith(prefix))?.slice(prefix.length);
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = cookie("openroboops_csrf");
    if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  }
  const response = await fetch(path, { ...init, credentials: "include", headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = typeof payload.detail === "string" ? payload.detail : response.statusText;
    throw new ApiError(detail || "Request failed", response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
