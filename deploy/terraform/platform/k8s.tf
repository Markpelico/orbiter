# The bridge from cloud infrastructure to the app: a namespace and one
# secret carrying the connection strings Terraform just created. The app
# manifests in deploy/k8s/ mount this via envFrom and need to know nothing
# about AWS.

resource "kubernetes_namespace_v1" "orbiter" {
  metadata {
    name = "orbiter"
  }
  depends_on = [module.eks]
}

resource "kubernetes_secret_v1" "orbiter_config" {
  metadata {
    name      = "orbiter-config"
    namespace = kubernetes_namespace_v1.orbiter.metadata[0].name
  }

  data = {
    ORBITER_DATABASE_URL = "postgresql://orbiter:${random_password.db.result}@${aws_db_instance.postgres.address}:5432/orbiter"
    ORBITER_NATS_URL     = "nats://nats:4222" # in-cluster service, same namespace
    ORBITER_VALKEY_URL   = "redis://${aws_elasticache_replication_group.valkey.primary_endpoint_address}:6379/0"
  }
}
