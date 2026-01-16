#########################################
# OCI Cache (Valkey) — same VCN/subnet #
#########################################
# NOTE: Confirm resource types/arguments with your OCI Terraform provider version.
# This is a scaffold to be adjusted to the provider's current spec.

locals {
  cache_subnet_id = var.create_vcn_subnet == true ? oci_core_subnet.vcn1_psql_priv_subnet[0].id : var.psql_subnet_ocid
}



# Cache cluster (Valkey / Redis on OCI)

resource "oci_redis_redis_cluster" "spacesai_cache" {
  count                = var.enable_cache == true ? 1 : 0
  compartment_id       = var.compartment_ocid
  display_name         = var.cache_display_name
  node_count           = var.cache_node_count
  node_memory_in_gbs   = var.cache_memory_gbs

  software_version     = var.redis_software_version
  subnet_id            = local.cache_subnet_id
  freeform_tags        = { "app" = "spacesai" }
}
