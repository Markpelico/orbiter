# Chaos experiments (apply day)

Cluster-level failure injection — the modes a process cannot fake from inside
(ADR-0007 covers the in-process CHAOS button).

Install Chaos Mesh on the running platform:

```
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh --create-namespace \
  --set chaosDaemon.runtime=containerd \
  --set chaosDaemon.socketPath=/run/containerd/containerd.sock
```

Run one experiment: `kubectl apply -f deploy/chaos/pod-kill.yaml` (it fires
once on apply for PodChaos; timed ones carry a `duration`). Clean up with
`kubectl delete -f`.

| Experiment | Proves | Measure |
|---|---|---|
| `pod-kill.yaml` | worker loss mid-job recovers | RUNNING→(silence)→re-STARTED gap in the audit trail |
| `broker-partition.yaml` | broker outage stalls, never loses | queue depth spike + drain; zero lost jobs |
| `clock-skew.yaml` | fencing beats TTL-lock corruption | zero double-`completed` rows (query in the file) |

Each result goes in RESULTS.md with the exact experiment file, fleet shape,
and the recording.
