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
  display_name         = var.redis_display_name
  node_count           = var.redis_node_count
  node_memory_in_gbs   = var.redis_node_memory_gbs
  software_version     = var.redis_software_version
  subnet_id            = local.cache_subnet_id
  freeform_tags        = { "app" = "spacesai" }
}

# Optional Cache user (password-auth) and attach to cluster
resource "oci_redis_oci_cache_user" "default_cache_user" {
  # Only create the user when hashed passwords are provided to satisfy provider requirements
  count          = var.enable_cache == true && var.create_cache_user == true && length(var.cache_user_hashed_passwords) > 0 ? 1 : 0
  compartment_id = var.compartment_ocid
  name           = var.cache_user_name
  description    = var.cache_user_description
  acl_string     = var.cache_user_acl_string

  authentication_mode {
    authentication_type = "PASSWORD"
    hashed_passwords    = var.cache_user_hashed_passwords
  }

  status = var.cache_user_status

  depends_on = [oci_redis_redis_cluster.spacesai_cache]
}

resource "oci_redis_redis_cluster_attach_oci_cache_user" "attach_default_user" {
  count            = var.enable_cache == true && var.create_cache_user == true && length(var.cache_user_hashed_passwords) > 0 ? 1 : 0
  redis_cluster_id = oci_redis_redis_cluster.spacesai_cache[0].id
  oci_cache_users  = [oci_redis_oci_cache_user.default_cache_user[0].id]
  depends_on       = [oci_redis_oci_cache_user.default_cache_user]
}
