#!/usr/bin/env python3
"""Bounded disposable snapshot/S3 restore drill; failures retain all evidence.

Run on the Ansible jumphost with production kubectl access. No recurring
producer or generation-readiness flag is enabled by this script.
"""
import argparse
import collections
import datetime
import json
import pathlib
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--evidence-dir', required=True, type=pathlib.Path)
a = p.parse_args()
a.evidence_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
ns = 'linstor-backup-validation'
remote = 'rustfs-linstor-backups-v2'
k = ['kubectl']
l = k + ['-n', 'piraeus-datastore', 'exec', 'deploy/linstor-controller', '--', 'linstor', '-m']
sequence = 0


def command(args, data=None):
    global sequence
    sequence += 1
    result = subprocess.run(args, input=data, text=True, capture_output=True, timeout=90)
    (a.evidence_dir / f'{sequence:03d}.json').write_text(json.dumps({
        'argv': args, 'returncode': result.returncode,
        'stdout': result.stdout, 'stderr': result.stderr}, indent=2))
    if result.returncode:
        raise RuntimeError(f'Command {sequence} failed; inspect evidence. Resources retained.')
    return result.stdout


def get(args):
    result = json.loads(command(args))
    # LINSTOR sometimes reports API failures with a successful process exit.
    if isinstance(result, list) and any(isinstance(x, dict) and x.get('ret_code', 0) < 0 for x in result):
        raise RuntimeError(f'LINSTOR API failure at command {sequence}; resources retained.')
    return result


def create(obj):
    command(k + ['create', '-f', '-'], json.dumps(obj))


def wait(description, check, seconds=900):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            print(description, flush=True)
            return
        time.sleep(5)
    raise RuntimeError(f'Timed out: {description}; resources retained.')


def states():
    return {(r['name'], r['node_name'], v['volume_number']): v.get('state', {}).get('disk_state')
            for r in get(l + ['resource', 'list'])[0] for v in r.get('volumes', [])}


baseline = states()
assert set(baseline.values()) <= {'UpToDate', 'Diskless'}, 'Pre-existing replica degradation'


def health():
    current = states()
    assert all(current.get(key) == value for key, value in baseline.items()), 'Replica degradation: stopped'
    nodes = get(l + ['node', 'list'])[0]
    assert all(n['connection_status'] == 'ONLINE' for n in nodes), 'Satellite offline: stopped'


def host_inventory():
    out = {}
    pods = get(k + ['-n', 'piraeus-datastore', 'get', 'pods', '-o', 'json'])['items']
    for pod in pods:
        if not pod['metadata']['name'].startswith('linstor-satellite.kubernetes-node-'):
            continue
        base = k + ['-n', 'piraeus-datastore', 'exec', pod['metadata']['name'], '-c', 'linstor-satellite', '--']
        vg = get(base + ['vgs', '--reportformat', 'json', '--units', 'b', '--nosuffix', '-o', 'vg_name,vg_mda_free'])['report'][0]['vg'][0]
        lv = get(base + ['lvs', '--reportformat', 'json', '-a', '-o', 'lv_name,lv_uuid,lv_size', 'linstor_vg'])['report'][0]['lv']
        pool = get(base + ['lvs', '--reportformat', 'json', '-o', 'data_percent', 'linstor_vg/linstor_thin'])['report'][0]['lv'][0]
        assert float(pool['data_percent']) < 80, 'Pool below 20% free: stopped'
        out[pod['spec']['nodeName']] = {'metadata_free_bytes': int(float(vg['vg_mda_free'])), 'lvs': lv}
    assert len(out) == 3
    return out


