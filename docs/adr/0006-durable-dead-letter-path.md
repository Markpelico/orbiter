# ADR-0006: a durable dead-letter path via captured advisories

**Status:** accepted · 2026-08

## The problem

A poison message — one that takes its worker down before any application code
can handle it — never gets acked, nak'd, or termed. JetStream redelivers it
after every AckWait, forever, and it kills every worker in the fleet in
rotation. The app-level retry ladder (worker catches the failure, requeues,
eventually terms) cannot help, because the definition of poison is that the
app layer never runs.

## Decision

`MaxDeliver` on the consumer caps redelivery. When it exhausts, JetStream
emits a max-deliveries **advisory**. ORBITER's DLQ listener consumes the
advisory and quarantines the job: copy the message to a durable DLQ stream,
record DEAD_LETTERED in the audit trail, delete the original from the work
stream, ack the advisory.

The subtlety: **advisories are fire-and-forget.** A listener that is down for
a deploy would silently lose quarantines — a stuck job with no trace. So the
advisory subject is itself captured into a JetStream stream
(`ORBITER_ADVISORIES`) and consumed with a durable pull consumer. A
quarantine can be late; it cannot be lost.

Ordering inside the quarantine is deliberate: copy → audit event → delete →
ack. The DLQ publish is deduped by `Nats-Msg-Id`, so crashing at any point
and re-running the whole block is safe.

## Replay

Replay is an operator decision, not an automatic retry — a job that exhausted
MaxDeliver has earned human attention. `POST /jobs/{id}/replay` appends a
REPLAYED event (legal only from DEAD_LETTER; 409 otherwise) and writes a
fresh outbox row in the same transaction, so a replay travels the exact same
effectively-once pipeline as an original submission.

## Alternatives rejected

- **Term-based DLQ only (app layer):** already exists for well-behaved
  failures; cannot catch poison by definition.
- **A separate redelivery-sweeper polling for stuck messages:** more moving
  parts to do what the broker already announces.
- **Core-NATS subscription to the advisory subject:** the fire-and-forget
  loss window above.
