export const API_BASE_URL = "http://localhost:8000";

// Build with VITE_USE_MOCK=false to use FastAPI without editing source.
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";
export const MOCK_SCENARIO = import.meta.env.VITE_MOCK_SCENARIO ?? "normal";
export const CLIENT_VERSION = "0.1.0";
