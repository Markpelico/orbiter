# Karpenter: the node autoscaler. KEDA decides how many worker PODS the queue
# needs; Karpenter notices pods that do not fit and buys NODES for them —
# spot-first — then sells the nodes back when the pods go away.
#
# The submodule provisions the controller's IAM (via EKS Pod Identity), the
# node role, and the SQS interruption queue wired to EC2 spot/health events —
# the 2-minute warning pipeline that makes graceful shutdown real.

module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 21.0"

  cluster_name = module.eks.cluster_name

  # Deterministic name: deploy/k8s/karpenter/nodeclass.yaml references it.
  node_iam_role_name            = "${var.name}-karpenter-node"
  node_iam_role_use_name_prefix = false

  queue_name = "${var.name}-karpenter-interruption"
}

resource "helm_release" "karpenter" {
  name       = "karpenter"
  namespace  = "kube-system"
  chart      = "oci://public.ecr.aws/karpenter/karpenter"
  version    = var.karpenter_chart_version
  wait       = true

  values = [yamlencode({
    settings = {
      clusterName       = module.eks.cluster_name
      interruptionQueue = module.karpenter.queue_name
    }
    # One replica: two would need pod anti-affinity across our two small
    # system nodes and doubles the standing memory bill. Controller restarts
    # are seconds; the fleet keeps running without it.
    replicas = 1
    controller = {
      resources = {
        requests = { cpu = "250m", memory = "512Mi" }
        limits   = { memory = "512Mi" }
      }
    }
  })]

  depends_on = [module.eks, module.karpenter]
}
