# Bootstrap workspace — run ONCE per AWS account to create shared infrastructure.
# After first apply, migrate state to the new S3 bucket:
#   tofu init -migrate-state
#
# This workspace is NEVER destroyed. Resources use prevent_destroy = true.

terraform {
  required_version = ">= 1.8.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  # Initially uses local state. After apply, run:
  #   tofu init -migrate-state
  # to move state into the newly created S3 bucket.
}

provider "aws" {
  region = var.aws_region
  # Credentials from env vars: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN
  default_tags {
    tags = {
      ManagedBy = "opentofu"
      Project   = "certmanager"
      Workspace = "bootstrap"
    }
  }
}
