/**
 * k6 smoke: browse /api/v1/fights with 100 concurrent users.
 *
 * Configurable via env: `BASE_URL=http://localhost:8000 k6 run ...`
 * (default localhost:8000 matches the docker-compose dev stack).
 */
import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const TARGET = `${BASE_URL}/api/v1/fights`;

export const options = {
  thresholds: {
    http_req_duration: ["p(95)<500"],
    http_req_failed: ["rate<0.01"],
  },
  stages: [
    { duration: "30s", target: 10 },
    { duration: "60s", target: 100 },
    { duration: "120s", target: 100 },
    { duration: "30s", target: 0 },
  ],
};

export default function (): void {
  const res = http.get(TARGET);
  check(res, {
    "status is 200": (r) => r.status === 200,
    "has JSON data": (r) => {
      try {
        return r.json() !== null;
      } catch {
        return false;
      }
    },
  });
  sleep(1);
}
