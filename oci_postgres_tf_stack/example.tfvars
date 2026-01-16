# Example tfvars for full stack (PostgreSQL + OpenSearch + Valkey)

# Core
region = "us-ashburn-1"
# REQUIRED: fill with your compartment OCID
# compartment_ocid = "ocid1.compartment.oc1..example..."
# tenancy_ocid     = ""

# Networking
create_vcn_subnet      = true
create_service_gateway = true
vcn_cidr               = ["10.10.0.0/16"]
# Use existing subnets when create_vcn_subnet=false
# psql_subnet_ocid   = "ocid1.subnet.oc1..example..."
# public_subnet_ocid = "ocid1.subnet.oc1..example..."

# PostgreSQL
psql_admin  = "pgadmin"
# Optional: leave blank to auto-generate a strong password
psql_admin_password = ""
psql_version = 16
num_ocpu     = 2
inst_count   = 1
psql_shape_name = "PostgreSQL.VM.Standard.E5.Flex"

# PostgreSQL Configuration (optional/default-enabled)
create_psql_configuration = true
psql_configuration_ocid   = ""
psql_config_display_name  = "livelab_flexible_configuration"
psql_config_is_flexible   = true
psql_config_compatible_shapes = ["VM.Standard.E5.Flex", "VM.Standard.E6.Flex", "VM.Standard3.Flex"]
psql_config_description   = "test configuration created by terraform"
psql_config_overrides = {
  "oci.admin_enabled_extensions" = "pg_stat_statements,pglogical,vector"
  "pglogical.conflict_log_level" = "debug1"
  "pg_stat_statements.max"       = "5000"
}

# Object Storage
object_storage_bucket_name = "search-app-uploads"

# OpenSearch (OCI)
enable_opensearch      = true
opensearch_display_name = "spacesai-opensearch"
opensearch_version      = "3.2.0"

# Data nodes
opensearch_node_count  = 3
opensearch_ocpus       = 2
opensearch_memory_gbs  = 16
opensearch_storage_gbs = 200
opensearch_data_node_host_type = "FLEX"
# Master nodes
opensearch_master_node_count               = 3
opensearch_master_node_host_ocpu_count     = 2
opensearch_master_node_host_memory_gb      = 16
opensearch_master_node_host_type           = "FLEX"
# Dashboard nodes
opensearch_opendashboard_node_count           = 1
opensearch_opendashboard_node_host_ocpu_count = 1
opensearch_opendashboard_node_host_memory_gb  = 8
# Security (optional): provide only if you want to set master user
opensearch_security_mode        = "ENFORCING"
opensearch_admin_user           = null
opensearch_admin_password_hash  = null

# Valkey (OCI Redis)
enable_cache       = true
redis_display_name = "spacesai-valkey"
redis_node_count   = 1
redis_node_memory_gbs  = 2
redis_software_version = "VALKEY_7_2"
# Optional Cache User (disabled by default)
create_cache_user           = false
cache_user_name             = "default"
cache_user_description      = "Default Cache user"
cache_user_acl_string       = "+@all"
cache_user_status           = "ON"
# Provide at least one hashed password to enable user creation; leave empty to skip
cache_user_hashed_passwords = []