health()
initial_hosts = host_inventory()
initial_remote = get(l + ['backup', 'list', remote])
# Refuse reuse: an interrupted drill must be inspected before another starts.
existing = get(k + ['get', 'namespaces', '-o', 'json'])['items']
assert not any(x['metadata']['name'] == ns for x in existing), 'Canary namespace already exists; review previous run'
create({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': ns, 'labels': {'backupGeneration': remote, 'purpose': 'disposable-backup-validation'}}})
create({'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': 'isolate-drill', 'namespace': ns}, 'spec': {'podSelector': {}, 'policyTypes': ['Ingress', 'Egress']}})


def pvc(name, snapshot=None):
    spec = {'accessModes': ['ReadWriteOnce'], 'storageClassName': 'linstor', 'resources': {'requests': {'storage': '256Mi'}}}
    if snapshot:
        spec['dataSource'] = {'name': snapshot, 'kind': 'VolumeSnapshot', 'apiGroup': 'snapshot.storage.k8s.io'}
    create({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': name, 'namespace': ns}, 'spec': spec})


def disposable_reclaim_delete(claim):
    pvc_object = get(k + ['-n', ns, 'get', 'pvc', claim, '-o', 'json'])
    pv_name = pvc_object['spec']['volumeName']
    pv_object = get(k + ['get', 'pv', pv_name, '-o', 'json'])
    ref = pv_object['spec']['claimRef']
    assert ref['namespace'] == ns and ref['name'] == claim
    assert ref['uid'] == pvc_object['metadata']['uid']
    patch = [{'op': 'test', 'path': '/metadata/uid', 'value': pv_object['metadata']['uid']},
             {'op': 'test', 'path': '/spec/claimRef/uid', 'value': ref['uid']},
             {'op': 'replace', 'path': '/spec/persistentVolumeReclaimPolicy', 'value': 'Delete'}]
    command(k + ['patch', 'pv', pv_name, '--type=json', '-p', json.dumps(patch)])


def pod(name, claim, script, readonly=False):
    create({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': ns}, 'spec': {
        'restartPolicy': 'Never', 'activeDeadlineSeconds': 600,
        'containers': [{'name': 'check', 'image': 'busybox:1.37.0', 'command': ['/bin/sh', '-ec', script],
                        'resources': {'requests': {'cpu': '10m', 'memory': '16Mi'}, 'limits': {'memory': '64Mi'}},
                        'volumeMounts': [{'name': 'data', 'mountPath': '/data', 'readOnly': readonly}]}],
        'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': claim, 'readOnly': readonly}}]}})
    def done():
        phase = get(k + ['-n', ns, 'get', 'pod', name, '-o', 'json'])['status'].get('phase')
        assert phase != 'Failed', f'{name} failed: stopped'
        return phase == 'Succeeded'
    wait(name + ' completed', done)
    checksum = command(k + ['-n', ns, 'logs', name]).strip()
    assert len(checksum.split()[0]) == 64, 'Missing SHA256'
    command(k + ['-n', ns, 'delete', 'pod', name, '--wait=true', '--timeout=90s'])
    return checksum.split()[0]


pvc('source')
expected = pod('writer', 'source', 'dd if=/dev/urandom of=/data/payload bs=1M count=8 2>/dev/null; sync; sha256sum /data/payload')
pv = get(k + ['-n', ns, 'get', 'pvc', 'source', '-o', 'json'])['spec']['volumeName']
handle = get(k + ['get', 'pv', pv, '-o', 'json'])['spec']['csi']['volumeHandle']
health()
before = host_inventory()


def snapshot(name, cls):
    create({'apiVersion': 'snapshot.storage.k8s.io/v1', 'kind': 'VolumeSnapshot', 'metadata': {'name': name, 'namespace': ns}, 'spec': {'volumeSnapshotClassName': cls, 'source': {'persistentVolumeClaimName': 'source'}}})
    def ready():
        s = get(k + ['-n', ns, 'get', 'volumesnapshot', name, '-o', 'json']).get('status', {})
        assert not s.get('error'), f'{name} snapshot error: stopped'
        return s.get('readyToUse') is True
    wait(name + ' ready', ready, 1800)
    s = get(k + ['-n', ns, 'get', 'volumesnapshot', name, '-o', 'json'])
    return s['status']['boundVolumeSnapshotContentName']


