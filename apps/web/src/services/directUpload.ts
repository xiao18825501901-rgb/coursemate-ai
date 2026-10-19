import type { GetSessionToken } from "../auth/AuthProvider";
import type { UploadAccepted } from "../types/api";
import { ApiError, requestJson } from "./http";

export interface DirectUploadGrant {
  uploadId: string;
  method: "PUT";
  url: string;
  headers: Record<string, string>;
  expiresAt: string;
}

interface DirectUploadFallback {
  method: "FALLBACK";
  reason: "LOCAL_STORAGE";
}

export async function sha256(file: File): Promise<string> {
  const bytes = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}

export async function uploadDirectOrFallback(
  getToken: GetSessionToken,
  file: File,
  beginUrl: string,
  completeUrl: (uploadId: string) => string,
  fallback: () => Promise<UploadAccepted>,
): Promise<UploadAccepted> {
  let result: DirectUploadGrant | DirectUploadFallback;
  try {
    result = await requestJson<DirectUploadGrant | DirectUploadFallback>(getToken, beginUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: file.name,
        mediaType: file.type || "application/octet-stream",
        byteSize: file.size,
        sha256: await sha256(file),
      }),
    });
  } catch (error: unknown) {
    if (error instanceof ApiError && error.code === "DIRECT_UPLOAD_UNAVAILABLE") {
      return fallback();
    }
    throw error;
  }
  if (result.method === "FALLBACK") return fallback();
  await putSignedObject(result, file);
  return requestJson<UploadAccepted>(getToken, completeUrl(result.uploadId), {
    method: "POST",
  });
}

/** Only signed storage headers: never forward the app's Clerk bearer token. */
export async function putSignedObject(grant: DirectUploadGrant, file: File): Promise<void> {
  const headers = new Headers();
  for (const [name, value] of Object.entries(grant.headers)) {
    if (name.toLowerCase() !== "content-length") headers.set(name, value);
  }
  if (!headers.has("content-type")) {
    headers.set("Content-Type", file.type || "application/octet-stream");
  }
  const uploaded = await fetch(grant.url, { method: grant.method, headers, body: file, credentials: 'omit' });
  if (!uploaded.ok) {
    throw new ApiError(
      uploaded.status,
      "OBJECT_UPLOAD_FAILED",
      `Object upload failed (${uploaded.status}).`,
    );
  }
}
