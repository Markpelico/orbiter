# Terraform (Phase 3)

Everything ORBITER runs on is provisioned here; there is no click-ops path.

```
bootstrap/   # APPLIED. One-time foundation: versioned+encrypted S3 state
             # bucket (S3-lockfile locking, no DynamoDB), GitHub OIDC provider
             # + orbiter-ci role (trusts exactly repo main branch — CI deploys
             # with zero stored cloud keys), monthly gross-usage budget alarm
             # (credits excluded on purpose: it fires on consumption pace,
             # not on what happened to be free). Local state, by design.
platform/    # WRITTEN, plan-verified (96 resources), NOT YET APPLIED.
             # VPC (single NAT), EKS 1.34 + 2x t3.medium system nodes,
             # Karpenter 1.14 (spot-first NodePools + on-demand fallback +
             # SQS interruption queue), KEDA 2.20, RDS Postgres 17,
             # ElastiCache Valkey 8, ECR, artifacts bucket. S3 backend in
             # the bootstrap bucket. App manifests in ../../k8s (kustomize),
             # deployed by the manual `deploy` workflow via OIDC.
             # `make up` starts the ~$0.30/hr meter; `make down` stops it.
observability/ # LATER. LGTM stack, OpenCost, Chaos Mesh.
```

Ground rules:

- `make up` / `make down` build and destroy the entire platform; nothing is
  precious. Short-lived clusters are the cost-control strategy — the EKS
  control plane bills ~$0.10/hour, so it exists only during build/demo
  sessions.
- CI authenticates via GitHub OIDC; no long-lived cloud keys exist anywhere.
- The bootstrap stack is the only long-lived one, and it rounds to $0/month.
