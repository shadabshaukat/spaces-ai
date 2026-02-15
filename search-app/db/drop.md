# Drop Script (manual use)

## PostgreSQL
Run the following SQL statements manually (psql) to drop all SpacesAI tables:

```sql
DROP TABLE IF EXISTS document_tables CASCADE;
DROP TABLE IF EXISTS image_assets CASCADE;
DROP TABLE IF EXISTS user_activity CASCADE;
DROP TABLE IF EXISTS chunks CASCADE;
DROP TABLE IF EXISTS documents CASCADE;
DROP TABLE IF EXISTS spaces CASCADE;
DROP TABLE IF EXISTS users CASCADE;
```

## OpenSearch
Delete existing indices (text + image):

```bash
curl -X DELETE https://amaaaaaawiclygaashyteiqunkonejhfurxooxj2vv6ubcrflyruk5oa34tq.opensearch.mx-queretaro-1.oci.oraclecloud.com:9200/spacesai_chunks --user "osmaster:RAbbithole1234##"

curl -X DELETE https://amaaaaaawiclygaashyteiqunkonejhfurxooxj2vv6ubcrflyruk5oa34tq.opensearch.mx-queretaro-1.oci.oraclecloud.com:9200/spacesai_images --user "osmaster:RAbbithole1234##"
```

> Note: These commands are destructive; run only when you want to reset the environment.