variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  description = "Base name for everything. Also hardcoded in deploy/k8s YAML — change both or neither."
  type        = string
  default     = "orbiter"
}

variable "kubernetes_version" {
  type    = string
  default = "1.34"
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

# Two AZs is the minimum EKS accepts. One NAT gateway, not one per AZ:
# this is a portfolio platform, and the ~$65/month second NAT buys
# availability theater, not a lesson.
variable "az_count" {
  type    = number
  default = 2
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "valkey_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "karpenter_chart_version" {
  type    = string
  default = "1.14.1"
}

variable "keda_chart_version" {
  type    = string
  default = "2.20.2"
}
