output  "psql_admin_pwd" { 
  value      = local.psql_admin_password
  sensitive  = true
}

output "compute_instance_id" {
  value = length(oci_core_instance.app_host) > 0 ? oci_core_instance.app_host[0].id : null
}

output "compute_state" {
  value = length(oci_core_instance.app_host) > 0 ? oci_core_instance.app_host[0].state : null
}

output "compute_public_ip" {
  value = length(data.oci_core_vnic.app_host_primary_vnic) > 0 ? data.oci_core_vnic.app_host_primary_vnic[0].public_ip_address : null
}

output "compute_private_ip" {
  value = length(data.oci_core_vnic.app_host_primary_vnic) > 0 ? data.oci_core_vnic.app_host_primary_vnic[0].private_ip_address : null
}

output "uploads_bucket_name" {
  value       = oci_objectstorage_bucket.uploads_bucket.name
  description = "Object Storage bucket name for search-app uploads"
}

# OpenSearch FQDNs and private IP (per OCI provider attributes)
output "opensearch_fqdn" {
  value       = try(oci_opensearch_opensearch_cluster.spacesai_os[0].opensearch_fqdn, null)
  description = "OpenSearch API FQDN"
}

output "opendashboard_fqdn" {
  value       = try(oci_opensearch_opensearch_cluster.spacesai_os[0].opendashboard_fqdn, null)
  description = "OpenSearch Dashboard FQDN"
}

output "opensearch_private_ip" {
  value       = try(oci_opensearch_opensearch_cluster.spacesai_os[0].opensearch_private_ip, null)
  description = "OpenSearch private IP (inside VCN)"
}


# Valkey/Redis outputs
output "valkey_cluster_id" {
  value       = try(oci_redis_redis_cluster.spacesai_cache[0].id, null)
  description = "Valkey/Redis cluster OCID"
}


output "valkey_port" {
  value       = 6379
  description = "Valkey/Redis port"
}
