#!/usr/bin/env python3
"""Fetch the NAS capacity report with bucket-scoped S3 credentials."""
import datetime
import hashlib
import hmac
import json
import os
import pathlib
import urllib.request

output = pathlib.Path('/tmp/rustfs-capacity.json')
try:
    endpoint = 'http://192.168.1.102:9000'
    host = '192.168.1.102:9000'
    path = '/linstor-backups-v2/__protection/capacity.json'
    region = 'us-east-1'
    now = datetime.datetime.now(datetime.timezone.utc)
    date = now.strftime('%Y%m%d')
    amzdate = now.strftime('%Y%m%dT%H%M%SZ')
    payload_hash = hashlib.sha256(b'').hexdigest()
    headers = 'host:' + host + '\nx-amz-content-sha256:' + payload_hash + '\nx-amz-date:' + amzdate + '\n'
    signed_headers = 'host;x-amz-content-sha256;x-amz-date'
    canonical = 'GET\n' + path + '\n\n' + headers + '\n' + signed_headers + '\n' + payload_hash
    scope = date + '/' + region + '/s3/aws4_request'
    string_to_sign = 'AWS4-HMAC-SHA256\n' + amzdate + '\n' + scope + '\n' + hashlib.sha256(canonical.encode()).hexdigest()

    def sign(key, message):
        return hmac.new(key, message.encode(), hashlib.sha256).digest()

    signing_key = sign(sign(sign(sign(('AWS4' + os.environ['RUSTFS_SECRET_KEY']).encode(), date), region), 's3'), 'aws4_request')
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    auth = 'AWS4-HMAC-SHA256 Credential=' + os.environ['RUSTFS_ACCESS_KEY'] + '/' + scope + ', SignedHeaders=' + signed_headers + ', Signature=' + signature
    request = urllib.request.Request(endpoint + path, headers={'Host': host, 'x-amz-date': amzdate, 'x-amz-content-sha256': payload_hash, 'Authorization': auth})
    with urllib.request.urlopen(request, timeout=20) as response:
        report = json.loads(response.read(8192))
    output.write_text(json.dumps(report))
except Exception as error:
    # Let the main gate publish an explicit blocker. Never print credentials or headers.
    output.write_text(json.dumps({'error': type(error).__name__}))
