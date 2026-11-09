#!/bin/sh
# Run as root on the RustFS host. Existing buckets and objects are never removed.
set -eu

docker run --rm --user 0:0 --network host \
  --entrypoint /bin/sh --volume /etc/rustfs:/bootstrap:ro \
  rustfs/rc@sha256:9f4e5cd6e43576f2daaa5f6338827ef8296f5eb781175950b0bf62c92e983686 -ec '
    access=$(tr -d "\r\n" < /bootstrap/root-access-key)
    secret=$(tr -d "\r\n" < /bootstrap/root-secret-key)
    rc alias set recovery-admin http://192.168.1.198:9000 "$access" "$secret" \
      --region us-east-1 --bucket-lookup path >/dev/null
    for bucket in recovery-postgres-v1 recovery-volumes-v1 recovery-gitlab-v1 recovery-cluster-v1; do
      rc bucket create "recovery-admin/$bucket" --ignore-existing >/dev/null
      rc bucket list "recovery-admin/$bucket" >/dev/null
      printf "verified bucket: %s\n" "$bucket"
    done
  '
