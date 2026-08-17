output "state_bucket_name" {
  value = aws_s3_bucket.tofu_state.bucket
}

output "lock_table_name" {
  value = aws_dynamodb_table.tofu_locks.name
}

output "logs_bucket_name" {
  value = aws_s3_bucket.logs.bucket
}

output "artefacts_bucket_name" {
  value = aws_s3_bucket.artefacts.bucket
}
