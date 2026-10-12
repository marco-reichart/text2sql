# Permissions of the text2sql Lambda: read the databases from S3 and call the Bedrock models
# (permissions for the CloudWatch logs are added by the Lambda module)
data "aws_iam_policy_document" "text2sql_lambda" {
  statement {
    sid       = "ReadDatabases"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.deployment_codes.arn}/databases/*"]
  }

  statement {
    sid       = "InvokeBedrockModels" # also covers the Converse API
    actions   = ["bedrock:InvokeModel"]
    resources = [for model_id in var.bedrock_model_ids : "arn:aws:bedrock:${var.region}::foundation-model/${model_id}"]
  }
}
