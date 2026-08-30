// ORBITER load curves: six constant-arrival-rate windows walk the offered
// load up from 10 to 200 submissions/second, 30s each. Per-scenario
// thresholds exist mostly as a trick: declaring a threshold on a tagged
// sub-metric forces k6 to compute and export per-window percentiles, which
// is exactly what the latency-vs-load chart needs.
//
// Run from inside the compose network:
//   docker run --rm --network orbiter_default \
//     -v ./deploy/load:/scripts grafana/k6 run \
//     --summary-export /scripts/summary.json /scripts/submit.js
import http from "k6/http";
import { check } from "k6";

const RATES = [10, 25, 50, 100, 150, 200];
const WINDOW_S = 30;

export const options = {
  discardResponseBodies: true,
  // p(99) is not in k6's default export stats — and it is the whole point.
  summaryTrendStats: ["avg", "min", "med", "max", "p(90)", "p(95)", "p(99)"],
  scenarios: Object.fromEntries(
    RATES.map((rate, i) => [
      `rate${rate}`,
      {
        executor: "constant-arrival-rate",
        rate: rate,
        timeUnit: "1s",
        duration: `${WINDOW_S}s`,
        startTime: `${i * WINDOW_S}s`,
        preAllocatedVUs: Math.max(20, rate),
        maxVUs: rate * 3,
        tags: { rate: String(rate) },
      },
    ])
  ),
  thresholds: Object.fromEntries(
    RATES.flatMap((rate) => [
      [`http_req_duration{scenario:rate${rate}}`, ["p(99)<60000"]],
      [`http_req_failed{scenario:rate${rate}}`, ["rate<1"]],
    ])
  ),
};

const BASE = __ENV.ORBITER_URL || "http://api:8000";

export default function () {
  const key = `load-${__VU}-${__ITER}-${Date.now()}`;
  const res = http.post(
    `${BASE}/jobs`,
    JSON.stringify({ duration_ms: 100, failure_rate: 0 }),
    {
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": key,
      },
    }
  );
  check(res, {
    "accepted (201)": (r) => r.status === 201,
    "backpressured (429)": (r) => r.status === 429,
  });
}
