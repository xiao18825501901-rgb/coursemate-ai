import type { ApiErrorBody } from "../types/api";
import type { GetSessionToken } from "../auth/AuthProvider";


export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as Partial<ApiErrorBody>;
    if (body.error?.code && body.error.message) {
      return new ApiError(
        response.status,
        body.error.code,
        body.error.message,
        body.error.details ?? {},
      );
    }
  } catch {
    // Fall through to the safe generic message.
  }
  return new ApiError(response.status, "REQUEST_FAILED", `Request failed (${response.status}).`);
}

export async function authenticatedFetch(
  getToken: GetSessionToken,
  url: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = await getToken();
  if (!token) {
    throw new ApiError(401, "UNAUTHENTICATED", "A valid sign-in session is required.");
  }
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return fetch(url, { ...init, headers });
}

export async function requestJson<T>(
  getToken: GetSessionToken,
  url: string,
  init?: RequestInit,
): Promise<T> {
  const response = await authenticatedFetch(getToken, url, init);
  if (!response.ok) throw await errorFromResponse(response);
  return (await response.json()) as T;
}

export async function requireOk(response: Response): Promise<Response> {
  if (!response.ok) throw await errorFromResponse(response);
  return response;
}
