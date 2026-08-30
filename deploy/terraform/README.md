# Terraform (Phase 3)

Everything ORBITER runs on is provisioned here; there is no click-ops path.

```
bootstrap/   # APPLIED. One-time foundation: versioned+encrypted S3 state
             # bucket (S3-lockfile locking, no DynamoDB), GitHub OIDC provider
             # + orbiter-ci role (trusts exactly repo main branch — CI deploys
             # with zero stored cloud keys), monthly gross-usage budget alarm
             # (credits excluded on purpose: it fires on consumption pace,
             # not on what happened to be free). Local state, by design.
platform/    # NEXT. VPC, EKS, Karpenter (spot-first NodePools + on-demand
             # fallback, interruption queue), KEDA, RDS Postgres, ElastiCache
             # (Valkey), artifacts bucket. S3 backend in the bootstrap bucket.
observability/ # LATER. LGTM stack, OpenCost, Chaos Mesh.
```

Ground rules:

- `make up` / `make down` build and destroy the entire platform; nothing is
  precious. Short-lived clusters are the cost-control strategy — the EKS
  control plane bills ~$0.10/hour, so it exists only during build/demo
  sessions.
- CI authenticates via GitHub OIDC; no long-lived cloud keys exist anywhere.
- The bootstrap stack is the only long-lived one, and it rounds to $0/month.
