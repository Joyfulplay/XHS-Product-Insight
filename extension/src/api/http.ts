import { API_BASE_URL } from "../config";

export class HttpRequestError extends Error {
  constructor(
    message: string,
    public readonly status: number | null = null,
  ) {
    super(message);
    this.name = "HttpRequestError";
  }
}

export async function requestJson<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new HttpRequestError("后端未启动或网络不可达", null);
  }
  if (!response.ok) {
    throw new HttpRequestError(`后端返回 HTTP ${response.status}`, response.status);
  }
  return (await response.json()) as T;
}

export function delay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = window.setTimeout(resolve, milliseconds);
    signal?.addEventListener(
      "abort",
      () => {
        window.clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });
}
