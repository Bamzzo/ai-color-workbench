import type { ColorParams } from "../core/params";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(
  /\/$/,
  "",
) ?? "";

export interface ApiEnvelope<T> {
  code: number;
  message: string;
  data: T;
}

export class ApiError extends Error {
  code: number;
  constructor(code: number, message: string) {
    super(message);
    this.code = code;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const response = await fetch(url, init);
  const body = (await response.json()) as ApiEnvelope<T>;
  if (body.code !== 0) {
    throw new ApiError(body.code, body.message);
  }
  return body.data;
}

export interface PresetItem {
  key: string;
  label: string;
  params: ColorParams;
}

export interface LutBakeResult {
  lut_id: string;
  size: number;
  domain_min: [number, number, number];
  domain_max: [number, number, number];
  data_b64: string;
}

export interface MediaUploadResult {
  media_id: string;
  kind: "image" | "video";
  width: number;
  height: number;
  content_url: string;
  duration_s?: number;
  fps?: number;
}

export interface HistogramData {
  r: number[];
  g: number[];
  b: number[];
  luma: number[];
  clip_low: number;
  clip_high: number;
}

export interface AiProposal {
  params: ColorParams;
  summary: string;
  source: string;
  provider: string;
  model: string;
}

export interface JobStatus {
  job_id: string;
  kind: string;
  status: string;
  progress: number;
  message: string;
  result_path: string | null;
  error: string | null;
  download_url?: string;
  detail?: Record<string, unknown>;
}

export function decodeLutBase64(data_b64: string): Float32Array {
  const binary = atob(data_b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Float32Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 4);
}

export function mediaContentUrl(mediaId: string): string {
  return `${API_BASE}/api/media/${mediaId}/content`;
}

export function jobDownloadUrl(jobId: string): string {
  return `${API_BASE}/api/jobs/${jobId}/download`;
}

export function wsJobUrl(jobId: string): string {
  const base = API_BASE || window.location.origin;
  const wsBase = base.replace(/^http/, "ws");
  return `${wsBase}/ws/jobs/${jobId}`;
}

export const api = {
  getPresets: () => request<PresetItem[]>("/api/presets"),

  validateParams: (params: ColorParams) =>
    request<{ params: ColorParams }>("/api/params/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ params }),
    }),

  aiPropose: (
    intent: string,
    current_params: ColorParams,
    allow_offline_fallback = true,
  ) =>
    request<AiProposal>("/api/ai/propose", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ intent, current_params, allow_offline_fallback }),
    }),

  bakeLut: (params: ColorParams, size = 33) =>
    request<LutBakeResult>("/api/lut/bake", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ params, size }),
    }),

  uploadCube: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<LutBakeResult & { title?: string; sha256?: string }>(
      "/api/lut/upload_cube",
      { method: "POST", body: form },
    );
  },

  uploadMedia: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<MediaUploadResult>("/api/media/upload", {
      method: "POST",
      body: form,
    });
  },

  histogram: (media_id: string) =>
    request<HistogramData>("/api/histogram", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ media_id }),
    }),

  exportImage: (
    media_id: string,
    params: ColorParams,
    strength = 1,
    format = "PNG",
  ) =>
    request<{ job_id: string }>("/api/export/image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ media_id, params, strength, format }),
    }),

  exportVideo: (media_id: string, params: ColorParams, strength = 1) =>
    request<{ job_id: string }>("/api/export/video", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ media_id, params, strength }),
    }),

  exportLut: (params: ColorParams, strength = 1) =>
    request<{ job_id: string }>("/api/export/lut", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ params, strength }),
    }),

  jobStatus: (jobId: string) => request<JobStatus>(`/api/jobs/${jobId}`),
};