content = snapshot('metadata-calibration', 'linstor-snapshot-prunable')
during = host_inventory()
growth = {}
for node in before:
    old = {v['lv_uuid'] for v in before[node]['lvs']}
    new = {v['lv_uuid'] for v in during[node]['lvs']}
    assert old <= new and len(new - old) == 1, 'Unexpected calibration LV change'
    growth[node] = max(0, before[node]['metadata_free_bytes'] - during[node]['metadata_free_bytes'])
assert max(growth.values()) > 0, 'No measurable metadata growth; calibration remains false'
command(k + ['-n', ns, 'delete', 'volumesnapshot', 'metadata-calibration', '--wait=true', '--timeout=90s'])
wait('Calibration content removed', lambda: not any(x['metadata']['name'] == content for x in get(k + ['get', 'volumesnapshotcontents', '-o', 'json'])['items']))
after = host_inventory()
for node in before:
    assert before[node]['lvs'] == after[node]['lvs'], 'Calibration cleanup changed LV inventory'
health()
content = snapshot('s3-canary', 'linstor-snapshot-s3-v2')
s3content = get(k + ['get', 'volumesnapshotcontent', content, '-o', 'json'])
s3handle = s3content['status']['snapshotHandle']
assert s3handle.startswith('S3'), 'Snapshot is not S3-backed'
backups = get(l + ['backup', 'list', remote])
assert any(v.get('restorable') for key, v in backups.get('linstor', {}).items() if key.startswith(handle + '_')), 'No restorable remote backup'
health()
pvc('restored', 's3-canary')
actual = pod('reader', 'restored', 'sha256sum /data/payload', True)
assert expected == actual, 'Restore checksum mismatch: stopped'
health()
# Remove only disposable objects after checksum agreement. Never clear finalizers.
disposable_reclaim_delete('restored')
command(k + ['-n', ns, 'delete', 'pvc', 'restored', '--wait=true', '--timeout=90s'])
command(k + ['-n', ns, 'delete', 'volumesnapshot', 's3-canary', '--wait=true', '--timeout=90s'])
wait('S3 content removed', lambda: not any(x['metadata']['name'] == content for x in get(k + ['get', 'volumesnapshotcontents', '-o', 'json'])['items']))
wait('S3 remote backup removed', lambda: not any(key.startswith(handle + '_') for key in get(l + ['backup', 'list', remote]).get('linstor', {})))
disposable_reclaim_delete('source')
command(k + ['-n', ns, 'delete', 'pvc', 'source', '--wait=true', '--timeout=90s'])
wait('Disposable resources removed', lambda: not any(r['name'] == handle for r in get(l + ['resource', 'list'])[0]))
health()
final_hosts = host_inventory()
for node in initial_hosts:
    assert initial_hosts[node]['lvs'] == final_hosts[node]['lvs'], 'Disposable LV cleanup mismatch'
final_remote = get(l + ['backup', 'list', remote])
assert final_remote == initial_remote, 'Remote listing differs after cleanup; retain evidence'
result = {'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'source_handle': handle,
          'snapshot_handle': s3handle, 'expected_sha256': expected, 'restored_sha256': actual,
          'metadata_growth_bytes_per_worker': growth, 'bytes_per_snapshot_lv': max(growth.values()),
          'kubernetes_content_cleanup_verified': True, 'worker_lv_cleanup_verified': True,
          'remote_listing_cleanup_verified': True,
          'production_replicas_unchanged': True, 'recurring_producers_enabled': False}
(a.evidence_dir / 'result.json').write_text(json.dumps(result, indent=2))
command(k + ['delete', 'namespace', ns, '--wait=true', '--timeout=90s'])
print(json.dumps(result), flush=True)
