# Managed data services. The compute plane is the show; the data plane is
# deliberately boring, small, and single-AZ — a judgment call, not an
# accident (multi-AZ doubles cost to demonstrate a checkbox).

resource "random_password" "db" {
  length           = 24
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

# --- Postgres (RDS) ---------------------------------------------------------

resource "aws_db_subnet_group" "db" {
  name       = var.name
  subnet_ids = module.vpc.private_subnets
}

resource "aws_security_group" "db" {
  name   = "${var.name}-db"
  vpc_id = module.vpc.vpc_id
  ingress {
    from_port = 5432
    to_port   = 5432
    protocol  = "tcp"
    security_groups = [
      module.eks.node_security_group_id,
      module.eks.cluster_primary_security_group_id,
    ]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "postgres" {
  identifier     = var.name
  engine         = "postgres"
  engine_version = "17"
  instance_class = var.db_instance_class

  allocated_storage = 20
  storage_type      = "gp3"

  db_name  = "orbiter"
  username = "orbiter"
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.db.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = false

  # Disposable-platform settings; a system of record would set the opposite.
  skip_final_snapshot     = true
  deletion_protection     = false
  backup_retention_period = 0
  apply_immediately       = true
}

# --- Valkey (ElastiCache) ---------------------------------------------------

resource "aws_elasticache_subnet_group" "valkey" {
  name       = var.name
  subnet_ids = module.vpc.private_subnets
}

resource "aws_security_group" "valkey" {
  name   = "${var.name}-valkey"
  vpc_id = module.vpc.vpc_id
  ingress {
    from_port = 6379
    to_port   = 6379
    protocol  = "tcp"
    security_groups = [
      module.eks.node_security_group_id,
      module.eks.cluster_primary_security_group_id,
    ]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# The valkey engine only ships as a replication group; one node of one is
# still the smallest legal shape.
resource "aws_elasticache_replication_group" "valkey" {
  replication_group_id = var.name
  description          = "ORBITER hot state: idempotency keys and fenced leases"

  engine         = "valkey"
  engine_version = "8.0"
  node_type      = var.valkey_node_type
  port           = 6379

  num_cache_clusters         = 1
  automatic_failover_enabled = false

  subnet_group_name  = aws_elasticache_subnet_group.valkey.name
  security_group_ids = [aws_security_group.valkey.id]
}

# --- Images and artifacts ---------------------------------------------------

resource "aws_ecr_repository" "orbiter" {
  name         = var.name
  force_delete = true # disposable platform; images are rebuilt by CI at will
}

resource "aws_ecr_lifecycle_policy" "keep_recent" {
  repository = aws_ecr_repository.orbiter.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the 10 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "artifacts" {
  bucket        = "${var.name}-artifacts-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
