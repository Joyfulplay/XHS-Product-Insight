export const apiPaths = {
  products: {
    analysis: (productId: string, mode: string) => `/products/${encodeURIComponent(productId)}/analysis?mode=${encodeURIComponent(mode)}`,
    evidence: (productId: string, query: string) => `/products/${encodeURIComponent(productId)}/evidence?${query}`,
    refresh: (productId: string) => `/products/${encodeURIComponent(productId)}/refresh`,
  },
  jobs: {
    detail: (jobId: string) => `/jobs/${encodeURIComponent(jobId)}`,
  },
  crawler: {
    authStatus: (refresh = false) => `/xhs/auth/status${refresh ? "?refresh=true" : ""}`,
    login: "/xhs/auth/login",
    loginJob: (jobId: string) => `/xhs/auth/login/${encodeURIComponent(jobId)}`,
    collection: "/xhs/collections",
    collectionJob: (jobId: string) => `/xhs/collections/${encodeURIComponent(jobId)}`,
    collectionResult: (jobId: string) => `/xhs/collections/${encodeURIComponent(jobId)}/result`,
  },
} as const;
