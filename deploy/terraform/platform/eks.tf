module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  name               = var.name
  kubernetes_version = var.kubernetes_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Public API endpoint so laptop + GitHub runners can reach the control
  # plane without a bastion or VPN. Auth is still IAM; this is reachability,
  # not exposure.
  endpoint_public_access                   = true
  enable_cluster_creator_admin_permissions = true

  # IAM authentication is not Kubernetes authorization: the CI role could
  # assume itself into AWS all day and still be a stranger to the cluster.
  # This access entry is what lets the deploy workflow run kubectl.
  access_entries = {
    ci = {
      principal_arn = "arn:aws:iam::907797501994:role/orbiter-ci"
      policy_associations = {
        admin = {
          policy_arn   = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = { type = "cluster" }
        }
      }
    }
  }

  # before_compute on the networking addons, or the cluster deadlocks on
  # first boot: the module installs addons AFTER the node group by default,
  # but a node cannot go Ready without the CNI — so the node group waits on
  # a Ready node, the CNI waits on the node group, and nothing ever finishes.
  # Diagnosed live: node Registered, NotReady, zero pods cluster-wide.
  addons = {
    vpc-cni                = { before_compute = true }
    kube-proxy             = { before_compute = true }
    eks-pod-identity-agent = { before_compute = true }
    coredns                = {}
    aws-ebs-csi-driver     = {} # NATS JetStream persistence needs EBS volumes
  }

  # The "system" node group: a fixed, boring on-demand pair that hosts the
  # controllers (Karpenter, KEDA, CoreDNS, CSI) plus ORBITER's small services.
  # Karpenter cannot schedule itself, so it must live on nodes it does not
  # manage. Workers do NOT run here — Karpenter provisions spot capacity
  # for them (see deploy/k8s/karpenter/).
  # FREE-PLAN CONSTRAINT: the AWS Free account plan refuses to launch any
  # instance type that is not free-tier-eligible, and the account carries a
  # 5-vCPU on-demand quota. Verified eligible in us-east-1 (2026-08):
  # m7i-flex.large (2c/8GB), c7i-flex.large (2c/4GB), t3.small, t3/t4g.micro.
  # So: ONE 8GB system node instead of two 4GB ones — same controller
  # capacity, half the vCPU budget (2 of 5). Fleet quotas live in
  # deploy/k8s/karpenter/nodepools.yaml.
  eks_managed_node_groups = {
    system = {
      instance_types = ["m7i-flex.large"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
    }
  }

  # Karpenter's EC2NodeClass discovers subnets and security groups by this tag.
  node_security_group_tags = {
    "karpenter.sh/discovery" = var.name
  }

  tags = {
    "karpenter.sh/discovery" = var.name
  }
}

# (EBS CSI credentials: see ebs_csi.tf — Pod Identity, not node roles.
# Node-role policy attachments were dead weight: the IMDS hop limit stops
# pods from using them anyway.)
