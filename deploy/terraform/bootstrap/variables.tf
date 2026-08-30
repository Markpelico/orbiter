variable "region" {
  type    = string
  default = "us-east-1"
}

variable "github_repo" {
  description = "GitHub repo allowed to assume the CI role, owner/name form."
  type        = string
  default     = "Markpelico/orbiter"
}

variable "budget_limit_usd" {
  description = "Monthly gross-usage alarm threshold. Credits are ignored on purpose: the alarm tracks real consumption pace, not what happens to be free this month."
  type        = string
  default     = "90"
}

variable "budget_email" {
  type    = string
  default = "pelicmar@gmail.com"
}
