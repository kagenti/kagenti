# Management Cluster Autoscaling Configuration
#
# Automatically scales worker nodes based on hosted cluster control plane workload.
# Each hosted cluster adds ~70 control plane pods to management workers.
#
# Tested configuration:
# - 2 hosted clusters: 3 workers sufficient
# - 5 hosted clusters: scales to 6 workers
# - Scale-up time: ~3-5 minutes
# - Scale-down time: ~10-15 minutes (with grace periods)

# ClusterAutoscaler - manages overall scaling decisions
resource "kubernetes_manifest" "cluster_autoscaler" {
  count = var.autoscaling_enabled ? 1 : 0

  manifest = {
    apiVersion = "autoscaling.openshift.io/v1"
    kind       = "ClusterAutoscaler"
    metadata = {
      name = "default"
    }
    spec = {
      podPriorityThreshold = -10
      resourceLimits = {
        maxNodesTotal = var.autoscaling_max_nodes_total
        cores = {
          min = var.autoscaling_min_cores
          max = var.autoscaling_max_cores
        }
        memory = {
          min = var.autoscaling_min_memory_gb
          max = var.autoscaling_max_memory_gb
        }
      }
      scaleDown = {
        enabled              = true
        delayAfterAdd        = var.autoscaling_scale_down_delay_after_add
        delayAfterDelete     = var.autoscaling_scale_down_delay_after_delete
        delayAfterFailure    = var.autoscaling_scale_down_delay_after_failure
        unneededTime         = var.autoscaling_scale_down_unneeded_time
        utilizationThreshold = tostring(var.autoscaling_scale_down_utilization_threshold)
      }
      balanceSimilarNodeGroups     = false
      ignoreDaemonsetsUtilization  = true
      skipNodesWithLocalStorage    = false
    }
  }
}

# Data source to discover MachineSet names (they include random suffix from installer)
data "kubernetes_resources" "machinesets" {
  count = var.autoscaling_enabled ? 1 : 0

  api_version    = "machine.openshift.io/v1beta1"
  kind           = "MachineSet"
  namespace      = "openshift-machine-api"
  # No label selector needed - all MachineSets in this namespace are workers
}

# Create a map of AZ -> MachineSet name
locals {
  machineset_map = var.autoscaling_enabled && length(data.kubernetes_resources.machinesets) > 0 ? {
    for ms in data.kubernetes_resources.machinesets[0].objects :
    # Extract AZ from MachineSet name (format: cluster-random-worker-us-east-1a)
    regex(".*-(us-[a-z]+-[0-9][a-z])$", ms.metadata.name)[0] => ms.metadata.name
  } : {}
}

# MachineAutoscaler - sets min/max workers per availability zone
resource "kubernetes_manifest" "machine_autoscaler" {
  for_each = local.machineset_map

  manifest = {
    apiVersion = "autoscaling.openshift.io/v1beta1"
    kind       = "MachineAutoscaler"
    metadata = {
      name      = "${each.value}-autoscaler"
      namespace = "openshift-machine-api"
    }
    spec = {
      minReplicas = var.autoscaling_min_replicas_per_az
      maxReplicas = var.autoscaling_max_replicas_per_az
      scaleTargetRef = {
        apiVersion = "machine.openshift.io/v1beta1"
        kind       = "MachineSet"
        name       = each.value
      }
    }
  }

  depends_on = [kubernetes_manifest.cluster_autoscaler]
}
