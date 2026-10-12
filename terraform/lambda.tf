locals {
  lambda_s3_key = "lambda/text2sql/text2sql.zip"
}

module "text2sql_label" {
  source  = "cloudposse/label/null"
  version = "0.25.0"
  name    = "text2sql"
  context = module.global_label.context
}

module "text2sql_lambda" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.9.0"

  function_name                  = "text2sql-lambda"
  description                    = "Lambda to run the text2sql LangGraph workflow."
  runtime                        = "python3.12"
  handler                        = "lambda_entrypoint.lambda_handler"
  timeout                        = 300
  memory_size                    = 2048
  ephemeral_storage_size         = 2048 # /tmp holds the downloaded SQLite databases
  reserved_concurrent_executions = 10

  # Code is built and uploaded by the CI pipeline; Terraform only points the function at it
  create_package = false
  s3_existing_package = {
    bucket = aws_s3_bucket.deployment_codes.id
    key    = local.lambda_s3_key
  }

  cloudwatch_logs_retention_in_days = 60 # the module also attaches the policy to write these logs

  attach_policy_json = true
  policy_json        = data.aws_iam_policy_document.text2sql_lambda.json

  environment_variables = {
    DATABASE_BUCKET = aws_s3_bucket.deployment_codes.id
  }

  tags = merge(module.text2sql_label.tags, var.default_tags)
}
