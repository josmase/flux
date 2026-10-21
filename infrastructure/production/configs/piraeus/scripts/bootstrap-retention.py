#!/usr/bin/env python3
"""Bound retention of the explicitly reviewed manual v2 bootstrap chains.

Scheduled LINSTOR retention covers schedule-tagged chains. This supplement
handles only the exact bootstrap IDs in the reviewed index, preserving every
legacy remote and all CNPG Backup-object recovery sets.
"""
import json
import os
import re
import ssl
import subprocess
import time
import urllib.error
import urllib.request

NAMESPACE = 'piraeus-datastore'
REMOTE = 'rustfs-linstor-backups-v2'
STATUS = 'linstor-bootstrap-retention-status'
PREFIX = 'BackupShipping/Source/' + REMOTE + '/'
LINSTOR = ['linstor', '--controllers', 'linstor-controller.piraeus-datastore.svc:3370', '-m']
TLS = ssl.create_default_context(cafile='/var/run/secrets/kubernetes.io/serviceaccount/ca.crt')
TOKEN = open('/var/run/secrets/kubernetes.io/serviceaccount/token').read().strip()
API = 'https://' + os.environ['KUBERNETES_SERVICE_HOST'] + ':' + os.environ.get('KUBERNETES_SERVICE_PORT_HTTPS', os.environ['KUBERNETES_SERVICE_PORT'])
CM = '/api/v1/namespaces/' + NAMESPACE + '/configmaps/'
changes = []


