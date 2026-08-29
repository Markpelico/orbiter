# ADR-0005: fenced leases, not TTL locks

**Status:** accepted · 2026-08

## The problem

Workers take a lease on a job so exactly one executes it. Leases carry TTLs so
a dead worker's lease frees itself. But a TTL lock alone has a hole: the
holder can pause — GC, VM freeze, CPU starvation, clock skew — past its own
expiry *without knowing it*. The lease expires, a second worker legitimately
acquires it, and now two workers write. The lock did its job; the system
corrupted state anyway. This is Kleppmann's critique of Redlock.

## Decision

Every acquisition receives a token from a monotonic counter (`INCR` in
Valkey). Writes carry their token, and the *write site* — the jobs table —
rejects any token older than the newest it has accepted, via the UPDATE's
WHERE clause (`fence_token <= $n`, zero rows updated → `StaleLeaseError`).
The stale holder's writes bounce off the data, which is the only place the
check can be airtight.

Details that matter:

- The counter increments *before* the SET NX, so a failed acquire burns a
  token. Fencing needs monotonicity, not density.
- Release is compare-and-delete (Lua, server-side): a plain DEL from a stale
  holder would drop its successor's lease — the same two-writer bug wearing a
  different hat.
- The token check accepts `>=`, not `>`: the same holder writes repeatedly
  under one token.

## Proof

- Today: `tests/unit/test_fencing.py::test_paused_holder_is_fenced_out`
  reproduces the pause with a fake clock.
- Phase 5: Chaos Mesh TimeChaos reproduces it on the live cluster, and the
  naive-lock-vs-fenced-lease chart goes in RESULTS.md.
