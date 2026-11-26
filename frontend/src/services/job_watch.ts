import type { JobStatus } from "./api_client";
import { api, jobDownloadUrl, wsJobUrl } from "./api_client";

function parseWsPayload(raw: unknown): Partial<JobStatus> | null {
  if (!raw || typeof raw !== "object") return null;
  const env = raw as { code?: number; data?: Partial<JobStatus> };
  if (env.code !== 0 || !env.data) return null;
  return env.data;
}

export type JobProgressHandler = (status: JobStatus) => void;

export async function watchJob(
  jobId: string,
  onProgress: JobProgressHandler,
): Promise<JobStatus> {
  return new Promise((resolve, reject) => {
    let settled = false;
    let pollTimer: ReturnType<typeof setInterval> | undefined;
    let ws: WebSocket | null = null;

    const finish = (status: JobStatus) => {
      if (settled) return;
      settled = true;
      if (pollTimer !== undefined) clearInterval(pollTimer);
      ws?.close();
      resolve(status);
    };

    const fail = (err: unknown) => {
      if (settled) return;
      settled = true;
      if (pollTimer !== undefined) clearInterval(pollTimer);
      ws?.close();
      reject(err);
    };

    const handleStatus = (partial: Partial<JobStatus>) => {
      const merged: JobStatus = {
        job_id: jobId,
        kind: partial.kind ?? "",
        status: partial.status ?? "running",
        progress: partial.progress ?? 0,
        message: partial.message ?? "",
        result_path: partial.result_path ?? null,
        error: partial.error ?? null,
        download_url: partial.download_url,
        detail: partial.detail,
      };
      onProgress(merged);
      if (
        merged.status === "done" ||
        merged.status === "failed" ||
        merged.status === "cancelled"
      ) {
        finish(merged);
      }
    };

    const poll = async () => {
      try {
        const status = await api.jobStatus(jobId);
        handleStatus(status);
      } catch (e) {
        fail(e);
      }
    };

    try {
      ws = new WebSocket(wsJobUrl(jobId));
      ws.onmessage = (ev) => {
        try {
          const data = parseWsPayload(JSON.parse(String(ev.data)));
          if (data) handleStatus({ job_id: jobId, ...data });
        } catch {
          /* ignore malformed */
        }
      };
      ws.onerror = () => {
        /* polling continues */
      };
    } catch {
      ws = null;
    }

    pollTimer = setInterval(() => {
      void poll();
    }, 800);
    void poll();
  });
}

export function triggerJobDownload(jobId: string, filename?: string): void {
  const a = document.createElement("a");
  a.href = jobDownloadUrl(jobId);
  if (filename) a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}