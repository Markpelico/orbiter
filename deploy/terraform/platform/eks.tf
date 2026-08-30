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

  addons = {
    coredns                = {}
    kube-proxy             = {}
    vpc-cni                = {}
    eks-pod-identity-agent = {}
    aws-ebs-csi-driver     = {} # NATS JetStream persistence needs EBS volumes
  }

  # The "system" node group: a fixed, boring on-demand pair that hosts the
  # controllers (Karpenter, KEDA, CoreDNS, CSI) plus ORBITER's small services.
  # Karpenter cannot schedule itself, so it must live on nodes it does not
  # manage. Workers do NOT run here — Karpenter provisions spot capacity
  # for them (see deploy/k8s/karpenter/).
  eks_managed_node_groups = {
    system = {
      instance_types = ["t3.medium"]
      min_size       = 2
      max_size       = 3
      desired_size   = 2
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

# The EBS CSI controller can be scheduled onto ANY node, so both node roles
# (system group + Karpenter nodes) carry the policy. IRSA/pod-identity scoping
# is the tighter production answer; this is the pragmatic portfolio one.
resource "aws_iam_role_policy_attachment" "system_nodes_ebs_csi" {
  role       = module.eks.eks_managed_node_groups["system"].iam_role_name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}
