output "app_bucket_name" {
  value = var.create_app_bucket ? aws_s3_bucket.app_data[0].bucket : null
}
