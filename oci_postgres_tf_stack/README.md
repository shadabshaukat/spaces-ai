# OCI PostgreSQL + OpenSearch + Valkey (Redis) Terraform Stack

This Resource Manager–ready stack provisions:
- Networking
  - VCN with private subnet (PostgreSQL, OpenSearch private endpoint, Valkey) and public subnet (optional compute)
  - NAT + optional Service Gateway; Internet Gateway + public RT for public subnet
- OCI PostgreSQL DB System (with optional Configuration)
- Optional Compute instance
- Object Storage bucket for application uploads
- OpenSearch cluster (OCI managed)

The application (search-app) uses:
- PostgreSQL as system-of-record
- OpenSearch for serving search (KNN/BM25)
- Valkey (Redis-compatible) for caching


## Prerequisites
- Terraform >= 1.5.0
- OCI Terraform Provider >= 5.30.0 (declared in provider.tf)
- Compartment OCID and region


## Variables (high level)

Core
- compartment_ocid (string) — required
- region (string, default us-ashburn-1)
- tenancy_ocid (string, optional)

Networking
- create_vcn_subnet (bool, default true)
- create_service_gateway (bool, default true)
- vcn_cidr (list(string), default ["10.10.0.0/16"]) 
- psql_subnet_ocid (string, default "") — use existing private subnet when create_vcn_subnet=false
- public_subnet_ocid (string, default "") — use existing public subnet for compute

PostgreSQL
- psql_admin (string) — required
- psql_admin_password (string, sensitive, default "") — leave empty to auto-generate
- psql_version (number, default 16)
- num_ocpu (number, default 2)
- inst_count (number, default 1)
- psql_shape_name (string, default "PostgreSQL.VM.Standard.E5.Flex")
- psql_iops (map(number))
- PostgreSQL Configuration (optional; default-enabled): see vars.tf for create_psql_configuration, psql_configuration_ocid, and others

Compute (optional)
- create_compute (bool, default false)
- compute_shape, compute_ocpus, compute_memory_in_gbs, compute_assign_public_ip, compute_ssh_public_key, etc.

Object Storage
- object_storage_bucket_name (string, default "search-app-uploads")

OpenSearch (OCI)
- enable_opensearch (bool, default true)
- opensearch_display_name (string, default "spacesai-opensearch")
- opensearch_version (string, default "3.2.0")

- Data nodes:
  - opensearch_node_count (number, default 3)
  - opensearch_ocpus (number, default 2)
  - opensearch_memory_gbs (number, default 16)
  - opensearch_storage_gbs (number, default 200)
- Master nodes:
  - opensearch_master_node_count (number, default 3)
  - opensearch_master_node_host_ocpu_count (number, default 2)
  - opensearch_master_node_host_memory_gb (number, default 16)
- Dashboard nodes:
  - opensearch_opendashboard_node_count (number, default 1)
  - opensearch_opendashboard_node_host_ocpu_count (number, default 1)
  - opensearch_opendashboard_node_host_memory_gb (number, default 8)
- Security (optional):
  - opensearch_admin_user (string, default null)
  - opensearch_admin_password_hash (string, sensitive, default null)

Valkey (OCI Redis)
- enable_cache (bool, default true)
- cache_display_name (string, default "spacesai-cache")
- cache_node_count (number, default 1)
- cache_memory_gbs (number, default 8)
- redis_software_version (string, default "VALKEY_7_2")








## What gets created

- Network (when create_vcn_subnet=true):
  - VCN vcn1, private subnet vcn1_psql_priv_subnet, public subnet vcn1_pub_subnet
  - NAT, Service Gateway (optional), Internet Gateway
  - Security Lists + NSGs
    - Private subnet rules within VCN: tcp/22 (SSH), tcp/5432 (PostgreSQL), tcp/6379 (Valkey), tcp/9200 (OpenSearch API), tcp/5601 (OpenSearch Dashboard)


- OpenSearch (oci_opensearch_opensearch_cluster):
  - Required flat attributes set from vars (counts, memory_gb, ocpu_count, host_type, storage_gb, version)
  - Network linking via vcn_id and subnet_id in your compartment
  - Optional security_master_user_* if provided

- Valkey (oci_redis_redis_cluster):
  - Single or multi-node with memory and version

- PostgreSQL DB System and optional configuration
- Uploads bucket in Object Storage
- Optional compute instance


## Outputs

- psql_admin_pwd (sensitive)
- uploads_bucket_name
- OpenSearch:
  - opensearch_fqdn — API endpoint FQDN
  - opendashboard_fqdn — Dashboard FQDN
  - opensearch_private_ip — Private IP inside VCN
- Valkey (Redis):
  - valkey_cluster_id
  - valkey_port (constant 6379)


## Map outputs to app .env

- SEARCH_BACKEND=opensearch
- OPENSEARCH_HOST=https://<opensearch_fqdn>:9200
- OPENSEARCH_INDEX=spacesai_chunks
- OPENSEARCH_USER / OPENSEARCH_PASSWORD — if you configured security in OpenSearch (optional)
- VALKEY_HOST=<private IP or DNS of the cluster endpoint>
- VALKEY_PORT=6379
- DB connection for the app must reach the OCI PostgreSQL endpoint.
- DB_STORE_EMBEDDINGS=false (already defaulted in search-app/.env.example) when OpenSearch serves queries.


## Usage

1) Update example.tfvars (or set variables in UI) for OpenSearch and Valkey sizing.
2) terraform init
3) terraform plan -var-file=example.tfvars
4) terraform apply -var-file=example.tfvars
5) Use outputs to configure search-app/.env

## Cloud-init bootstrap (Compute)

