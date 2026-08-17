# main.tf — DB subnet group + all engine variants

resource "aws_db_subnet_group" "main" {
  count      = var.db_engine != null ? 1 : 0
  name       = "${var.environment_name}-db-subnet-group"
  subnet_ids = var.private_subnet_ids
  tags       = { Name = "${var.environment_name}-db-subnet-group" }
}

# ---------------------------------------------------------------------------
# RDS MySQL (single instance)
# ---------------------------------------------------------------------------

resource "aws_db_parameter_group" "mysql" {
  count  = var.db_engine == "rds_mysql" ? 1 : 0
  name   = "${var.environment_name}-mysql-params"
  family = "mysql8.0"

  parameter { name = "require_secure_transport"; value = "ON" }
  parameter { name = "slow_query_log";           value = "1" }
  parameter { name = "long_query_time";          value = "2" }

  tags = { Name = "${var.environment_name}-mysql-params" }
}

resource "aws_db_instance" "mysql" {
  count = var.db_engine == "rds_mysql" ? 1 : 0

  identifier        = "${var.environment_name}-mysql"
  engine            = "mysql"
  engine_version    = "8.0"
  instance_class    = var.db_instance_class
  allocated_storage = var.db_allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main[0].name
  vpc_security_group_ids = [var.sg_rds_id]
  parameter_group_name   = aws_db_parameter_group.mysql[0].name

  multi_az            = var.db_multi_az
  publicly_accessible = false
  deletion_protection = var.db_deletion_protection
  skip_final_snapshot = var.db_skip_final_snapshot
  final_snapshot_identifier = var.db_skip_final_snapshot ? null : "${var.environment_name}-mysql-final"

  backup_retention_period         = var.db_backup_retention_days
  backup_window                   = "02:00-03:00"
  maintenance_window              = "sun:04:00-sun:05:00"
  enabled_cloudwatch_logs_exports = ["error", "general", "slowquery"]

  tags = { Name = "${var.environment_name}-mysql" }
}

# ---------------------------------------------------------------------------
# Aurora MySQL cluster
# ---------------------------------------------------------------------------

resource "aws_rds_cluster_parameter_group" "aurora_mysql" {
  count  = var.db_engine == "aurora_mysql" ? 1 : 0
  name   = "${var.environment_name}-aurora-mysql-params"
  family = "aurora-mysql8.0"

  parameter { name = "require_secure_transport"; value = "ON" }
  parameter { name = "slow_query_log";           value = "1" }

  tags = { Name = "${var.environment_name}-aurora-mysql-params" }
}

resource "aws_rds_cluster" "aurora_mysql" {
  count = var.db_engine == "aurora_mysql" ? 1 : 0

  cluster_identifier      = "${var.environment_name}-aurora-mysql"
  engine                  = "aurora-mysql"
  engine_version          = "8.0.mysql_aurora.3.05.2"
  database_name           = var.db_name
  master_username         = var.db_username
  master_password         = var.db_password

  db_subnet_group_name            = aws_db_subnet_group.main[0].name
  vpc_security_group_ids          = [var.sg_rds_id]
  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.aurora_mysql[0].name

  storage_encrypted            = true
  deletion_protection          = var.db_deletion_protection
  skip_final_snapshot          = var.db_skip_final_snapshot
  final_snapshot_identifier    = var.db_skip_final_snapshot ? null : "${var.environment_name}-aurora-final"
  backup_retention_period      = var.db_backup_retention_days
  preferred_backup_window      = "02:00-03:00"
  preferred_maintenance_window = "sun:04:00-sun:05:00"
  enabled_cloudwatch_logs_exports = ["error", "general", "slowquery", "audit"]

  tags = { Name = "${var.environment_name}-aurora-mysql" }
}

resource "aws_rds_cluster_instance" "aurora_mysql" {
  count = var.db_engine == "aurora_mysql" ? var.aurora_instance_count : 0

  identifier         = "${var.environment_name}-aurora-mysql-${count.index}"
  cluster_identifier = aws_rds_cluster.aurora_mysql[0].id
  engine             = aws_rds_cluster.aurora_mysql[0].engine
  engine_version     = aws_rds_cluster.aurora_mysql[0].engine_version
  instance_class     = var.db_instance_class

  publicly_accessible          = false
  auto_minor_version_upgrade   = true
  performance_insights_enabled = var.enable_performance_insights

  tags = { Name = "${var.environment_name}-aurora-mysql-${count.index}" }
}

