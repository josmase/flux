#!/usr/bin/env python3
"""Fail closed when the RustFS capacity report is missing, stale, or below floor."""
import datetime
import hashlib
import hmac
import json
import os
import sys
import urllib.parse
import urllib.request


def fail(message):
    print("RustFS capacity check failed: " + message, file=sys.stderr)
    raise SystemExit(1)


endpoint = os.environ["RUSTFS_ENDPOINT"].rstrip("/")
bucket = os.environ["RUSTFS_BUCKET"]
key = os.environ["RUSTFS_REPORT_KEY"]
region = os.environ.get("AWS_REGION", "us-east-1")
access = os.environ["AWS_ACCESS_KEY_ID"]
secret = os.environ["AWS_SECRET_ACCESS_KEY"]
parsed = urllib.parse.urlsplit(endpoint)
if parsed.scheme != "http" or not parsed.netloc or parsed.path:
    fail("invalid endpoint configuration")

method = "GET"
path = "/" + bucket + "/" + urllib.parse.quote(key, safe="/-_.~")
now = datetime.datetime.now(datetime.timezone.utc)
date = now.strftime("%Y%m%d")
amzdate = now.strftime("%Y%m%dT%H%M%SZ")
payload_hash = hashlib.sha256(b"").hexdigest()
signed_headers = "host;x-amz-content-sha256;x-amz-date"
canonical_headers = (
    "host:" + parsed.netloc + "\n"
    + "x-amz-content-sha256:" + payload_hash + "\n"
    + "x-amz-date:" + amzdate + "\n"
)
canonical_request = "\n".join(
    [method, path, "", canonical_headers, signed_headers, payload_hash]
)
scope = date + "/" + region + "/s3/aws4_request"
string_to_sign = (
    "AWS4-HMAC-SHA256\n" + amzdate + "\n" + scope + "\n"
    + hashlib.sha256(canonical_request.encode()).hexdigest()
)


def sign(secret_bytes, message):
    return hmac.new(secret_bytes, message.encode(), hashlib.sha256).digest()


signing_key = sign(
    sign(sign(sign(("AWS4" + secret).encode(), date), region), "s3"),
    "aws4_request",
)
signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
authorization = (
    "AWS4-HMAC-SHA256 Credential=" + access + "/" + scope
    + ", SignedHeaders=" + signed_headers + ", Signature=" + signature
)
request = urllib.request.Request(
    endpoint + path,
    headers={
        "Host": parsed.netloc,
        "x-amz-date": amzdate,
        "x-amz-content-sha256": payload_hash,
        "Authorization": authorization,
    },
)
try:
    with urllib.request.urlopen(request, timeout=15) as response:
        report = json.load(response)
except Exception as error:
    fail("capacity report could not be read (" + type(error).__name__ + ")")

expected = {
    "bucket": bucket,
    "generation": os.environ["RUSTFS_GENERATION"],
    "mountpoint": os.environ["RUSTFS_MOUNTPOINT"],
    "fstype": os.environ["RUSTFS_EXPECTED_FSTYPE"],
}
for name, value in expected.items():
    if report.get(name) != value:
        fail("report has an unexpected " + name)

try:
    checked_at = int(report["checkedAt"])
    free_bytes = int(report["freeBytes"])
    bucket_bytes = int(report["bucketBytes"])
except (KeyError, TypeError, ValueError):
    fail("report has missing or invalid measurements")

age = int(now.timestamp()) - checked_at
max_age = int(os.environ.get("RUSTFS_REPORT_MAX_AGE_SECONDS", "600"))
if age < -120 or age > max_age:
    fail("capacity report is stale or has a future timestamp")
minimum_free = int(os.environ["RUSTFS_MIN_FREE_BYTES"])
if free_bytes < minimum_free:
    fail("filesystem free space is below the configured minimum")

print(
    "RustFS capacity check passed: freeBytes=" + str(free_bytes)
    + " bucketBytes=" + str(bucket_bytes)
)
