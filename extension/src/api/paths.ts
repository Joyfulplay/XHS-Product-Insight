export const apiPaths = {
  products: {
    resolve: "/products/resolve",
    analysis: (productId: string, mode: string) => `/products/${encodeURIComponent(productId)}/analysis?mode=${encodeURIComponent(mode)}`,
    evidence: (productId: string, query: string) => `/products/${encodeURIComponent(productId)}/evidence?${query}`,
    refresh: (productId: string) => `/products/${encodeURIComponent(productId)}/refresh`,
  },
  jobs: {
    detail: (jobId: string) => `/jobs/${encodeURIComponent(jobId)}`,
  },
  crawler: {
    authStatus: "/crawler/auth/status",
    login: "/crawler/auth/login",
    loginJob: (jobId: string) => `/crawler/auth/login/jobs/${encodeURIComponent(jobId)}`,
    collection: "/crawler/collections",
    collectionJob: (jobId: string) => `/crawler/collections/${encodeURIComponent(jobId)}`,
    collectionResult: (jobId: string) => `/crawler/collections/${encodeURIComponent(jobId)}/result`,
  },
} as const;
