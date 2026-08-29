# ADR-0001: NATS JetStream as the job broker

**Status:** accepted · 2026-08

## Decision

Jobs travel through a NATS JetStream work-queue stream with explicit acks,
`AckWait` as the visibility timeout, and `MaxDeliver` feeding a dead-letter
stream.

## Why not the alternatives

**Kafka.** A partitioned log is the wrong shape for a work queue. Consumer
groups track *offsets*, not messages: there is no per-message ack, no
per-message redelivery, and a poison message at the head of a partition blocks
everything behind it. You end up rebuilding a job queue on top of the log —
retry topics, DLQ topics, dedupe tables — at which point the log bought
nothing. Kafka is the right tool when you need replayable history and many
independent consumers; that is not this workload.

**SQS.** Semantically the closest fit (visibility timeout, redrive policy,
DLQ are all built in). Rejected because the broker's failure modes are part
of what this project exists to learn, and because a managed broker welds the
local dev story and the demo to one cloud. JetStream runs identically in
docker-compose, in CI containers, and on the cluster.

**RabbitMQ.** Would work. JetStream was chosen for the smaller operational
surface (one binary, no Erlang tuning), the built-in `Nats-Msg-Id` dedupe
window that backstops the outbox relay, and the monitoring endpoint KEDA's
scaler consumes directly.

## Consequences

- At-least-once delivery is the contract; idempotency is mandatory (ADR-0005,
  execution guard).
- Known issue to verify in Phase 3: KEDA's JetStream scaler polls a monitoring
  endpoint that only the stream leader answers authoritatively; scale-from-zero
  needs the scaler pointed at the right place.
