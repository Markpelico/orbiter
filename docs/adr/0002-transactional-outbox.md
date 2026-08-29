# ADR-0002: transactional outbox from day one

**Status:** accepted · 2026-08

## The problem

The API must do two things when a job is submitted: persist it in Postgres and
publish it to the broker. Two systems, no shared transaction. Whichever order
you pick, a crash between the two either loses the job silently (DB write
succeeded, publish never happened) or executes a job that officially does not
exist (publish succeeded, DB write lost). This is the dual-write problem, and
retries do not fix it — they just move the window.

## Decision

The submit transaction writes the job row, its first events, and a row in an
`outbox` table atomically. A relay process polls unpublished outbox rows
(`FOR UPDATE SKIP LOCKED`, so relays scale horizontally without double-claiming)
and publishes them to JetStream, then marks them published.

Crash-safety is layered:
1. Job and outbox row are atomic — nothing can exist that won't be published.
2. Relay crash between publish and mark → republish with the same
   `Nats-Msg-Id`; JetStream dedupes inside its duplicate window.
3. Beyond that window, the worker's execution guard makes the duplicate a no-op.

At-least-once transport, effectively-once processing.

## Alternatives rejected

- **Publish-then-write / write-then-publish:** the crash window, see above.
- **CDC (Debezium):** the production-grade version of the same pattern; a
  Kafka Connect cluster is too much operational mass for this system. The ADR
  exists so the interview answer can be "outbox with a poller here, Debezium
  when change volume justifies it."
- **Built from day one, not retrofitted:** touching every write path later is
  the most expensive possible time to discover you need it.
