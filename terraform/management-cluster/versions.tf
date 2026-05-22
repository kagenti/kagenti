# OpenShift and MCE version compatibility matrix
#
# This file documents which OpenShift versions are supported by each MCE version
# and which hosted cluster versions can be deployed.
#
# Last updated: 2026-02-12

locals {
  # MCE version compatibility
  mce_compatibility = {
    "2.9" = {
      management_cluster_versions = ["4.18", "4.19", "4.20"]
      hosted_cluster_versions     = ["4.18", "4.19", "4.20"]
      released                    = "2025-Q4"
    }
    "2.10" = {
      management_cluster_versions = ["4.19", "4.20", "4.21"]
      hosted_cluster_versions     = ["4.19", "4.20", "4.21"]
      released                    = "2026-Q1"
    }
  }

  # This configuration uses MCE 2.10
  selected_mce_version = "2.10"

  # Extract major.minor version from full version string (e.g., "4.20" from "4.20.11")
  ocp_major_minor = join(".", slice(split(".", var.ocp_version), 0, 2))

  # Validate compatibility
  is_compatible = contains(
    local.mce_compatibility[local.selected_mce_version].management_cluster_versions,
    local.ocp_major_minor
  )
}

# Validation
resource "null_resource" "version_validation" {
  count = local.is_compatible ? 0 : 1

  provisioner "local-exec" {
    command = <<-EOT
      echo "ERROR: OpenShift ${var.ocp_version} is not compatible with MCE ${local.selected_mce_version}"
      echo "Compatible versions: ${join(", ", local.mce_compatibility[local.selected_mce_version].management_cluster_versions)}"
      exit 1
    EOT
  }
}
