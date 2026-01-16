# Local full tfvars for OCI PostgreSQL + OpenSearch + Valkey
# Fill the REQUIRED fields before running terraform locally

# ----------------------
# Core / Provider region
# ----------------------
region = "us-ashburn-1"
# REQUIRED: compartment OCID for all resources
compartment_ocid = "REQUIRED_FILL_ME"
# Optional: tenancy OCID used only for AD discovery in this stack (leave empty to use compartment_ocid)
tenancy_ocid = ""

# ----------------------
# Networking
# ----------------------
create_service_gateway = true
create_vcn_subnet      = true
# When using existing subnets, set create_vcn_subnet=false and provide these OCIDs
psql_subnet_ocid   = ""
public_subnet_ocid = ""
# VCN CIDR(s)
vcn_cidr = ["10.10.0.0/16"]

# ----------------------
# PostgreSQL credentials
# ----------------------
# Admin username (required)
psql_admin = "pgadmin"
# Optional: leave blank to auto-generate a strong password
psql_admin_password = ""

# ----------------------
# PostgreSQL DB System
# ----------------------
psql_version   = 16
inst_count     = 1
num_ocpu       = 2
psql_shape_name = "PostgreSQL.VM.Standard.E5.Flex"
# IOPS profile mapping (keep defaults)
psql_iops = {
  75  = 75000
  150 = 150000
  225 = 225000
  300 = 300000
}

# ----------------------
# Optional Compute
# ----------------------
create_compute           = false
compute_shape            = "VM.Standard.E5.Flex"
compute_ocpus            = 1
compute_memory_in_gbs    = 8
compute_assign_public_ip = false
compute_display_name     = "app-host-1"
compute_ssh_public_key   = ""
compute_image_ocid       = ""
compute_nsg_ids          = []
compute_boot_volume_size_in_gbs = 50

# ----------------------
# Object Storage
# ----------------------
object_storage_bucket_name = "search-app-uploads"

# ----------------------------------------
# PostgreSQL Configuration (optional/on)
# ----------------------------------------
create_psql_configuration   = true
psql_configuration_ocid     = ""
psql_config_display_name    = "livelab_flexible_configuration"
psql_config_is_flexible     = true
psql_config_compatible_shapes = [
  "VM.Standard.E5.Flex",
  "VM.Standard.E6.Flex",
  "VM.Standard3.Flex"
]
psql_config_description     = "test configuration created by terraform"
psql_config_overrides = {
  "oci.admin_enabled_extensions" = "pg_stat_statements,pglogical,vector"
  "pglogical.conflict_log_level" = "debug1"
  "pg_stat_statements.max"       = "5000"
}

# ----------------------
# OpenSearch (OCI)
# ----------------------
enable_opensearch      = true
opensearch_display_name = "spacesai-opensearch"
opensearch_version      = "3.2.0"

# Data nodes
opensearch_node_count        = 3
opensearch_ocpus             = 2
opensearch_memory_gbs        = 16
opensearch_storage_gbs       = 200
opensearch_data_node_host_type = "FLEX"   # FLEX | BM
# Master nodes
opensearch_master_node_count               = 3
opensearch_master_node_host_ocpu_count     = 2
opensearch_master_node_host_memory_gb      = 16
opensearch_master_node_host_type           = "FLEX"  # FLEX | BM
# Dashboard nodes
opensearch_opendashboard_node_count           = 1
opensearch_opendashboard_node_host_ocpu_count = 1
opensearch_opendashboard_node_host_memory_gb  = 16

# Security (optional): provide only if you want to set master user
opensearch_security_mode       = "ENFORCING"
opensearch_admin_user          = null
opensearch_admin_password_hash = null

# ----------------------
# Valkey (OCI Redis)
# ----------------------
enable_cache       = true
# legacy display name (unused by resources in this stack but kept for compatibility)
cache_display_name = "spacesai-cache"
redis_display_name = "spacesai-valkey"
redis_node_count   = 1
redis_node_memory_gbs  = 2
redis_software_version = "VALKEY_7_2"
