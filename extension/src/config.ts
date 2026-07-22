export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";
export const CRAWLER_BASE_URL = import.meta.env.VITE_CRAWLER_BASE_URL ?? API_BASE_URL;

// Build with VITE_USE_MOCK=false to use FastAPI without editing source.
const rawUseMock = import.meta.env.VITE_USE_MOCK;
export const USE_MOCK = rawUseMock === undefined ? true : rawUseMock.toLowerCase() === "true";
export const MOCK_SCENARIO = import.meta.env.VITE_MOCK_SCENARIO ?? "normal";
export const CLIENT_VERSION = "0.1.0";
