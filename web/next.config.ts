import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // dev-only: allow HMR on loopback variants (127.0.0.1, localhost).
  // Next.js 16 matches Origin exactly, hostname only, no port.
  // For LAN access (mobile testing), add your machine's IP from
  // `ip -4 route get 1 | awk '{for(i=1;i<=NF;i++)if($i=="src"){print $(i+1);exit}}'`.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
