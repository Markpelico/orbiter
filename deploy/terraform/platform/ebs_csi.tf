# EBS CSI controller identity — the modern answer to a modern refusal.
#
# Hardened node templates cap the IMDS hop limit at 1, so pods cannot borrow
# the node's IAM role ("no EC2 IMDS role found", found live on first boot).
# The controller gets its own role via EKS Pod Identity instead: the agent
# (installed as an addon, before_compute) injects credentials for exactly
# this service account, nothing else on the node included.
#
# The role was first created by CLI mid-apply to unblock the boot and is
# terraform-imported; the association is cluster-scoped and recreated fresh
# on every make up.

data "aws_iam_policy_document" "ebs_csi_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ebs_csi" {
  name               = "${var.name}-ebs-csi"
  assume_role_policy = data.aws_iam_policy_document.ebs_csi_trust.json
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

resource "aws_eks_pod_identity_association" "ebs_csi" {
  cluster_name    = module.eks.cluster_name
  namespace       = "kube-system"
  service_account = "ebs-csi-controller-sa"
  role_arn        = aws_iam_role.ebs_csi.arn
}
