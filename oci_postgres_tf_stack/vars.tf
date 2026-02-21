variable "region" {
  type        = string
  description = "OCI region identifier (e.g., mx-queretaro-1)."
  default     = "mx-queretaro-1"
}

variable "compartment_ocid" {
  type        = string
  description = "OCID of the target compartment where all resources will be created."
}

variable "tenancy_ocid" {
  type        = string
  description = "Tenancy OCID used only for Availability Domain discovery (optional). Leave unset to fall back to compartment_ocid."
}

## Network

variable "create_service_gateway" {
  type        = bool
  description = "Whether to create a Service Gateway for private access to Oracle Services Network."
  default     = true
}

variable "create_vcn_subnet" {
  type        = bool
  description = "Create a new VCN, route tables, security lists, and subnets. Set to false to use existing subnet OCIDs."
  default     = true
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
  type        = list(string)
  description = "VCN CIDR blocks (used only when create_vcn_subnet=true)."
  default     = ["10.10.0.0/16"]
}

## Credentials

variable "psql_admin_password" {
  type        = string
  description = "Admin password for PostgreSQL. If set to an empty string, a strong random password is generated at apply. Default is a sample value; override in tfvars for production."
  default     = "RAbbithole1234##"
  sensitive   = true
}

## PostgreSQL

variable "psql_admin" {
  type        = string
  description = "Name of PostgreSQL admin username"
  default     = "postgres"
}

variable "psql_version" {
  type        = number
  description = "PostgreSQL major version."
  default     = 16
}

variable "inst_count" {
  type        = number
  description = "Number of PostgreSQL nodes"
  default     = 1
}

variable "num_ocpu" {
  type        = number
  description = "Number of OCPUs per PostgreSQL node"
  default     = 2
}

variable "psql_shape_name" {
  type        = string
  description = "PostgreSQL shape family name"
  default     = "PostgreSQL.VM.Standard.E5.Flex"
}

variable "psql_iops" {
  type        = map(number)
  description = "Internal IOPS profile map used by the module (do not modify unless you know what you are doing)."
  default = {
    75  = 75000
    150 = 150000
    225 = 225000
    300 = 300000
  }
}

# variable "psql_passwd_type" { default = "PLAIN_TEXT" }

## Compute 

variable "create_compute" {
  type        = bool
  description = "Whether to create a small compute instance alongside the database."
  default     = true
}


variable "compute_shape" {
  type        = string
  description = "Compute instance shape (Flex shapes supported)."
  default     = "VM.Standard.E5.Flex"
}

variable "compute_ocpus" {
  type        = number
  description = "Number of OCPUs for the compute instance."
  default     = 1
}

variable "compute_memory_in_gbs" {
  type        = number
  description = "Memory (GB) for the compute instance."
  default     = 8
}

variable "compute_assign_public_ip" {
  type        = bool
  description = "Assign a public IP to the compute VNIC; must be compatible with the chosen subnet."
  default     = true
}


variable "compute_display_name" {
  type        = string
  description = "Display name for the compute instance."
  default     = "app-host-1"
}

variable "compute_ssh_public_key" {
  type        = string
  description = "SSH public key for the opc user on the compute instance."
  default     = "ssh-rsa AAAAB3NzaC1yc2EAAAABIwAAAQEAs4f9ua0AU3U08s3s7D75Z7gUkmV0WgAYL7bdolT4r/N98uGXgaa6t4AYN+wKN0gdnjbEWunmoPf0ico8Trqlto8Vdp52DlvOjMZ/26KdJu8b0ytzV/MDO8RZhmL7A/Cwcr9VcPoRoGpfY/PExMGZUXBT7XOQ+ModkkhjCCyLebnMhE7Dv8HjqGnQI9jxob/DhZ0M8Xz9j9OUK82cTUCwtRULYXRx2h9vL5wHp7HZIddNjdnssXADVBVbzerO4S7aRaKfdIEaZu8JL4JYoDrtxv/sWRB3IdSTgYco6augNcTTdkDefn+Qr2dLZFSvcqSY8lP6Tz+/Yp3SLCeWKys+xQ== shadab"
}


variable "compute_image_ocid" {
  type        = string
  description = "Image OCID for compute. If blank, the latest Oracle Linux 10 image compatible with the shape is auto-selected."
  default     = ""
}

variable "compute_nsg_ids" {
  type        = list(string)
  description = "Optional list of NSG OCIDs to attach to the compute VNIC."
  default     = []
}

variable "compute_boot_volume_size_in_gbs" {
  type        = number
  description = "Boot volume size (GB) for the compute instance."
  default     = 250
}

## Object Storage

