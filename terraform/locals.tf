locals {
  name_prefix = "${var.name}-${var.environment}"

  common_tags = {
    Project   = "ColdGuard"
    Owner     = var.owner
    Env       = var.environment
    ManagedBy = "Terraform"
  }
}