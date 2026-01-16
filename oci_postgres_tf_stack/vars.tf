variable "region" {
  type    = string
  default = "us-ashburn-1"
}

variable "compartment_ocid" {
  type = string
}

variable "tenancy_ocid" {
  type        = string
  description = "Tenancy OCID (used for AD discovery). If empty, compartment_ocid is used."
  default     = ""
}

## Network

variable "create_service_gateway" {
  type    = bool
  default = true
}

variable "create_vcn_subnet" {
  type    = bool
  default = true
}

variable "psql_subnet_ocid" {
  type        = string
  description = "Private Subnet OCID of existing subnet (used when create_vcn_subnet = false)"
  default     = ""
}

variable "public_subnet_ocid" {
  type        = string
  description = "Public Subnet OCID to use for Compute when create_vcn_subnet = false. If empty, psql_subnet_ocid is used."
  default     = ""
}

variable "vcn_cidr" {
  type    = list(string)
  default = ["10.10.0.0/16"]
}

## Credentials

variable "psql_admin_password" {
  type        = string
  description = "Optional admin password. Leave empty to auto-generate a strong random password."
  default     = ""
  sensitive   = true
}

## PostgreSQL

variable "psql_admin" {
  type        = string
  description = "Name of PostgreSQL admin username"
}

variable "psql_version" {
  type    = number
  default = 16
}

variable "inst_count" {
  type    = number
  default = 1
}

variable "num_ocpu" {
  type    = number
  default = 2
}

variable "psql_shape_name" {
  type        = string
  description = "PostgreSQL shape family name"
  default     = "PostgreSQL.VM.Standard.E5.Flex"
}

variable "psql_iops" {
  type = map(number)
  default = {
    75  = 75000
    150 = 150000
    225 = 225000
    300 = 300000
  }
}

# variable "psql_passwd_type" { default = "PLAIN_TEXT" }

## Compute (optional)

variable "create_compute" {
  type    = bool
  default = false
}

variable "compute_shape" {
  type    = string
  default = "VM.Standard.E5.Flex"
}

variable "compute_ocpus" {
  type    = number
  default = 1
}

variable "compute_memory_in_gbs" {
  type    = number
  default = 8
}

variable "compute_assign_public_ip" {
  type    = bool
  default = false
}

variable "compute_display_name" {
  type    = string
  default = "app-host-1"
}

variable "compute_ssh_public_key" {
  type    = string
  default = ""
}

variable "compute_image_ocid" {
  type    = string
  default = ""
}

variable "compute_nsg_ids" {
  type    = list(string)
  default = []
}

variable "compute_boot_volume_size_in_gbs" {
  type    = number
  default = 50
}

## Object Storage

variable "object_storage_bucket_name" {
  type        = string
  description = "Object Storage bucket name to create for search-app uploads"
  default     = "search-app-uploads"
}

## OCI PostgreSQL Configuration (optional)

variable "create_psql_configuration" {
  type        = bool
  description = "Whether to create an OCI PostgreSQL configuration in this stack"
  default     = true
}

variable "psql_configuration_ocid" {
  type        = string
  description = "Existing OCI PostgreSQL configuration OCID to use (if provided, skips creation)"
  default     = ""
}

variable "psql_config_display_name" {
  type        = string
  description = "Display name for the OCI PostgreSQL configuration (when created)"
  default     = "livelab_flexible_configuration"
}

variable "psql_config_is_flexible" {
  type        = bool
  description = "Whether the configuration is flexible"
  default     = true
}

variable "psql_config_compatible_shapes" {
  type        = list(string)
  description = "List of compatible shapes for the configuration"
  default     = [
    "VM.Standard.E5.Flex",
    "VM.Standard.E6.Flex",
    "VM.Standard3.Flex"
  ]
}

variable "psql_config_description" {
  type        = string
  description = "Description for the PostgreSQL configuration"
  default     = "test configuration created by terraform"
}

# Map of config_key => overridden_config_value
# Example:
# {
#   "oci.admin_enabled_extensions" = "pg_stat_statements,pglogical,vector"
#   "pglogical.conflict_log_level" = "debug1"
#   "pg_stat_statements.max"       = "5000"
# }
variable "psql_config_overrides" {
  type        = map(string)
  description = "Configuration overrides as key/value pairs"
  default     = {
    "oci.admin_enabled_extensions" = "pg_stat_statements,pglogical,vector"
    "pglogical.conflict_log_level" = "debug1"
    "pg_stat_statements.max"       = "5000"
  }
}

## OpenSearch (to be provisioned in same VCN)
variable "enable_opensearch" {
  type        = bool
  description = "Whether to provision an OCI OpenSearch cluster in this stack"
  default     = true
}

variable "opensearch_display_name" {
  type        = string
  description = "Display name for the OpenSearch cluster"
  default     = "spacesai-opensearch"
}

variable "opensearch_version" {
  type        = string
  description = "OpenSearch engine version (e.g., 3.2.0) — confirm with OCI service"
  default     = "3.2.0"
}



variable "opensearch_node_count" {
  type        = number
  description = "Number of data nodes in the OpenSearch cluster"
  default     = 3
}

