# RUNBOOK

Every alert pages a human; every page deserves a script. Commands assume the
local stack (`docker compose ...`) — the kubectl equivalent is noted where it
differs on EKS (`kubectl -n orbiter ...`).

## <a name="fast-burn"></a>OrbiterErrorBudgetFastBurn (page)

**Meaning:** permanent job failures (retries exhausted) are consuming the
30-day error budget ~14x too fast. Retries do NOT trigger this — only jobs
that gave up.

1. Is it one poison-ish job class or everything?
   `curl -s localhost:8000/dlq` and check recent `failed` jobs' `detail.error`
   in their event logs.
2. Worker health: `docker compose ps worker` / `kubectl get pods -l app=worker`.
   Crash-looping workers turn every job into a MaxDeliver exhaustion.
3. Dependencies: Valkey down makes every claim fail; Postgres down fails every
   state write. `docker compose logs worker --tail 50` names the culprit.
4. If failures are a bad deploy: roll back the worker image; in-flight jobs
   redeliver to the previous version by design (at-least-once + idempotency).

## <a name="slow-burn"></a>OrbiterErrorBudgetSlowBurn (ticket)

Same investigation as fast-burn, without the urgency: a few percent of jobs
failing steadily. Usually a specific payload shape; find the pattern in the
audit trail before it becomes a fast burn.

## <a name="dlq"></a>OrbiterDLQGrowth (ticket)

**Meaning:** the max-deliveries advisory fired; jobs are quarantined.

1. `curl -s localhost:8000/dlq` — inspect payloads. What do they share?
2. Fix the cause (usually a payload the worker cannot survive — that is what
   "poison" means).
3. Replay each: `curl -X POST localhost:8000/jobs/<id>/replay`.
4. Replay without a fix just re-quarantines after MaxDeliver more deliveries —
   safe, but pointless.

## <a name="stalled"></a>OrbiterQueueStalled (page)

**Meaning:** submissions flow, completions are zero for 10 minutes.

1. Any workers alive? Local: `docker compose ps worker`. EKS: `kubectl -n
   orbiter get pods -l app=worker` — **zero pods with a non-empty queue means
   the KEDA activation dead zone** (see the activationLagThreshold story in
   scaledobject.yaml) or KEDA itself is down (`kubectl -n keda get pods`).
2. Workers alive but idle → broker: is NATS up, does the consumer exist?
   `docker compose exec nats nats-server --help` is useless — check the
   monitoring endpoint instead: `curl -s localhost:8222/jsz | jq .streams`.
3. Workers busy but nothing completes → look for StaleLeaseError storms
   (clock trouble) or Postgres write failures in worker logs.
4. On EKS also check Karpenter can buy nodes: `kubectl get nodeclaims` —
   quota exhaustion shows as NodeClaims stuck not-Ready (seen live on the
   free plan; the fallback pool and vCPU ceilings exist for this).

## Not alerts, but worth knowing

- **429s from the API** are not an incident — that is admission control doing
  its job. Sustained 429s mean capacity planning, not firefighting.
- **`requeued` events** are the system working. Only `failed` burns budget.
- **Cold start after idle** (~65s on EKS: KEDA activation + node purchase +
  boot + pull) is the scale-to-zero tradeoff, measured in RESULTS.md.
