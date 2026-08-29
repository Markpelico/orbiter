# ADR-0003: no Temporal, no Celery

**Status:** accepted · 2026-08

## Decision

ORBITER builds its own durability primitives — idempotency keys, fenced
leases, retries, the outbox, the event-sourced state machine — instead of
adopting a workflow engine or task framework that provides them.

## Why

Because providing exactly these guarantees is what Temporal is *for*, and
adopting it would reduce this project to configuration. The purpose of ORBITER
is to be able to explain, from experience, what breaks without each mechanism.

This is not not-invented-here. The honest production recommendation is the
reverse of this decision: a team shipping a product should reach for Temporal
(durable execution, replay-based recovery, versioned workflows) or at minimum
Celery/SQS for simple task fan-out, and spend its innovation budget on the
product. What Temporal would replace here, concretely: the outbox (workflow
starts are durable), the execution guard (activities are deduplicated by the
engine), the state machine table (workflow state is the source of truth), and
most of the worker's retry logic (retry policies are declarative).

Being able to name that list is the point of having built it once.
