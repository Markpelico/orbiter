# Bootstrap: the one-time, near-zero-cost foundation everything else stands on.
# Uses LOCAL state on purpose — it creates the bucket that every other stack
# stores its state in. The chicken lays this egg exactly once.
terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      project    = "orbiter"
      managed_by = "terraform"
      stack      = "bootstrap"
    }
  }
}
