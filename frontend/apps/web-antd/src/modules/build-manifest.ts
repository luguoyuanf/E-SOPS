export const buildManifest = {
  "schema_version": 2,
  "edition": "esop",
  "source_revision": "ad6cbee39f385456e276fab602b9a10faaddf6c3",
  "platform_contract_version": 1,
  "platform_version": "1.0.0",
  "modules": [
    {
      "code": "platform",
      "version": "1.0.0",
      "migration_namespace": "platform",
      "migration_heads": [
        "mysql_platform_0009"
      ],
      "openapi_sha256": "sha256:d546a7f02a2931cd1596c25ff0bd710741639fe8d917eae9427d319c722621a0"
    },
    {
      "code": "erp",
      "version": "0.1.0",
      "migration_namespace": "erp",
      "migration_heads": [
        "mysql_erp_0003_product_model"
      ],
      "openapi_sha256": "sha256:42eb75b9221ebe678798658042d36436e26def2fb4ddab36814d73ad6b9d6075"
    },
    {
      "code": "esop",
      "version": "0.1.0",
      "migration_namespace": "esop",
      "migration_heads": [
        "mysql_esop_0038"
      ],
      "openapi_sha256": "sha256:a644a206fb49093bcebe204b29a035a608c8ef02ed37b0c28d93273cfa8d8328"
    }
  ],
  "manifest_digest": "sha256:dda71b60bc52d0639e6037c933569a6a396fc2ed2f08e07383653f85522c8f33"
} as const;
