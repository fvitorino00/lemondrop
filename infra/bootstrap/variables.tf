# ═══════════════════════════════════════════════════════════════════════════
# BOOTSTRAP — variables
# ═══════════════════════════════════════════════════════════════════════════
#
# This config creates exactly ONE resource: the S3 bucket that holds Terraform
# state for the main config in `infra/`. It is deliberately minimal. Anything
# added here is something that must exist before any real infrastructure can
# be planned, which is a very high bar.

variable "aws_region" {
  description = "AWS region for the state bucket. MUST match the region in the backend block in infra/versions.tf."
  type        = string
  default     = "eu-west-1"
}

variable "state_bucket_name" {
  description = <<-EOT
    Globally-unique name for the Terraform state bucket. S3 bucket names are
    global, so the default is a placeholder that will very likely collide with
    an existing bucket. Set it to something like
    "lemondrop-tfstate-<your-account-id>" or "lemondrop-tfstate-<a-suffix>".

    This value must be copied verbatim into the `bucket` argument of the
    backend block in infra/versions.tf — Terraform cannot reference a variable
    from inside a backend block.
  EOT
  type        = string
  default     = "lemondrop-tfstate-CHANGE-ME"
}

variable "tags" {
  description = "Tags applied to the state bucket."
  type        = map(string)
  default = {
    Project   = "lemondrop"
    ManagedBy = "terraform"
    Component = "terraform-bootstrap"
  }
}
