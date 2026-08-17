output "db_endpoint" {
  value = (
    var.db_engine == "rds_mysql"      ? aws_db_instance.mysql[0].endpoint :
    var.db_engine == "aurora_mysql"   ? aws_rds_cluster.aurora_mysql[0].endpoint :
    var.db_engine == "rds_postgres"   ? aws_db_instance.postgres[0].endpoint :
    var.db_engine == "aurora_postgres" ? aws_rds_cluster.aurora_postgres[0].endpoint :
    null
  )
}

output "db_reader_endpoint" {
  value = (
    var.db_engine == "aurora_mysql"    ? aws_rds_cluster.aurora_mysql[0].reader_endpoint :
    var.db_engine == "aurora_postgres" ? aws_rds_cluster.aurora_postgres[0].reader_endpoint :
    null
  )
}

output "db_port" {
  value = (
    var.db_engine == "rds_mysql" || var.db_engine == "aurora_mysql" ? 3306 :
    var.db_engine == "rds_postgres" || var.db_engine == "aurora_postgres" ? 5432 :
    null
  )
}
