output "tfstate_bucket" {
  value = aws_s3_bucket.tfstate.bucket
}

output "ci_role_arn" {
  description = "Set as AWS_ROLE_ARN in the GitHub Actions deploy workflow."
  value       = aws_iam_role.ci.arn
}

output "account_id" {
  value = data.aws_caller_identity.current.account_id
}
