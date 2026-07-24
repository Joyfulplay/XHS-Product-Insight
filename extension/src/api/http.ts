import { API_BASE_URL } from "../config";

export class HttpRequestError extends Error {
  constructor(
    message: string,
    public readonly status: number | null = null,
    public readonly businessCode: string | null = null,
    public readonly body: unknown = null,
  ) {
    super(message);
    this.name = "HttpRequestError";
  }
}

function businessMessage(body: unknown): { code: string | null; message: string | null } {
  if (!body || typeof body !== "object") return { code: null, message: null };
  const error = "error" in body ? (body as { error?: unknown }).error : body;
  if (!error || typeof error !== "object") return { code: null, message: null };
  const code = "code" in error && typeof (error as { code?: unknown }).code === "string" ? (error as { code: string }).code : null;
  const message = "message" in error && typeof (error as { message?: unknown }).message === "string" ? (error as { message: string }).message : null;
  return { code, message };
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
    throw new HttpRequestError("网络失败：后端未启动或无法连接", null);
  }
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // Keep the HTTP status as the primary error when the body is absent or not JSON.
    }
    const business = businessMessage(body);
    if (response.status === 409) {
      throw new HttpRequestError(business.message ?? "已有采集任务正在运行，请等待任务完成后重试。", response.status, business.code, body);
    }
    if (response.status === 404) {
      throw new HttpRequestError(`接口不存在（404）：${path}`, response.status, business.code, body);
    }
    if (business.message) {
      throw new HttpRequestError(`后端业务失败：${business.message}`, response.status, business.code, body);
    }
    throw new HttpRequestError(`请求失败：后端返回 HTTP ${response.status}`, response.status, business.code, body);
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
