# OCI PostgreSQL + OpenSearch + Valkey (Redis) Terraform Stack

This Resource Manager–ready stack provisions:
- Networking
  - VCN with private subnet (PostgreSQL, OpenSearch private endpoint, Valkey) and public subnet (optional compute)
  - NAT + optional Service Gateway; Internet Gateway + public RT for public subnet
- OCI PostgreSQL DB System (with optional Configuration)
- Optional Compute instance
- Object Storage bucket for application uploads
- OpenSearch cluster (OCI managed)
- Valkey (OCI Redis) cluster with optional user and ACL

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
- redis_display_name (string, default "spacesai-valkey")
- redis_node_count (number, default 1)
- redis_node_memory_gbs (number, default 2)
- redis_software_version (string, default "VALKEY_7_2")
- Optional Cache User:
  - create_cache_user (bool, default false)
  - cache_user_name (string, default "default")
  - cache_user_description (string, default "Default Cache user")
  - cache_user_acl_string (string, default "+@all")
  - cache_user_status (string, default "ON")
  - cache_user_hashed_passwords (list(string), sensitive, default [])


## What gets created

- Network (when create_vcn_subnet=true):
  - VCN vcn1, private subnet vcn1_psql_priv_subnet, public subnet vcn1_pub_subnet
  - NAT, Service Gateway (optional), Internet Gateway
  - Security Lists + NSGs
    - PSQL NSG rule: tcp/5432 ingress within VCN
    - OpenSearch NSG rule: tcp/9200 ingress within VCN
    - Valkey NSG rule: tcp/6379 ingress within VCN

- OpenSearch (oci_opensearch_opensearch_cluster):
  - Required flat attributes set from vars (counts, memory_gb, ocpu_count, host_type, storage_gb, version)
  - Network linking via vcn_id and subnet_id in your compartment
  - Optional security_master_user_* if provided

- Valkey (oci_redis_redis_cluster):
  - Single or multi-node with memory and version
  - Optional oci_redis_oci_cache_user and attach resource when create_cache_user=true

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


## Notes and compliance
- This stack uses provider oracle/oci >= 5.30.0.
- OpenSearch resource is oci_opensearch_opensearch_cluster and requires the explicit arguments shown above.
- Valkey is provisioned via oci_redis_redis_cluster. Optional user is oci_redis_oci_cache_user + oci_redis_redis_cluster_attach_oci_cache_user.
- NSG rule blocks use proper multi-line destination_port_range syntax.

If the provider version you run requires different argument names, run terraform plan and share the exact error, and we will iterate quickly to align names.
