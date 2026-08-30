# KEDA: scales the worker Deployment on JetStream consumer lag, including
# from and to ZERO — the mechanism behind "empty queue costs nothing".
# The ScaledObject itself lives in deploy/k8s/ with the app manifests.
resource "helm_release" "keda" {
  name             = "keda"
  namespace        = "keda"
  create_namespace = true
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  version          = var.keda_chart_version
  wait             = true

  values = [yamlencode({
    resources = {
      operator = {
        requests = { cpu = "100m", memory = "256Mi" }
        limits   = { memory = "512Mi" }
      }
      metricServer = {
        requests = { cpu = "100m", memory = "256Mi" }
        limits   = { memory = "512Mi" }
      }
    }
  })]

  depends_on = [module.eks]
}
