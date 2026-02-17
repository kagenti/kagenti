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
  default     = "4.20.11"
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
