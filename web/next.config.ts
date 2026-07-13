import type { NextConfig } from "next";
import createBundleAnalyzer from "@next/bundle-analyzer";

// v0.10.x plan 011: application-layer fallback for the security headers
// emitted at the Caddy reverse-proxy layer (Caddyfile plan 008).
// Layered defense: a deployment topology WITHOUT a configured proxy
// (e.g., raw Cloudfront in front, ngrok tunneling, bare-metal behind a
// corporate VPN) still ships HSTS / CSP / nosniff / frame-ancestors via
// this `headers()` block.
//
// Operators deploying behind Caddy + plan 008 produce the SAME headers
// TWICE -- acceptable: browsers dedupe on identical key+value pairs. If
// the operator changes one value WITHOUT the other, the LATER-emitting
// layer wins -- KEEP THESE TWO FILES SYNCHRONIZED:
//   - /Caddyfile (plan 008)         -> emits at the proxy layer
//   - /web/next.config.ts (plan 011) -> emits at the app layer
//
// Future policy relaxations (CSP inline-script, frame-ancestors change,
// HSTS max-age tweak) MUST land in BOTH files in the SAME PR with a
// short note in the commit body explaining the rationale -- CSP drift
// is invisible otherwise, and a half-relaxed CSP is worse than the
// strict version.

const SECURITY_HEADERS = [
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  },
  { key: "X-Content-Type-Options", value: "nosniff" },
  {
    key: "Referrer-Policy",
    value: "strict-origin-when-cross-origin",
  },
  {
    key: "Content-Security-Policy",
    // 'self' for default + script-src + style-src; 'unsafe-inline' for
    // styles is required by Next.js SSR output (the framework emits
    // inline <style> tags during streaming SSR). 'unsafe-inline' for
    // scripts is required by Next.js 16 / React 19 streaming SSR, which
    // injects a small inline bootstrapping script (e.g. self.__next_r)
    // to coordinate hydration. If a future contributor adds a custom
    // inline <script>, prefer a nonce-based CSP instead of broadening
    // this directive further.
    value:
      "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
  },
];

const withBundleAnalyzer = createBundleAnalyzer({
  enabled: process.env.ANALYZE === "true",
});

const nextConfig: NextConfig = {
  output: "standalone",
  // dev-only: allow HMR on loopback variants (127.0.0.1, localhost).
  // Next.js 16 matches Origin exactly, hostname only, no port.
  // For LAN access (mobile testing), add your machine's IP from
  // `ip -4 route get 1 | awk '{for(i=1;i<=NF;i++)if($i=="src"){print $(i+1);exit}}'`.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: SECURITY_HEADERS,
      },
    ];
  },
};

export default withBundleAnalyzer(nextConfig);
