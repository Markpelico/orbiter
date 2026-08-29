# ADR-0004: backpressure = bounded admission + loud rejection

**Status:** accepted · 2026-08

## The problem

Submissions can outrun capacity. Something must give: reject new work, buffer
it, or shed existing work. Choosing *nothing* means choosing an unbounded
buffer by accident, which converts overload into latency, then into memory
pressure, then into an outage — after hiding the problem exactly as long as it
was cheap to fix.

## Decision

The API holds a per-replica admission controller with a fixed capacity.
Past capacity, submissions get **429 with `Retry-After`**. The client — which,
unlike the server, knows whether the work still matters — decides whether to
retry.

- **Rejection over buffering:** the queue behind the API (JetStream) is the
  buffer, and it is durable and observable. A second, implicit buffer inside
  the API process would be neither.
- **Rejection over shedding:** shedding needs priorities; ORBITER has one job
  class. If priorities arrive, this ADR gets a successor.
- **Per-replica, not global:** global admission needs shared state and becomes
  its own availability problem. Each replica defending its own capacity
  composes with horizontal scaling; the aggregate limit scales with the fleet.

## Consequence to demonstrate (Phase 3)

The k6 overload scenario runs twice: once against this policy (throughput
plateaus, p99 stays sane, 429 rate climbs) and once with admission disabled
(latency runs away). Both charts go in RESULTS.md.
