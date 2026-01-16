###############################################
# OpenSearch Cluster (OCI) — same VCN/subnet #
###############################################
# NOTE: Confirm exact resource type/attributes with your installed OCI Terraform provider.
# This file provides a working scaffold using commonly-documented types and patterns.
# If your provider uses a different name (e.g., oci_opensearch_cluster vs oci_opensearch_opensearch_cluster),
# update the resource blocks accordingly.

locals {
  os_subnet_id = var.create_vcn_subnet == true ? oci_core_subnet.vcn1_psql_priv_subnet[0].id : var.psql_subnet_ocid
}

# Network Security Group for OpenSearch (allow 9200 from inside the VCN/app NSG)


# OpenSearch Cluster
# Replace the resource type below with the correct one for your OCI provider version if necessary.
resource "oci_opensearch_opensearch_cluster" "spacesai_os" {
  count                                 = var.enable_opensearch == true ? 1 : 0
  compartment_id                         = var.compartment_ocid
  display_name                           = var.opensearch_display_name
  software_version                       = var.opensearch_version

  # Required sizing (mapped from vars)
  data_node_count                        = var.opensearch_node_count
  data_node_host_memory_gb               = var.opensearch_memory_gbs
  data_node_host_ocpu_count              = var.opensearch_ocpus
  data_node_host_type                    = var.opensearch_data_node_host_type
  data_node_storage_gb                   = var.opensearch_storage_gbs

  master_node_count                      = var.opensearch_master_node_count
  master_node_host_memory_gb             = var.opensearch_master_node_host_memory_gb
  master_node_host_ocpu_count            = var.opensearch_master_node_host_ocpu_count
  master_node_host_type                  = var.opensearch_master_node_host_type

  opendashboard_node_count               = var.opensearch_opendashboard_node_count
  opendashboard_node_host_memory_gb      = var.opensearch_opendashboard_node_host_memory_gb
  opendashboard_node_host_ocpu_count     = var.opensearch_opendashboard_node_host_ocpu_count

  # Security (optional)
  security_mode                          = var.opensearch_security_mode
  security_master_user_name              = var.opensearch_admin_user
  security_master_user_password_hash     = var.opensearch_admin_password_hash

  # Network placement (VCN + Subnet in same compartment)


  vcn_compartment_id                     = var.compartment_ocid
  vcn_id                                 = oci_core_vcn.vcn1[0].id
  subnet_compartment_id                  = var.compartment_ocid
  subnet_id                              = local.os_subnet_id
}
