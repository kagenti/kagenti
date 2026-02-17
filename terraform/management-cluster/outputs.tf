output "vpc_id" {
  description = "VPC ID for the management cluster"
  value       = aws_vpc.mgmt_cluster.id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = aws_subnet.private[*].id
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = aws_subnet.public[*].id
}

output "cluster_name" {
  description = "Cluster name"
  value       = var.cluster_name
}

output "base_domain" {
  description = "Base domain"
  value       = var.base_domain
}

output "aws_region" {
  description = "AWS region"
  value       = var.aws_region
}

output "install_config_template" {
  description = "Path to install-config.yaml template"
  value       = local_file.install_config_template.filename
}

output "cluster_metadata_file" {
  description = "Path to cluster metadata JSON"
  value       = local_file.cluster_metadata.filename
}

output "next_steps" {
  description = "Next steps to complete OpenShift installation"
  value       = <<-EOT
    Infrastructure created successfully!

    Next steps:
    1. Run the OpenShift installer:
       ./terraform/management-cluster/scripts/install-openshift.sh

    2. After installation, install MCE 2.10:
       ./terraform/management-cluster/scripts/install-mce.sh

    3. Verify the management cluster:
       export KUBECONFIG=~/openshift-clusters/${var.cluster_name}/auth/kubeconfig
       oc get nodes
       oc get multiclusterengine
  EOT
}