# ---------------------------------------------------------------------------
# RDS PostgreSQL (single instance)
# ---------------------------------------------------------------------------

resource "aws_db_parameter_group" "postgres" {
  count  = var.db_engine == "rds_postgres" ? 1 : 0
  name   = "${var.environment_name}-postgres-params"
  family = "postgres16"

  parameter { name = "log_min_duration_statement"; value = "2000" }

  tags = { Name = "${var.environment_name}-postgres-params" }
}

resource "aws_db_instance" "postgres" {
  count = var.db_engine == "rds_postgres" ? 1 : 0

  identifier        = "${var.environment_name}-postgres"
  engine            = "postgres"
  engine_version    = "16"
  instance_class    = var.db_instance_class
  allocated_storage = var.db_allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main[0].name
  vpc_security_group_ids = [var.sg_rds_id]
  parameter_group_name   = aws_db_parameter_group.postgres[0].name

  multi_az            = var.db_multi_az
  publicly_accessible = false
  deletion_protection = var.db_deletion_protection
  skip_final_snapshot = var.db_skip_final_snapshot
  final_snapshot_identifier = var.db_skip_final_snapshot ? null : "${var.environment_name}-postgres-final"

  backup_retention_period         = var.db_backup_retention_days
  backup_window                   = "02:00-03:00"
  maintenance_window              = "sun:04:00-sun:05:00"
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  tags = { Name = "${var.environment_name}-postgres" }
}

# ---------------------------------------------------------------------------
# Aurora PostgreSQL cluster
# ---------------------------------------------------------------------------

resource "aws_rds_cluster_parameter_group" "aurora_postgres" {
  count  = var.db_engine == "aurora_postgres" ? 1 : 0
  name   = "${var.environment_name}-aurora-postgres-params"
  family = "aurora-postgresql16"

  parameter { name = "log_min_duration_statement"; value = "2000" }

  tags = { Name = "${var.environment_name}-aurora-postgres-params" }
}

resource "aws_rds_cluster" "aurora_postgres" {
  count = var.db_engine == "aurora_postgres" ? 1 : 0

  cluster_identifier      = "${var.environment_name}-aurora-postgres"
  engine                  = "aurora-postgresql"
  engine_version          = "16.2"
  database_name           = var.db_name
  master_username         = var.db_username
  master_password         = var.db_password

  db_subnet_group_name            = aws_db_subnet_group.main[0].name
  vpc_security_group_ids          = [var.sg_rds_id]
  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.aurora_postgres[0].name

  storage_encrypted            = true
  deletion_protection          = var.db_deletion_protection
  skip_final_snapshot          = var.db_skip_final_snapshot
  final_snapshot_identifier    = var.db_skip_final_snapshot ? null : "${var.environment_name}-aurora-pg-final"
  backup_retention_period      = var.db_backup_retention_days
  preferred_backup_window      = "02:00-03:00"
  preferred_maintenance_window = "sun:04:00-sun:05:00"
  enabled_cloudwatch_logs_exports = ["postgresql"]

  tags = { Name = "${var.environment_name}-aurora-postgres" }
}

resource "aws_rds_cluster_instance" "aurora_postgres" {
  count = var.db_engine == "aurora_postgres" ? var.aurora_instance_count : 0

  identifier         = "${var.environment_name}-aurora-postgres-${count.index}"
  cluster_identifier = aws_rds_cluster.aurora_postgres[0].id
  engine             = aws_rds_cluster.aurora_postgres[0].engine
  engine_version     = aws_rds_cluster.aurora_postgres[0].engine_version
  instance_class     = var.db_instance_class

  publicly_accessible          = false
  auto_minor_version_upgrade   = true
  performance_insights_enabled = var.enable_performance_insights

  tags = { Name = "${var.environment_name}-aurora-postgres-${count.index}" }
}
