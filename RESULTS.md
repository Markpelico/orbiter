# RESULTS

Every measurement this project produces, including the ones that come out
badly. A chart showing where it fell over is more credible than one showing it
never did.

## Ledger

| Date | Measurement | Verdict | Chart |
|---|---|---|---|
| 2026-08-30 | **Cold start, empty fleet → first execution: 65s** (submit 12:15:05 → started 12:16:10; covers KEDA activation + Karpenter node purchase + boot + join + image pull + worker start; n=1, first live run, free-tier t3.small on-demand fallback) | measured | pending |
| 2026-08-30 | **Scale-up for a single stranded job: node Ready in 89s**, fleet 0→1 (the KEDA activation-dead-zone fix, verified live) | measured | pending |
| 2026-08-30 | **Full cycle: 21/21 jobs succeeded**; KEDA 0→4→0 pods; Karpenter bought and consolidated away t3.small nodes; spot market refused by the free plan → on-demand fallback pool absorbed 100% of demand | measured | — |
| 2026-08-30 | **One distributed trace spans api → relay → worker** (0ms POST /jobs → 9.5ms relay.publish → 2,438ms job.process attempt 1 — queue wait visible in the gap), verified via Tempo API on the local stack | verified | pending |
| 2026-08-30 | **Submit latency vs offered load (local, 10→200 rps)**: p50 ≈ 3–4ms flat, p95 ≈ 4ms flat, p99 rises 5→10ms at 200 rps — the submit path (one Postgres tx: job + events + outbox) absorbs 200/s with single-digit-ms latency; **the knee is beyond the tested range** | measured | [chart](results/latency-vs-load.png) |
| 2026-08-30 | **Completion ceiling, fixed fleet**: 2 local workers plateau at ~19 jobs/s while offered load climbs to 200/s — the durable queue absorbs the gap without loss (16,056/16,056 accepted). This flat line is the argument for queue-depth autoscaling | measured | [chart](results/throughput-timeline.png) |
| — | Same curves on EKS with KEDA scaling (the flat line should rise) | pending next apply day | — |
| — | Throughput vs. worker count (1..16) | pending next apply day | — |
| — | Overload: admission on vs. off (ADR-0004) | pending (local capacity never tripped 64 in-flight) | — |
| — | Cold-start breakdown (node/image/pod/poll) | pending (have the total; need the split) | — |
| — | Recovery time: pod kill / node kill / partition | pending Phase 5 | — |
| — | Naive TTL lock vs. fenced lease under TimeChaos | pending Phase 5 | — |
| — | Cost per 1,000 jobs: spot vs. on-demand, STZ on/off | pending Phase 4 | — |
| — | Nightly chaos pass/fail history | pending Phase 5 | — |

## Method notes

Load generation: k6. Metrics: Prometheus/Mimir with exemplars. Cost: OpenCost
(measured, not the pricing calculator). Each entry links its raw run data
under `results/` and states the fleet shape, so every chart is reproducible.
