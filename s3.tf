data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "app_bucket" {
  bucket = "s3-placesss-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name        = "s3-placesss"
    Environment = "production"
  }
}

resource "aws_s3_bucket_public_access_block" "app_bucket" {
  bucket = aws_s3_bucket.app_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "app_bucket" {
  bucket = aws_s3_bucket.app_bucket.id

  versioning_configuration {
    status = "Enabled"
  }
}
