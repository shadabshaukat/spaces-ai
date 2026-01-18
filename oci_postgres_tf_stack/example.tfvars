# Example tfvars for full stack (PostgreSQL + OpenSearch + Valkey)

# Core
region = "mx-queretaro-1"
compartment_ocid = "ocid1.compartment.oc1..aaaaaaaadfdmligjm7aefhatq6n5s2stavjgfq56n7vbnhjpxry7tiqjgmfa"
tenancy_ocid     = "ocid1.tenancy.oc1..aaaaaaaafhegmvy2da7xzh2b5jbmhdkfr4cr4e37m5filt4zgxs6mfl7icua"

# Networking
create_vcn_subnet      = true
create_service_gateway = true
vcn_cidr               = ["10.10.0.0/16"]
# Use existing subnets when create_vcn_subnet=false
# psql_subnet_ocid   = "ocid1.subnet.oc1..example..."
# public_subnet_ocid = "ocid1.subnet.oc1..example..."

# PostgreSQL
psql_admin  = "postgres"
# Optional: leave blank to auto-generate a strong password
psql_admin_password = "RAbbithole1234##"
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
  "pg_stat_statements.max"       = "5000"
  "pglogical.conflict_log_level" = "debug1"
  "wal_level"                    = "logical"
  "track_commit_timestamp"       = "1"
  "max_wal_size"                 = "10240"
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
opensearch_memory_gbs  = 20
opensearch_storage_gbs = 200
opensearch_data_node_host_type = "FLEX"
# Master nodes
opensearch_master_node_count               = 3
opensearch_master_node_host_ocpu_count     = 2
opensearch_master_node_host_memory_gb      = 20
opensearch_master_node_host_type           = "FLEX"
# Dashboard nodes
opensearch_opendashboard_node_count           = 1
opensearch_opendashboard_node_host_ocpu_count = 2
opensearch_opendashboard_node_host_memory_gb  = 16
# Security (optional)
opensearch_security_mode        = "ENFORCING"
opensearch_admin_user           = "osmaster"
opensearch_admin_password_hash  = "pbkdf2_stretch_1000$qIGFqgw8YfVKa2yUpX4NYr2mcpWfRph7$3YcIAfLawNaKDf4QHzebHMLUjcB2VEmYEUAkEVnwfZo="

# Valkey (OCI Redis)
enable_cache       = true
cache_display_name = "spacesai-cache"
cache_node_count   = 1
cache_memory_gbs   = 16
redis_software_version = "VALKEY_7_2"

# Optional Compute
create_compute           = true
compute_shape            = "VM.Standard.E5.Flex"
compute_ocpus            = 1
compute_memory_in_gbs    = 8
compute_assign_public_ip = true
compute_display_name     = "app-host-1"
compute_ssh_public_key   = "ssh-rsa AAAAB3NzaC1yc2EAAAABIwAAAQEAs4f9ua0AU3U08s3s7D75Z7gUkmV0WgAYL7bdolT4r/N98uGXgaa6t4AYN+wKN0gdnjbEWunmoPf0ico8Trqlto8Vdp52DlvOjMZ/26KdJu8b0ytzV/MDO8RZhmL7A/Cwcr9VcPoRoGpfY/PExMGZUXBT7XOQ+ModkkhjCCyLebnMhE7Dv8HjqGnQI9jxob/DhZ0M8Xz9j9OUK82cTUCwtRULYXRx2h9vL5wHp7HZIddNjdnssXADVBVbzerO4S7aRaKfdIEaZu8JL4JYoDrtxv/sWRB3IdSTgYco6augNcTTdkDefn+Qr2dLZFSvcqSY8lP6Tz+/Yp3SLCeWKys+xQ== shadab"
compute_image_ocid       = ""
compute_nsg_ids          = []
compute_boot_volume_size_in_gbs = 50

# IOPS profile mapping
psql_iops = {
  75  = 75000
  150 = 150000
  225 = 225000
  300 = 300000
}