When create_compute=true, you can optionally enable cloud-init to bootstrap the instance with OS packages and tools to run SpacesAI:
- Installs curl, git, unzip, firewalld, oraclelinux-developer-release-el10, python3-oci-cli, postgresql16
- Installs uv (user-local) and adds it to PATH
- Installs Docker and Docker Compose
- Enables firewalld and opens TCP port 8000 by default

- Installs AWS CLI v2 (no credentials)
- Clones the repo https://github.com/shadabshaukat/spaces-ai.git under /home/opc/src

Variables:
- enable_cloud_init (bool, default true)
- compute_app_port (number, default 8000)
- repo_url (string, default https://github.com/shadabshaukat/spaces-ai.git)
- cloud_init_user_data (string; a #cloud-config document). The default user_data includes the steps above; override to customize.

Note: The default user_data opens 8000/tcp; customize cloud_init_user_data if you change the app port.

Important: Cloud-init runs on first boot only. If you enabled or modified cloud-init after the instance was created, destroy and recreate the compute instance (toggle create_compute false→true or run a destroy/apply in ORM). After boot, you can verify execution on the VM via:
- sudo cloud-init status
- sudo tail -n 200 /var/log/cloud-init-output.log




## Notes and compliance
- This stack uses provider oracle/oci >= 5.30.0.
- OpenSearch resource is oci_opensearch_opensearch_cluster and requires the explicit arguments shown above.
- Valkey is provisioned via oci_redis_redis_cluster.

- NSG rule blocks use proper multi-line destination_port_range syntax.

If the provider version you run requires different argument names, run terraform plan and share the exact error, and we will iterate quickly to align names.

## List of Variables in the Stack

Core
- region (string, default mx-queretaro-1) — OCI region identifier
- compartment_ocid (string) — OCID of target compartment for all resources
- tenancy_ocid (string) — Tenancy OCID used only for AD discovery (optional)

Networking
- create_vcn_subnet (bool, default true) — Create VCN, route tables, security lists, and subnets
- create_service_gateway (bool, default true) — Create Service Gateway for private access to OSN
- vcn_cidr (list(string), default ["10.10.0.0/16"]) — VCN CIDRs (when create_vcn_subnet=true)
- psql_subnet_ocid (string, default "") — Existing private subnet OCID (when not creating VCN)
- public_subnet_ocid (string, default "") — Existing public subnet OCID for compute (fallback to psql_subnet_ocid if empty)

PostgreSQL
- psql_admin (string, default postgres) — Admin username
- psql_admin_password (string, sensitive, default "RAbbithole1234##") — Leave empty to auto-generate
- psql_version (number, default 16) — PostgreSQL major version
- inst_count (number, default 1) — Number of DB nodes
- num_ocpu (number, default 2) — OCPUs per DB node
- psql_shape_name (string, default "PostgreSQL.VM.Standard.E5.Flex") — Shape family
- psql_iops (map(number)) — Internal IOPS profile map

PostgreSQL Configuration (optional)
- create_psql_configuration (bool, default true)
- psql_configuration_ocid (string, default "") — Use existing configuration OCID
- psql_config_display_name (string, default "livelab_flexible_configuration")
- psql_config_is_flexible (bool, default true)
- psql_config_compatible_shapes (list(string)) — Compatible shapes
- psql_config_description (string)
- psql_config_overrides (map(string)) — Applied via db_configuration_overrides.items; includes keys like oci.admin_enabled_extensions, pglogical.conflict_log_level, pg_stat_statements.max, wal_level, track_commit_timestamp, max_wal_size

Compute (optional)
- create_compute (bool, default true) — Create a small compute instance
- compute_shape (string, default "VM.Standard.E5.Flex") — Instance shape
- compute_ocpus (number, default 1) — OCPUs
- compute_memory_in_gbs (number, default 8) — Memory (GB)
- compute_assign_public_ip (bool, default true) — Assign public IP to VNIC
- compute_display_name (string, default "app-host-1")
- compute_ssh_public_key (string) — SSH key for opc user
- compute_image_ocid (string, default "") — If blank, auto-select latest Oracle Linux 10 image
- compute_nsg_ids (list(string), default []) — NSG OCIDs for the VNIC
- compute_boot_volume_size_in_gbs (number, default 50) — Boot volume size (GB)

Object Storage
- object_storage_bucket_name (string, default "search-app-uploads") — Uploads bucket name

OpenSearch
- enable_opensearch (bool, default true)
- opensearch_display_name (string, default "spacesai-opensearch")
- opensearch_version (string, default "3.2.0")
- opensearch_node_count (number, default 3)
- opensearch_ocpus (number, default 2)
- opensearch_memory_gbs (number, default 20)
- opensearch_storage_gbs (number, default 200)
- opensearch_data_node_host_type (string, default FLEX)
- opensearch_master_node_count (number, default 3)
- opensearch_master_node_host_ocpu_count (number, default 2)
- opensearch_master_node_host_memory_gb (number, default 20)
- opensearch_master_node_host_type (string, default FLEX)
- opensearch_opendashboard_node_count (number, default 1)
- opensearch_opendashboard_node_host_ocpu_count (number, default 2)
- opensearch_opendashboard_node_host_memory_gb (number, default 16)
- opensearch_admin_user (string, default "osmaster")
- opensearch_admin_password_hash (string, sensitive, default provided) — PBKDF2 string, override as needed
- opensearch_security_mode (string, default "ENFORCING")

Valkey (OCI Cache)
- enable_cache (bool, default true)
- cache_display_name (string, default "spacesai-cache")
- cache_node_count (number, default 1)
- cache_memory_gbs (number, default 16)