variable "object_storage_bucket_name" {
  type        = string
  description = "Object Storage bucket name to create for search-app uploads"
  default     = "search-app-uploads"
}

## OCI PostgreSQL Configuration

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
variable "psql_config_overrides" {
  type        = map(string)
  description = "Key/value map applied to the OCI PostgreSQL configuration via db_configuration_overrides.items."
  default     = {
    "oci.admin_enabled_extensions" = "pg_stat_statements,pglogical,vector"
    "pglogical.conflict_log_level" = "debug1"
    "pg_stat_statements.max"       = "5000"
    "wal_level"                    = "logical"
    "track_commit_timestamp"       = "1"
    "max_wal_size"                 = "10240"
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

# Admin credentials for OpenSearch (if supported by your provider/resource)
variable "opensearch_admin_user" {
  type        = string
  description = "Admin (master) username for OpenSearch cluster (optional; provider may use IAM instead). Do not use 'admin' since that is a reserved word"
  default     = "osmaster"
}


variable "opensearch_admin_password_hash" {
  type        = string
  description = "Admin (master) password HASH for OpenSearch cluster (optional). Provide a hashed password if security is configured. How to create hashed password : eg : java -jar oci-crypto-common-1.0.0-SNAPSHOT.jar pbkdf2_stretch_1000 RAbbithole1234## . Refer : https://docs.oracle.com/en-us/iaas/Content/search-opensearch/Tasks/update-opensearch-cluster-name.htm"
  sensitive   = true
  default     = "pbkdf2_stretch_1000$qIGFqgw8YfVKa2yUpX4NYr2mcpWfRph7$3YcIAfLawNaKDf4QHzebHMLUjcB2VEmYEUAkEVnwfZo="
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
  default     = 16
}




variable "redis_software_version" {
  type        = string
  description = "OCI Cache software version identifier (e.g., VALKEY_7_2)"
  default     = "VALKEY_7_2"
}

## Cloud-init bootstrap (Compute)

variable "enable_cloud_init" {
  type        = bool
  description = "Enable cloud-init to bootstrap the compute instance with OS packages, uv, firewall, AWS CLI, and repo clone."
  default     = true
}

variable "compute_app_port" {
  type        = number
  description = "App port to open in firewalld on the compute instance."
  default     = 8000
}

variable "repo_url" {
  type        = string
  description = "Git repo URL to clone on the compute instance."
  default     = "https://github.com/shadabshaukat/spaces-ai.git"
}

variable "cloud_init_user_data" {
  type        = string
  description = "Cloud-init user data script (bash). Override to customize bootstrap."
  default     = <<-EOT
    #cloud-config
    # Run shell commands via runcmd to ensure cloud-init compatibility
    runcmd:
      - [ bash, -lc, 'sudo set -euxo pipefail' ]
      - [ bash, -lc, 'sudo dnf install -y curl git unzip firewalld oraclelinux-developer-release-el10 python3-oci-cli postgresql16 tesseract ffmpeg || true' ]
      - [ bash, -lc, 'sudo tmpdir=$(mktemp -d) && cd "$tmpdir" && curl -s https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o awscliv2.zip && unzip -q awscliv2.zip && sudo ./aws/install --update && cd / && rm -rf "$tmpdir"' ]
      - [ bash, -lc, 'sudo curl -LsSf https://astral.sh/uv/install.sh | su - opc -c "sh"' ]
      # - [ bash, -lc, 'echo \"export PATH=\"$HOME/.local/bin:$PATH\"\" >> /home/opc/.bashrc' ]
      - [ bash, -lc, 'sudo curl -fsSL https://get.docker.com | sh' ]
      - [ bash, -lc, 'sudo dnf install -y docker-compose-plugin || true' ]
      - [ bash, -lc, 'sudo curl -L "https://github.com/docker/compose/releases/download/v2.24.6/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose && chmod +x /usr/local/bin/docker-compose || true' ]
      - [ bash, -lc, 'sudo ln -sf /usr/local/bin/docker-compose /usr/bin/docker-compose || true' ]
      - [ bash, -lc, 'sudo systemctl enable --now docker' ]
      - [ bash, -lc, 'sudo usermod -aG docker opc' ]
      - [ bash, -lc, 'sudo systemctl enable --now firewalld' ]
      - [ bash, -lc, 'sudo firewall-cmd --permanent --add-port=__APP_PORT__/tcp' ]
      - [ bash, -lc, 'sudo firewall-cmd --reload' ]
      - [ bash, -lc, 'sudo "mkdir -p ~/src && cd ~/src && git clone __REPO_URL__ || true"' ]
  EOT
}
