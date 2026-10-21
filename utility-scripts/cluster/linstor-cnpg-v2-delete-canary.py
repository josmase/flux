#!/usr/bin/env python3
"""Verify ownership-driven deletion of one explicitly disposable CNPG S3 set.

Preserve every pre-existing Backup and remote record. On failure leave the
canary and private command journal for investigation; do not retry blindly.
"""
import argparse
import datetime
import json
import pathlib
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--evidence-dir', required=True, type=pathlib.Path)
a = p.parse_args()
a.evidence_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
assert not list(a.evidence_dir.glob('[0-9]*.json')), 'Review prior canary before reuse'
ns = 'cnpg-system'
name = 'shared-postgres-v2-deletion-canary'
remote = 'rustfs-linstor-backups-v2'
k = ['kubectl']
l = k + ['-n', 'piraeus-datastore', 'exec', 'deploy/linstor-controller', '--', 'linstor', '-m']
seq = 0


def run(argv, data=None):
    global seq
    seq += 1
    r = subprocess.run(argv, input=data, text=True, capture_output=True, timeout=120)
    (a.evidence_dir / f'{seq:03d}.json').write_text(json.dumps({'argv': argv, 'rc': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr}, indent=2))
    assert r.returncode == 0, f'Command {seq} failed; retain evidence and canary'
    return r.stdout


def get(argv):
    value = json.loads(run(argv))
    if isinstance(value, list):
        assert not any(isinstance(v, dict) and v.get('ret_code', 0) < 0 for v in value), 'LINSTOR API error'
    return value


def states():
    return {(r['name'], r['node_name'], v['volume_number']): v.get('state', {}).get('disk_state') for r in get(l + ['resource', 'list'])[0] for v in r.get('volumes', [])}


baseline = states()
assert baseline and set(baseline.values()) <= {'UpToDate', 'Diskless'}


def health():
    assert states() == baseline, 'Replica inventory changed: stopped'
    assert all(n['connection_status'] == 'ONLINE' for n in get(l + ['node', 'list'])[0]), 'Satellite offline'
    pools = [v for v in get(l + ['storage-pool', 'list'])[0] if v['storage_pool_name'] == 'linstor-thin']
    assert len(pools) == 3 and all(v['free_capacity'] * 100 >= v['total_capacity'] * 20 for v in pools), 'Capacity violation'
    c = get(k + ['-n', ns, 'get', 'cluster.postgresql.cnpg.io', 'shared-postgres', '-o', 'json'])
    assert c['status'].get('readyInstances') == c['spec']['instances'], 'CNPG instances not all ready'


def wait(label, check):
    end = time.monotonic() + 3600
    while time.monotonic() < end:
        health()
        if check():
            print(label, flush=True)
            return
        time.sleep(10)
    raise RuntimeError(label + ' timed out; preserve evidence')


health()
before = get(l + ['backup', 'list', remote])
assert len(before.get('linstor', {})) >= 52
assert all(not b.get('shipping') for b in before['linstor'].values()), 'Wait for existing shipping'
backups_before = get(k + ['-n', ns, 'get', 'backups.postgresql.cnpg.io', '-o', 'json'])['items']
assert not any(b['metadata']['name'] == name for b in backups_before), 'Disposable Backup already exists'
run(k + ['create', '-f', '-'], json.dumps({
    'apiVersion': 'postgresql.cnpg.io/v1', 'kind': 'Backup',
    'metadata': {'name': name, 'namespace': ns, 'labels': {
        'backupGeneration': remote + '-canary', 'protection.josmase.dev/disposable': 'true'}},
    'spec': {'cluster': {'name': 'shared-postgres'}, 'method': 'volumeSnapshot'}}))


def completed():
    b = get(k + ['-n', ns, 'get', 'backup', name, '-o', 'json'])
    assert b.get('status', {}).get('phase') != 'failed', 'Canary backup failed'
    return b.get('status', {}).get('phase') == 'completed'


wait('Disposable coordinated data/WAL backup complete', completed)
b = get(k + ['-n', ns, 'get', 'backup', name, '-o', 'json'])
assert b['metadata']['labels']['protection.josmase.dev/disposable'] == 'true'
elements = b['status']['snapshotBackupStatus']['elements']
assert sorted(e['type'] for e in elements) == ['PG_DATA', 'PG_WAL']
identities, contents = [], []
for element in elements:
    snap = get(k + ['-n', ns, 'get', 'volumesnapshot', element['name'], '-o', 'json'])
    assert snap['status']['readyToUse'] is True
    assert any(o['uid'] == b['metadata']['uid'] and o['kind'] == 'Backup' for o in snap['metadata']['ownerReferences'])
    content = get(k + ['get', 'volumesnapshotcontent', snap['status']['boundVolumeSnapshotContentName'], '-o', 'json'])
    assert content['spec']['deletionPolicy'] == 'Delete'
    handle = content['status']['snapshotHandle'].split('/')
    assert len(handle) == 5 and handle[:3] == ['S3:', '', remote]
    identities.append((handle[3], handle[4]))
    contents.append(content['metadata']['name'])
shipped = get(l + ['backup', 'list', remote])
canary_ids = {key for key, value in shipped['linstor'].items() if (value['origin_rsc'], value['origin_snap']) in identities and value.get('restorable') is True}
assert len(canary_ids) == 2 and not (canary_ids & set(before['linstor']))
assert set(shipped['linstor']) == set(before['linstor']) | canary_ids
# Delete only the exact reviewed canary UID using the Kubernetes precondition.
deletion = {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'preconditions': {'uid': b['metadata']['uid']}, 'propagationPolicy': 'Background'}
run(k + ['delete', '--raw', f'/apis/postgresql.cnpg.io/v1/namespaces/{ns}/backups/{name}', '-f', '-'], json.dumps(deletion))


def reclaimed():
    snaps = get(k + ['-n', ns, 'get', 'volumesnapshots', '-o', 'json'])['items']
    if any(s['metadata']['name'] in {e['name'] for e in elements} for s in snaps):
        return False
    vcs = get(k + ['get', 'volumesnapshotcontents', '-o', 'json'])['items']
    if any(c['metadata']['name'] in contents for c in vcs):
        return False
    listing = get(l + ['backup', 'list', remote])
    if set(listing.get('linstor', {})) != set(before['linstor']):
        return False
    # LINSTOR lists unmatched/orphan S3 keys in `other`; ensure no canary debris.
    if listing.get('other', {}) != before.get('other', {}):
        return False
    snaps = get(l + ['snapshot', 'list'])[0]
    return not any((s['resource_name'], s['name']) in identities for s in snaps)


wait('Canary Kubernetes, local snapshot and remote artifacts reclaimed', reclaimed)
remaining = get(k + ['-n', ns, 'get', 'backups.postgresql.cnpg.io', '-o', 'json'])['items']
assert {v['metadata']['uid'] for v in remaining} == {v['metadata']['uid'] for v in backups_before}, 'Pre-existing Backup inventory changed'
health()
result = {'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'backup': name,
          'canary_remote_records': sorted(canary_ids), 'owner_reference_verified': True,
          'backup_uid_precondition_used': True, 'snapshot_content_deletion_policy': 'Delete',
          'kubernetes_snapshot_cleanup_verified': True, 'local_snapshot_cleanup_verified': True,
          'remote_records_and_orphan_objects_cleanup_verified': True,
          'preexisting_remote_record_count': len(before['linstor']), 'preexisting_backups_preserved': True,
          'production_replica_inventory_unchanged': True}
(a.evidence_dir / 'result.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result), flush=True)
