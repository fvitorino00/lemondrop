# ═══════════════════════════════════════════════════════════════════════════
# BOOTSTRAP — outputs
# ═══════════════════════════════════════════════════════════════════════════
#
# These three outputs exist to be copy-pasted by a human into the `backend`
# block in `infra/versions.tf`. Terraform will NOT do that for you: backend
# blocks are parsed before any variable, resource, or data source is available,
# so they cannot interpolate anything. The copy-paste step is a real, manual
# part of this workflow and the outputs are what make it mechanical rather than
# guesswork.

output "state_bucket_name" {
  description = "Copy this into the `bucket` argument of the backend block in infra/versions.tf."
  value       = aws_s3_bucket.state.id
}

output "state_bucket_region" {
  description = "Copy this into the `region` argument of the backend block in infra/versions.tf."
  value       = var.aws_region
}

output "state_key_prefix" {
  description = "Recommended `key` prefix for the backend block in infra/versions.tf. Change only if you intend to run multiple environments from one bucket."
  value       = "lemondrop/dev/terraform.tfstate"
}
