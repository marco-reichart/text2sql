output "deployment_bucket" {
  description = "S3 bucket with the Lambda code and the SQLite databases"
  value       = aws_s3_bucket.deployment_codes.id
}

output "lambda_function_name" {
  value = module.text2sql_lambda.lambda_function_name
}