def kube(method, path, payload=None, missing_ok=False):
    request = urllib.request.Request(API + path, data=json.dumps(payload).encode() if payload is not None else None,
        method=method, headers={'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/merge-patch+json' if method == 'PATCH' else 'application/json'})
    try:
        with urllib.request.urlopen(request, context=TLS, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404 and missing_ok:
            return None
        raise


def report(healthy, state):
    data = {'healthy': str(healthy).lower(), 'state': state[:500], 'checkedAt': str(int(time.time())), 'backupGeneration': REMOTE, 'changes': json.dumps(changes)}
    if kube('GET', CM + STATUS, missing_ok=True) is None:
        kube('POST', CM.rstrip('/'), {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': STATUS, 'namespace': NAMESPACE}, 'data': data})
    else:
        kube('PATCH', CM + STATUS, {'data': data})
    print(json.dumps(data), flush=True)


def linstor(*args):
    result = subprocess.run(LINSTOR + list(args), text=True, capture_output=True, timeout=90)
    assert result.returncode == 0, 'LINSTOR command failed: ' + ' '.join(args)
    value = json.loads(result.stdout)
    assert not (isinstance(value, list) and any(isinstance(v, dict) and v.get('ret_code', 0) < 0 for v in value)), 'LINSTOR API error: ' + json.dumps(value)
    return value


def health():
    assert all(n['connection_status'] == 'ONLINE' for n in linstor('node', 'list')[0]), 'Satellite offline'
    resources = linstor('resource', 'list')[0]
    assert resources and all(v['state']['disk_state'] in ('UpToDate', 'Diskless') for r in resources for v in r.get('volumes', [])), 'Replica degradation'
    pools = [p for p in linstor('storage-pool', 'list')[0] if p['storage_pool_name'] == 'linstor-thin']
    assert len(pools) == 3 and all(p['free_capacity'] * 100 >= p['total_capacity'] * 20 for p in pools), 'Pool capacity violation'


def wait_for(check, description):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if check():
            return
        health()
        time.sleep(3)
    raise RuntimeError(description + " did not finish within 90 seconds")


def objects(entry):
    return {entry['s3']['meta_name']} | {v['s3']['key'] for v in entry['vlms']}


def main():
    manifest = kube('GET', CM + 'linstor-backup-generation-manifest')['data']
    index = kube('GET', CM + 'linstor-bootstrap-chain-index')['data']
    assert manifest['reviewed'] == index['reviewed'] == 'true', 'Reviewed bootstrap chain index required'
    assert manifest['backupGeneration'] == index['backupGeneration'] == REMOTE
    rows = {r.split('\t')[2]: r.split('\t') for r in manifest['resources.tsv'].splitlines() if r}
    chains = json.loads(index['chains.json'])
    assert 0 < len(chains) <= 200 and {c['resource'] for c in chains} == set(rows), 'Bootstrap index differs from canonical inventory'
    for c in chains:
        assert c['id'].startswith(c['resource'] + '_back_') and c['snapshot'].startswith('back_')
        assert c['tier'] == rows[c['resource']][3] and c['tier'] in ('standard', 'critical')
    gate = kube('GET', CM + 'linstor-protection-gate-status')['data']
    if gate.get('backupReady') != 'true' or int(time.time()) - int(gate.get('checkedAt', '0')) >= 600:
        report(True, 'waiting for recurring backup readiness; no deletion')
        return
    health()
    deleted = 0
    for c in chains:
        if deleted >= 50:
            break
        resource = c['resource']
        backups = linstor('backup', 'list', REMOTE).get('linstor', {})
        roots = [b for b in backups.values() if b['origin_rsc'] == resource and not b.get('based_on_id') and b.get('restorable') is True]
        replacements = [b for b in roots if b['id'] != c['id'] and b['start_timestamp'] > c['start_timestamp']]
        if not replacements:
            continue
        replacement = max(replacements, key=lambda b: b['start_timestamp'])
        info = linstor('backup', 'info', REMOTE, '--id', replacement['id'])
        assert info['count'] == 1, 'Replacement is not an independent full backup'
        snapshots = [s for s in linstor('snapshot', 'list')[0] if s['resource_name'] == resource]
        if any(s.get('props', {}).get(PREFIX + 'ShippingStatus') == 'Shipping' for s in snapshots):
            continue
        # Remove only this old bootstrap's local chain after a newer independent
        # full exists. Keep its remote chain until the tier's full-chain limit.
        old_local = [s for s in snapshots if s.get('props', {}).get(PREFIX + 'LastFullBackupTimestamp', '').lower() == c['snapshot'].lower()]
        old_local.sort(key=lambda s: int(s['props'][PREFIX + 'BackupStartTimestamp']), reverse=True)
        for snap in old_local:
            if deleted >= 50:
                break
            assert snap['props'].get(PREFIX + 'BackupTargetRemote') == REMOTE
            assert snap['name'] != replacement['origin_snap'] and not any('SHIPPING' in flag for flag in snap.get('flags', []))
            health()
            linstor('snapshot', 'delete', resource, snap['name'])
            wait_for(lambda: not any(s['resource_name'] == resource and s['name'] == snap['name'] for s in linstor('snapshot', 'list')[0]), 'Local bootstrap snapshot deletion')
            changes.append({'local_snapshot': snap['name'], 'resource': resource})
            deleted += 1
        keep = 14 if c['tier'] == 'critical' else 7
        if len(roots) <= keep or c['id'] not in backups or deleted >= 50:
            continue
        # The initial chain must be among the oldest excess full chains.
        excess = sorted(roots, key=lambda b: b['start_timestamp'])[:-keep]
        assert c['id'] in {b['id'] for b in excess}, 'Bootstrap chain is still inside retention'
        members = {c['id']}
        for unused in range(len(backups)):
            expanded = members | {key for key, b in backups.items() if ((b.get('based_on_id') or '')[:-5] if (b.get('based_on_id') or '').endswith('.meta') else (b.get('based_on_id') or '')) in members}
            if expanded == members:
                break
            members = expanded
        assert all(backups[key]['origin_rsc'] == resource and not backups[key].get('shipping') for key in members)
        expected = set().union(*(objects(backups[key]) for key in members))
        protected = objects(replacement)
        plan = linstor('backup', 'delete', 'id', REMOTE, c['id'], '--cascade', '--keep-snaps', '--dry-run')
        actual = set()
        for line in plan:
            message = line.get('message', '')
            if message.startswith('Would delete s3 objects:'):
                actual.update(v.strip() for v in message.splitlines()[1:] if v.strip())
            assert 'Would delete Snapshots:' not in message, 'Remote-only prune proposed local deletion'
        assert actual == expected and not (actual & protected), 'Deletion plan exceeds the exact bootstrap chain'
        health()
        linstor('backup', 'delete', 'id', REMOTE, c['id'], '--cascade', '--keep-snaps')
        wait_for(lambda: not (members & set(linstor('backup', 'list', REMOTE).get('linstor', {}))), 'Remote bootstrap chain deletion')
        after = linstor('backup', 'list', REMOTE).get('linstor', {})
        assert after[replacement['id']]['restorable'], 'Replacement full is no longer restorable'
        changes.append({'remote_chain': c['id'], 'resource': resource, 'members': len(members)})
        deleted += 1
    health()
    report(True, 'bootstrap retention checked')


try:
    main()
except Exception as error:
    report(False, str(error))
    raise
