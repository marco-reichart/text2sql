data "aws_caller_identity" "current" {}

# Select the AWS as the environment
provider "aws" {
  allowed_account_ids = [var.account_id]
  region              = var.region
}

# Setup remote state
terraform {
  required_version = ">= 1.11, <2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.44.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }

  backend "s3" {
    use_lockfile = true
    region       = "eu-central-1"
  }
}
