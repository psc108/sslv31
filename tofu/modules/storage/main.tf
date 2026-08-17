resource "aws_s3_bucket" "app_data" {
  count  = var.create_app_bucket ? 1 : 0
  bucket = "${var.environment_name}-app-data-${var.aws_account_id}"
  tags   = { Name = "${var.environment_name}-app-data", Environment = var.environment_name }
}

resource "aws_s3_bucket_versioning" "app_data" {
  count  = var.create_app_bucket ? 1 : 0
  bucket = aws_s3_bucket.app_data[0].id
  versioning_configuration {
    status = var.app_bucket_versioning ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "app_data" {
  count  = var.create_app_bucket ? 1 : 0
  bucket = aws_s3_bucket.app_data[0].id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "app_data" {
  count                   = var.create_app_bucket ? 1 : 0
  bucket                  = aws_s3_bucket.app_data[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "app_data" {
  count  = var.create_app_bucket && var.app_bucket_lifecycle_days > 0 ? 1 : 0
  bucket = aws_s3_bucket.app_data[0].id

  rule {
    id     = "transition-to-ia"
    status = "Enabled"
    transition { days = 30;                            storage_class = "STANDARD_IA" }
    transition { days = var.app_bucket_lifecycle_days; storage_class = "GLACIER" }
  }
}
