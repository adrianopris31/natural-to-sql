import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    // Default is 30s idle; local LLM generation can exceed that. The backend
    // also sends SSE heartbeats, this is a second safety net.
    proxyTimeout: 300_000,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
