import { API_BASE_URL } from "../env";
import { ApiError } from "./errors";

export interface UploadCreatedRow {
  id: string;
  sha256: string;
  status: "pending" | "completed" | "failed" | (string & {});
}

export interface UploadStatusRow {
  id: string;
  sha256: string;
  original_filename: string;
  size_bytes: number;
  uploaded_at: string;
  status: "pending" | "completed" | "failed" | (string & {});
  error_message: string | null;
  parser_version: string | null;
  fight_id: string | null;
}

export async function uploadLog(file: File): Promise<UploadCreatedRow> {
  const fd = new FormData();
  fd.append("file", file);
  const resp = await fetch(`${API_BASE_URL}/api/v1/uploads`, {
    method: "POST",
    body: fd,
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as UploadCreatedRow;
}

export async function fetchUploadStatus(uploadId: string): Promise<UploadStatusRow> {
  const url = `${API_BASE_URL}/api/v1/uploads/${encodeURIComponent(uploadId)}`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as UploadStatusRow;
}
