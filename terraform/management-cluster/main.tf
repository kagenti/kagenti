terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Using local state for now
  # To use S3 backend, uncomment and configure backend.tfvars
  # backend "s3" {
  #   # Backend config provided via -backend-config flags or environment
  #   # See terraform/management-cluster/backend.tfvars.example
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      "kagenti.io/managed-by" = var.managed_by_tag
      "kagenti.io/purpose"    = "hypershift-management-cluster"
      "kagenti.io/ocp-version" = var.ocp_version
    }
  }
}

# ============================================================================
# OpenShift Management Cluster via IPI
# ============================================================================
# This Terraform creates infrastructure for an OpenShift management cluster
# that will host the HyperShift operator and MCE 2.10 for creating hosted
# clusters (supports OpenShift 4.19-4.21).
#
# We use the OpenShift IPI (Installer Provisioned Infrastructure) approach,
# which means we pre-create minimal infrastructure and let openshift-install
# handle the rest.
# ============================================================================

# VPC for management cluster
# trivy:ignore:AVD-AWS-0178 VPC Flow Logs not required for basic OpenShift operation
resource "aws_vpc" "mgmt_cluster" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.cluster_name}-vpc"
  }
}

# Internet Gateway
resource "aws_internet_gateway" "mgmt_cluster" {
  vpc_id = aws_vpc.mgmt_cluster.id

  tags = {
    Name = "${var.cluster_name}-igw"
  }
}

# Public subnets (for load balancers and NAT gateways)
# trivy:ignore:AVD-AWS-0164 Public IP assignment required for OpenShift IPI installation
resource "aws_subnet" "public" {
  count = length(var.availability_zones)

  vpc_id                  = aws_vpc.mgmt_cluster.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, count.index)
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name                                        = "${var.cluster_name}-public-${var.availability_zones[count.index]}"
    "kubernetes.io/role/elb"                   = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

# Private subnets (for OpenShift nodes)
resource "aws_subnet" "private" {
  count = length(var.availability_zones)

  vpc_id            = aws_vpc.mgmt_cluster.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, count.index + length(var.availability_zones))
  availability_zone = var.availability_zones[count.index]

  tags = {
    Name                                        = "${var.cluster_name}-private-${var.availability_zones[count.index]}"
    "kubernetes.io/role/internal-elb"          = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

# Elastic IPs for NAT Gateways
resource "aws_eip" "nat" {
  count  = length(var.availability_zones)
  domain = "vpc"

  tags = {
    Name = "${var.cluster_name}-nat-${var.availability_zones[count.index]}"
  }

  depends_on = [aws_internet_gateway.mgmt_cluster]
}

# NAT Gateways
resource "aws_nat_gateway" "mgmt_cluster" {
  count = length(var.availability_zones)

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = {
    Name = "${var.cluster_name}-nat-${var.availability_zones[count.index]}"
  }
}

# Public route table
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.mgmt_cluster.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.mgmt_cluster.id
  }

  tags = {
    Name = "${var.cluster_name}-public-rt"
  }
}

# Associate public subnets with public route table
resource "aws_route_table_association" "public" {
  count = length(var.availability_zones)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Private route tables (one per AZ for high availability)
resource "aws_route_table" "private" {
  count = length(var.availability_zones)

  vpc_id = aws_vpc.mgmt_cluster.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.mgmt_cluster[count.index].id
  }

  tags = {
    Name = "${var.cluster_name}-private-rt-${var.availability_zones[count.index]}"
  }
}

# Associate private subnets with private route tables
resource "aws_route_table_association" "private" {
  count = length(var.availability_zones)

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# ============================================================================
# Output infrastructure details for openshift-install
# ============================================================================

# Generate install-config.yaml template
resource "local_file" "install_config_template" {
  filename = "${path.module}/output/install-config.yaml.tpl"
  content  = templatefile("${path.module}/templates/install-config.yaml.tpl", {
    cluster_name       = var.cluster_name
    base_domain        = var.base_domain
    aws_region         = var.aws_region
    vpc_cidr           = var.vpc_cidr
    pull_secret        = "PULL_SECRET_PLACEHOLDER"  # Will be replaced by script
    ssh_public_key     = "SSH_KEY_PLACEHOLDER"      # Will be replaced by script
    worker_replicas    = var.worker_replicas
    master_replicas    = var.master_replicas
    worker_type        = var.worker_instance_type
    master_type        = var.master_instance_type
    availability_zones = var.availability_zones
    private_subnets    = join(",", aws_subnet.private[*].id)
    public_subnets     = join(",", aws_subnet.public[*].id)
  })
}

# Save metadata for post-install scripts
resource "local_file" "cluster_metadata" {
  filename = "${path.module}/output/cluster-metadata.json"
  content = jsonencode({
    cluster_name       = var.cluster_name
    base_domain        = var.base_domain
    aws_region         = var.aws_region
    ocp_version        = var.ocp_version
    vpc_id             = aws_vpc.mgmt_cluster.id
    private_subnet_ids = aws_subnet.private[*].id
    public_subnet_ids  = aws_subnet.public[*].id
    availability_zones = var.availability_zones
    managed_by_tag     = var.managed_by_tag
  })
}
