# Terraform (Phase 3)

Everything ORBITER runs on is provisioned here; there is no click-ops path.

Planned module layout:

```
bootstrap/   # one-time: state bucket + lock table, GitHub OIDC role
network/     # VPC, subnets, endpoints
cluster/     # EKS, Karpenter (spot-first NodePools + on-demand fallback),
             # KEDA, interruption queue
data/        # RDS Postgres, ElastiCache (Valkey), S3 artifacts bucket
observability/ # LGTM stack, OpenCost, Chaos Mesh
```

Ground rules:

- `make up` / `make down` build and destroy the entire platform; nothing is
  precious. Short-lived clusters are the cost-control strategy.
- CI authenticates via GitHub OIDC; no long-lived cloud keys exist anywhere.
- Every PR gets an Infracost comment before merge.

Nothing in this directory is applied yet — it lands in Phase 3 alongside an
AWS account with the free-tier credits ($100–200 for new accounts as of 2026).
