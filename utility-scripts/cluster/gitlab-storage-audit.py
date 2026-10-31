#!/usr/bin/env python3
"""Read-only GitLab S3 access audit. Never prints credentials or object names."""
import base64
import configparser
import datetime
import hashlib
import hmac
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import yaml

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


NAMESPACE = "gitlab"
WORKLOAD_BUCKETS = ("gitlab-artifacts", "gitlab-lfs", "gitlab-uploads", "gitlab-packages", "gitlab-terraform-state")
BACKUP_BUCKETS = ("gitlab-backups", "gitlab-backups-tmp")


def secret(name, key):
    result = subprocess.run(["kubectl", "get", "secret", name, "-n", NAMESPACE, "-o", "json"], capture_output=True, check=True)
    return base64.b64decode(json.loads(result.stdout)["data"][key]).decode()


def sign(key, value):
    return hmac.new(key, value.encode(), hashlib.sha256).digest()


def list_bucket(config, bucket, prefix=""):
    """Return S3 HTTP status and error code; never return object listings."""
    endpoint = urllib.parse.urlsplit(config["endpoint"])
    if endpoint.scheme not in ("http", "https") or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        raise ValueError("invalid S3 endpoint")
    path = endpoint.path.rstrip("/") + "/" + urllib.parse.quote(bucket, safe="")
    params = {"list-type": "2", "max-keys": "1"}
    if prefix:
        params["prefix"] = prefix
    query = urllib.parse.urlencode(sorted(params.items()), quote_via=urllib.parse.quote)
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    payload = hashlib.sha256(b"").hexdigest()
    headers = {"host": endpoint.netloc, "x-amz-content-sha256": payload, "x-amz-date": stamp}
    canonical_headers = "".join(f"{key}:{value}\n" for key, value in sorted(headers.items()))
    signed_headers = ";".join(sorted(headers))
    request = "\n".join(("GET", path, query, canonical_headers, signed_headers, payload))
    scope = f"{day}/{config['region']}/s3/aws4_request"
    string_to_sign = "\n".join(("AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(request.encode()).hexdigest()))
    key = sign(sign(sign(sign(("AWS4" + config["secret"]).encode(), day), config["region"]), "s3"), "aws4_request")
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers["Authorization"] = f"AWS4-HMAC-SHA256 Credential={config['access']}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"
    url = urllib.parse.urlunsplit((endpoint.scheme, endpoint.netloc, path, query, ""))
    try:
        with urllib.request.build_opener(NoRedirect()).open(urllib.request.Request(url, headers=headers), timeout=15) as response:
            return response.status, ""
    except urllib.error.HTTPError as exc:
        try:
            code = ET.fromstring(exc.read(8192)).findtext("Code") or ""
        except ET.ParseError:
            code = ""
        return exc.code, code


def main():
    workload = yaml.safe_load(secret("gitlab-object-storage", "connection"))
    backup = configparser.ConfigParser(interpolation=None)
    backup.read_string(secret("gitlab-backup-object-storage", "config"))
    registry = yaml.safe_load(secret("gitlab-registry-storage", "config"))["s3"]
    b = backup["default"]
    configs = {
        "workload": {"endpoint": workload["endpoint"], "region": workload.get("region", "us-east-1"), "access": workload["aws_access_key_id"], "secret": workload["aws_secret_access_key"]},
        "backup": {"endpoint": ("https://" if b.getboolean("use_https", fallback=True) else "http://") + b["host_base"], "region": "us-east-1", "access": b["access_key"], "secret": b["secret_key"]},
        "registry": {"endpoint": registry["regionendpoint"], "region": registry.get("region", "us-east-1"), "access": registry["accesskey"], "secret": registry["secretkey"]},
    }
    print("Credential identities shared: workload/backup={}, workload/registry={}, backup/registry={}".format(
        configs["workload"]["access"] == configs["backup"]["access"],
        configs["workload"]["access"] == configs["registry"]["access"],
        configs["backup"]["access"] == configs["registry"]["access"]))
    checks = [("workload", bucket, "", True) for bucket in WORKLOAD_BUCKETS]
    checks += [("backup", bucket, "", True) for bucket in BACKUP_BUCKETS]
    checks += [("workload", bucket, "", False) for bucket in BACKUP_BUCKETS]
    checks += [("backup", bucket, "", False) for bucket in WORKLOAD_BUCKETS]
    checks += [("registry", registry["bucket"], str(registry.get("rootdirectory", "")).lstrip("/").rstrip("/") + "/", True)]
    checks += [("registry", bucket, "", False) for bucket in WORKLOAD_BUCKETS + BACKUP_BUCKETS]
    checks += [("registry", registry["bucket"], "unrelated/", False)]
    failures = 0
    for identity, bucket, prefix, expected in checks:
        try:
            status, code = list_bucket(configs[identity], bucket, prefix)
            passed = status == 200 if expected else status == 403 and code == "AccessDenied"
            print(f"{'PASS' if passed else 'FAIL'} {identity} {'allowed' if expected else 'denied'} {bucket}{' (configured prefix)' if prefix and expected else ' (unrelated prefix)' if prefix else ''}: HTTP {status} {code}")
        except (OSError, ValueError, urllib.error.URLError):
            passed = False
            print(f"FAIL {identity} {bucket}: connection or endpoint error")
        failures += not passed
    for first, second in (("workload", "backup"), ("workload", "registry"), ("backup", "registry")):
        if configs[first]["access"] == configs[second]["access"]:
            print(f"FAIL {first} and {second} use the same access key")
            failures += 1
    print(f"Result: {failures} failed checks. Listing alone does not verify read/write/delete permissions or OpenTofu CI credentials.")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (subprocess.CalledProcessError, KeyError, ValueError, configparser.Error, yaml.YAMLError):
        print("ERROR: unable to read or parse GitLab storage configuration", file=sys.stderr)
        sys.exit(2)
