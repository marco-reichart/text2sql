#####
# Common S3 Buckets
#####

# Holds the Lambda code (lambda/text2sql/text2sql.zip) and the SQLite databases (databases/<db_id>/<db_id>.sqlite)
resource "aws_s3_bucket" "deployment_codes" {
  bucket = "${module.global_label.id}-deployment-code"
  tags = merge(
    module.global_label.tags,
    {
      "Name"    = "${module.global_label.id}-deployment-code",
      "Project" = "text2sql"
    }
  )
}

resource "aws_s3_bucket_public_access_block" "deployment_codes" {
  bucket                  = aws_s3_bucket.deployment_codes.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
