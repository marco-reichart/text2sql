variable "account_id" {
  description = "The AWS account ID Terraform is allowed to operate against."
  type        = string
}

variable "environment" {
  type        = string
  description = <<EOT
    (Required) The name of the environment where the resources will be deployed.

    Options:
      - dev
      - preprod
      - prod

    Default: dev
  EOT
  default     = "dev"
  validation {
    condition     = can(regex("^(dev|preprod|uat|prod)$", var.environment))
    error_message = "Error: Environment name must be one of [dev, preprod, prod]."
  }
}

variable "region" {
  type        = string
  description = "(Required) The AWS region where resources will be deployed. Default is 'eu-central-1'."
  default     = "eu-central-1"
}

variable "default_tags" {
  type        = map(any)
  description = "(Optional) A map of default tags to apply to all resources."
}

variable "name" {
  type        = string
  description = "(Required) The name of the project or application, used for naming resources."
}

variable "bedrock_model_ids" {
  type        = list(string)
  description = "(Optional) Bedrock models the Lambda may call; must match the bedrock LLMs in src/config/config.yaml."
  default     = ["qwen.qwen3-32b-v1:0"]
}
