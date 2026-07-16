/**
 * k6 upload smoke: concurrent .zevtc uploads against
 * POST /api/v1/uploads.
 *
 * Uses the synthetic ``tests/load/fixtures/sample.zevtc`` (50 bytes,
 * header-only). For real-FUU (fight-replay-under-upload) tests,
 * copy a real fixture from libs/gw2_evtc_parser/tests/fixtures/ if
 * available. The thresholds are tuned for the 50-byte sample, NOT a
 * 100 MiB file -- those need a different harness.
 */
import http from "k6/http";
import { check } from "k6";
import { open } from "k6/data";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const TARGET = `${BASE_URL}/api/v1/uploads`;
const FIXTURE_PATH = __ENV.FIXTURE_PATH || "./fixtures/sample.zevtc";
const file = open(FIXTURE_PATH, "b");

export const options = {
  thresholds: {
    http_req_duration: ["p(95)<10000"],
    http_req_failed: ["rate<0.05"],
  },
  stages: [
    { duration: "30s", target: 5 },
    { duration: "30s", target: 20 },
    { duration: "60s", target: 50 },
  ],
};

export default function (): void {
  const data = { file: http.file(file, "sample.zevtc") };
  const res = http.post(TARGET, data);
  check(res, {
    "status is 200 or 201": (r) => r.status === 200 || r.status === 201,
    "has upload id": (r) => {
      try {
        const body = r.json() as { id?: string };
        return typeof body.id === "string" && body.id.length > 0;
      } catch {
        return false;
      }
    },
  });
}