variable "opensearch_ocpus" {
  type        = number
  description = "OCPUs per node"
  default     = 2
}

variable "opensearch_memory_gbs" {
  type        = number
  description = "Memory per node in GB"
  default     = 20
}


variable "opensearch_storage_gbs" {
  type        = number
  description = "Block storage per node in GB"
  default     = 200
}

# Host types (provider specific; typical values include COMPUTE)
variable "opensearch_data_node_host_type" {
  type        = string
  description = "Instance type for data nodes (FLEX|BM)"
  default     = "FLEX"
}


variable "opensearch_master_node_count" {
  type        = number
  description = "Number of master nodes"
  default     = 3
}

variable "opensearch_master_node_host_ocpu_count" {
  type        = number
  description = "OCPUs per master node"
  default     = 2
}

variable "opensearch_master_node_host_memory_gb" {
  type        = number
  description = "Memory (GB) per master node"
  default     = 20
}


variable "opensearch_master_node_host_type" {
  type        = string
  description = "Instance type for master nodes (FLEX|BM)"
  default     = "FLEX"
}

variable "opensearch_opendashboard_node_count" {
  type        = number
  description = "Number of OpenSearch dashboard nodes"
  default     = 1
}

variable "opensearch_opendashboard_node_host_ocpu_count" {
  type        = number
  description = "OCPUs per dashboard node"
  default     = 2
}


variable "opensearch_opendashboard_node_host_memory_gb" {
  type        = number
  description = "Memory (GB) per dashboard node"
  default     = 16
}


# Optional: Admin credentials for OpenSearch (if supported by your provider/resource)
# Some OCI provider versions require setting an admin/master user and password during cluster creation.
# If your provider exposes these fields, wire them in opensearch.tf accordingly.
variable "opensearch_admin_user" {
  type        = string
  description = "Admin (master) username for OpenSearch cluster (optional; provider may use IAM instead)"
  default     = null
}

variable "opensearch_admin_password_hash" {
  type        = string
  description = "Admin (master) password HASH for OpenSearch cluster (optional). Provide a hashed password if security is configured."
  sensitive   = true
  default     = null
}

variable "opensearch_security_mode" {
  type        = string
  description = "OpenSearch security mode (e.g., ENFORCING)"
  default     = "ENFORCING"
}



## OCI Cache (Valkey) in same VCN

variable "enable_cache" {
  type        = bool
  description = "Whether to provision OCI Cache (Valkey) in this stack"
  default     = true
}

variable "cache_display_name" {
  type        = string
  description = "Display name for the cache cluster"
  default     = "spacesai-cache"
}

variable "cache_node_count" {
  type        = number
  description = "Number of cache nodes"
  default     = 1
}

variable "cache_memory_gbs" {
  type        = number
  description = "Memory per cache node in GB"
  default     = 8
}

variable "redis_display_name" {
  type        = string
  description = "Display name for Redis/Valkey cluster"
  default     = "spacesai-valkey"
}

variable "redis_node_count" {
  type        = number
  description = "Number of Redis/Valkey nodes"
  default     = 1
}

variable "redis_node_memory_gbs" {
  type        = number
  description = "Memory per Redis/Valkey node in GB"
  default     = 2
}

variable "redis_software_version" {
  type        = string
  description = "Redis/Valkey software version identifier (e.g., VALKEY_7_2)"
  default     = "VALKEY_7_2"
}

# Optional Cache User configuration (attach to cluster)
variable "create_cache_user" {
  type        = bool
  description = "Whether to create a Valkey/Redis cache user and attach it to the cluster"
  default     = false
}

variable "cache_user_name" {
  type        = string
  description = "Cache user name"
  default     = "default"
}

variable "cache_user_description" {
  type        = string
  description = "Cache user description"
  default     = "Default Cache user"
}

variable "cache_user_acl_string" {
  type        = string
  description = "ACL string for the cache user (see Valkey/Redis ACL docs)."
  default     = "+@all"
}

variable "cache_user_status" {
  type        = string
  description = "Cache user status (e.g., ON|OFF)"
  default     = "ON"
}

variable "cache_user_hashed_passwords" {
  type        = list(string)
  description = "List of hashed passwords for the cache user (PASSWORD auth). Must be 64-character hex SHA-256 hashes."
  sensitive   = true
  default     = []
  validation {
    condition     = length(var.cache_user_hashed_passwords) == 0 || alltrue([for h in var.cache_user_hashed_passwords : can(regex("^[A-Fa-f0-9]{64}$", h))])
    error_message = "Each cache user hashed password must be a 64-character hex SHA-256 hash (not PBKDF2)."
  }
}


# Convenience: allow a single hashed password string (useful for ORM UIs that don't support list inputs)
variable "cache_user_hashed_password" {
  type        = string
  description = "Single hashed password for the cache user (PASSWORD auth). If set, it will be combined with cache_user_hashed_passwords. Must be 64-character hex SHA-256."
  sensitive   = true
  default     = ""
  validation {
    condition     = var.cache_user_hashed_password == "" || can(regex("^[A-Fa-f0-9]{64}$", var.cache_user_hashed_password))
    error_message = "cache_user_hashed_password must be a 64-character hex SHA-256 hash (not PBKDF2)."
  }
}
