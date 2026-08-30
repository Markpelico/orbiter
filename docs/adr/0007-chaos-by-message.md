# ADR-0007: chaos is a message, not an infrastructure call

**Status:** accepted · 2026-08

## The problem

The CHAOS button must kill one random worker mid-job. The obvious
implementations reach for infrastructure: call the Kubernetes API to delete a
pod, or the Docker socket to kill a container. Both mean privileges (RBAC for
the API service account, or mounting the Docker socket — a container-escape
classic), and both mean a different code path per environment.

## Decision

Chaos is delivered the same way work is: as a message. The API publishes to a
plain NATS subject (`orbiter.chaos`, core pub/sub — not JetStream: chaos should
not be durable); every worker subscribes **in a queue group**, so the broker
picks exactly one random recipient; that worker calls `os._exit(1)`.

- `os._exit`, not `sys.exit`: no cleanup, no lease release, no graceful drain.
  The worker vanishes exactly as it would on a segfault, OOM kill, or yanked
  spot instance — which is the failure the platform claims to survive.
- The queue group IS the random victim selector. No inventory, no coordination.
- One code path everywhere: compose restarts the corpse locally
  (`restart: unless-stopped`), the Deployment restarts it on EKS, and the
  recovery mechanics (AckWait redelivery, claim expiry, fencing) are identical.

## What this deliberately is not

Process-level chaos only. Node loss, network partitions, and clock skew cannot
be simulated from inside the process — that is Chaos Mesh's job on the cluster
(deploy/chaos/), where the platform itself is the blast radius. The button
demonstrates the recovery story on demand; Chaos Mesh proves it under failure
modes the process cannot fake.

## Consequence observed on first live use

The killed worker's in-flight message redelivers after AckWait, but its
execution claim (TTL = AckWait) may still be alive at redelivery, costing one
extra IN_PROGRESS → nak bounce before a new worker runs it. Recovery is
therefore bounded by roughly 2× AckWait in the worst case — a real, measurable
consequence of layering idempotency on top of at-least-once delivery, and
exactly the kind of number RESULTS.md exists to hold.
