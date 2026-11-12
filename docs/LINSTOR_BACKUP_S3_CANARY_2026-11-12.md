# LINSTOR disposable S3 canary — 2026-11-12

Tested the existing path-style endpoint `http://storage.local.hejsan.xyz:9000` and bucket `linstor-backups-v2` with the existing bucket-scoped credential. The credential was read from the Kubernetes Secret into process memory and was not printed or written to disk.

The test used a unique disposable object prefix and completed these checks:

| Operation | Result |
| --- | --- |
| Confirm new prefix was empty | HTTP 200 |
| Create object | HTTP 200 |
| List by unique prefix | HTTP 200; exactly one object |
| Read object | HTTP 200 |
| SHA-256 | `7b84b06588d2cd14bd37ae052b82040c5bdb72f361252f4972cbb3fc7a93a3bd`; matched the source payload |
| Delete object | HTTP 204 |
| List prefix after delete | HTTP 200; zero objects |

The test did not modify any pre-existing bucket object. RustFS remains the only backup destination by explicit user decision; this canary validates endpoint compatibility and scoped object operations, not protection from RustFS host or site loss.
