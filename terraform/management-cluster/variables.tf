variable "cluster_name" {
  description = "Name of the OpenShift management cluster"
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,13}[a-z0-9]$", var.cluster_name))
    error_message = "Cluster name must be lowercase alphanumeric with hyphens, max 15 chars"
  }
}

variable "base_domain" {
  description = "Base domain for the cluster (e.g., example.com)"
  type        = string
}

variable "aws_region" {
  description = "AWS region for the management cluster"
  type        = string
  default     = "us-east-1"
}

variable "ocp_version" {
  description = "OpenShift version for the management cluster"
  type        = string
  default     = "4.20.13"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones to use"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "master_replicas" {
  description = "Number of control plane nodes"
  type        = number
  default     = 3
  validation {
    condition     = contains([3], var.master_replicas)
    error_message = "Must be 3 for production (HA) clusters"
  }
}

variable "worker_replicas" {
  description = "Number of worker nodes"
  type        = number
  default     = 3
}

variable "master_instance_type" {
  description = "EC2 instance type for control plane nodes"
  type        = string
  default     = "m6i.xlarge"  # 4 vCPU, 16 GB RAM
}

variable "worker_instance_type" {
  description = "EC2 instance type for worker nodes"
  type        = string
  default     = "m6i.2xlarge"  # 8 vCPU, 32 GB RAM (needed for HyperShift workloads)
}

variable "managed_by_tag" {
  description = "Tag to identify who manages this infrastructure"
  type        = string
  default     = "kagenti-hypershift-mgmt"
}

variable "kubeconfig_path" {
  description = "Path to kubeconfig for post-install configuration (autoscaling). Leave empty for infrastructure-only apply."
  type        = string
  default     = ""
}

# ============================================================================
# Autoscaling Configuration
# ============================================================================

variable "autoscaling_enabled" {
  description = "Enable cluster autoscaling for worker nodes"
  type        = bool
  default     = true
}

variable "autoscaling_min_replicas_per_az" {
  description = "Minimum worker replicas per availability zone"
  type        = number
  default     = 1
  validation {
    condition     = var.autoscaling_min_replicas_per_az >= 0 && var.autoscaling_min_replicas_per_az <= 10
    error_message = "Must be between 0 and 10"
  }
}

variable "autoscaling_max_replicas_per_az" {
  description = "Maximum worker replicas per availability zone"
  type        = number
  default     = 4
  validation {
    condition     = var.autoscaling_max_replicas_per_az >= 1 && var.autoscaling_max_replicas_per_az <= 20
    error_message = "Must be between 1 and 20"
  }
}

variable "autoscaling_max_nodes_total" {
  description = "Maximum total worker nodes across all availability zones"
  type        = number
  default     = 15
  validation {
    condition     = var.autoscaling_max_nodes_total >= 3 && var.autoscaling_max_nodes_total <= 100
    error_message = "Must be between 3 and 100"
  }
}

variable "autoscaling_min_cores" {
  description = "Minimum total CPU cores for autoscaling"
  type        = number
  default     = 8
}

variable "autoscaling_max_cores" {
  description = "Maximum total CPU cores for autoscaling"
  type        = number
  default     = 120
}

variable "autoscaling_min_memory_gb" {
  description = "Minimum total memory in GB for autoscaling"
  type        = number
  default     = 4
}

variable "autoscaling_max_memory_gb" {
  description = "Maximum total memory in GB for autoscaling"
  type        = number
  default     = 256
}

# Scale-down behavior
variable "autoscaling_scale_down_delay_after_add" {
  description = "Delay before scaling down after a scale up (e.g., 10m)"
  type        = string
  default     = "10m"
}

variable "autoscaling_scale_down_delay_after_delete" {
  description = "Delay before scaling down after node deletion (e.g., 10m)"
  type        = string
  default     = "10m"
}

variable "autoscaling_scale_down_delay_after_failure" {
  description = "Delay before scaling down after a failure (e.g., 3m)"
  type        = string
  default     = "3m"
}

variable "autoscaling_scale_down_unneeded_time" {
  description = "Time a node must be unneeded before scale down (e.g., 10m)"
  type        = string
  default     = "10m"
}

variable "autoscaling_scale_down_utilization_threshold" {
  description = "Node utilization threshold for scale down (0.0-1.0)"
  type        = number
  default     = 0.5
  validation {
    condition     = var.autoscaling_scale_down_utilization_threshold >= 0.0 && var.autoscaling_scale_down_utilization_threshold <= 1.0
    error_message = "Must be between 0.0 and 1.0"
  }
}
