# Example tfvars for OCI PostgreSQL configuration

# Set to true to create a new configuration
create_psql_configuration = true

# Leave empty to create; set to an existing OCID to use an existing configuration instead
psql_configuration_ocid = ""

# DB version for the configuration (should match your DB system)
psql_version = 15

# Display name and compatible shapes
psql_config_display_name      = "livelab_flexible_configuration"
psql_config_is_flexible       = true
psql_config_compatible_shapes = ["VM.Standard.E5.Flex", "VM.Standard.E6.Flex", "VM.Standard3.Flex"]
psql_config_description       = "test configuration created by terraform"

# Key/value overrides rendered as items under db_configuration_overrides
psql_config_overrides = {
  "oci.admin_enabled_extensions" = "pg_stat_statements,pglogical"
  "pglogical.conflict_log_level" = "debug1"
  "pg_stat_statements.max"       = "5000"
}
