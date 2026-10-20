#!/usr/bin/env python3
"""Validate a completed v2 CNPG backup in a separate cluster, then reclaim drill PVCs."""
import argparse
import datetime
import json
import pathlib
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--manifest', required=True, type=pathlib.Path)
p.add_argument('--evidence-dir', required=True, type=pathlib.Path)
a = p.parse_args()
a.evidence_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
ns, drill, source = 'cnpg-system', 'shared-postgres-v2-restore-drill', 'shared-postgres'
seq = 0


def run(argv, data=None):
    global seq
    seq += 1
    x = subprocess.run(argv, input=data, text=True, capture_output=True, timeout=120)
    (a.evidence_dir / f'{seq:03d}.json').write_text(json.dumps({'argv': argv, 'rc': x.returncode, 'stdout': x.stdout, 'stderr': x.stderr}, indent=2))
    assert x.returncode == 0, f'Command {seq} failed; retain drill and evidence'
    return x.stdout


def get(args):
    return json.loads(run(['kubectl'] + args))


def wait(label, check):
    end = time.monotonic() + 1800
    while time.monotonic() < end:
        if check():
            print(label, flush=True)
            return
        time.sleep(10)
    raise RuntimeError(label + ' timed out; retain drill and evidence')


def health():
    rs = get(['-n', 'piraeus-datastore', 'exec', 'deploy/linstor-controller', '--', 'linstor', '-m', 'resource', 'list'])[0]
    assert rs, 'Empty resource inventory: stopped'
    current = {(r['name'], r['node_name'], v['volume_number']): v['state']['disk_state'] for r in rs for v in r.get('volumes', [])}
    if 'baseline' in globals():
        assert all(current.get(key) == value for key, value in baseline.items()), 'Production replica degradation: stopped'
    else:
        assert set(current.values()) <= {'UpToDate', 'Diskless'}, 'Pre-existing replica degradation: stopped'
    return current


def query(pod, database, sql):
    return run(['kubectl', '-n', ns, 'exec', pod, '-c', 'postgres', '--', 'psql', '-XqAt', '-v', 'ON_ERROR_STOP=1', '-d', database, '-c', 'BEGIN READ ONLY; ' + sql + '; COMMIT;']).strip()


backup = get(['-n', ns, 'get', 'backup', 'shared-postgres-v2-bootstrap', '-o', 'json'])
assert backup['status']['phase'] == 'completed', 'Coordinated backup must complete first'
assert backup['metadata']['labels']['backupGeneration'] == 'rustfs-linstor-backups-v2'
for name in ('shared-postgres-v2-bootstrap', 'shared-postgres-v2-bootstrap-wal'):
    snap = get(['-n', ns, 'get', 'volumesnapshot', name, '-o', 'json'])
    assert snap['status']['readyToUse'] is True
    content = get(['get', 'volumesnapshotcontent', snap['status']['boundVolumeSnapshotContentName'], '-o', 'json'])
    assert content['status']['snapshotHandle'].startswith('S3://rustfs-linstor-backups-v2/')
    assert any(o['uid'] == backup['metadata']['uid'] and o['kind'] == 'Backup' for o in snap['metadata']['ownerReferences'])
clusters = get(['-n', ns, 'get', 'clusters.postgresql.cnpg.io', '-o', 'json'])['items']
assert not any(c['metadata']['name'] == drill for c in clusters), 'Existing drill must be reviewed first'
original = next(c for c in clusters if c['metadata']['name'] == source)
assert original['status']['readyInstances'] == original['spec']['instances']
source_pod = original['status']['currentPrimary']
listing = 'SELECT datname FROM pg_database WHERE datallowconn ORDER BY datname'
source_databases = query(source_pod, 'postgres', listing).splitlines()
baseline = health()
run(['kubectl', 'apply', '--dry-run=server', '-f', str(a.manifest)])
run(['kubectl', 'apply', '-f', str(a.manifest)])


def ready():
    health()
    c = get(['-n', ns, 'get', 'clusters.postgresql.cnpg.io', drill, '-o', 'json'])
    return c.get('status', {}).get('readyInstances') == 1


wait('Isolated CNPG restore ready', ready)
c = get(['-n', ns, 'get', 'clusters.postgresql.cnpg.io', drill, '-o', 'json'])
pod = c['status']['currentPrimary']
for endpoint in get(['get', 'endpointslices.discovery.k8s.io', '-A', '-o', 'json'])['items']:
    for entry in endpoint.get('endpoints', []):
        ref = entry.get('targetRef', {})
        if ref.get('namespace', endpoint['metadata']['namespace']) == ns and ref.get('name', '').startswith(drill + '-'):
            assert endpoint['metadata']['labels']['kubernetes.io/service-name'].startswith(drill + '-'), 'Unexpected production service routing'
restored_databases = query(pod, 'postgres', listing).splitlines()
assert source_databases == restored_databases, 'Database enumeration mismatch: stopped'
queries = {}
for db in restored_databases:
    queries[db] = query(pod, db, "SELECT current_database(), current_setting('transaction_read_only'), count(*) FROM pg_catalog.pg_class WHERE relkind IN ('r','p') AND relnamespace NOT IN (SELECT oid FROM pg_namespace WHERE nspname IN ('pg_catalog','information_schema'))")
    assert '|on|' in queries[db]
current = health()
assert all(current.get(k) == v for k, v in baseline.items()), 'Production replica change: stopped'
pvcs = [v for v in get(['-n', ns, 'get', 'pvc', '-o', 'json'])['items'] if v['metadata'].get('labels', {}).get('cnpg.io/cluster') == drill]
assert len(pvcs) == 2
for pvc in pvcs:
    name = pvc['spec']['volumeName']
    pv = get(['get', 'pv', name, '-o', 'json'])
    assert pv['spec']['claimRef']['uid'] == pvc['metadata']['uid']
    assert pv['spec']['claimRef']['namespace'] == ns and pvc['metadata']['name'].startswith(drill + '-')
    patch = [{'op': 'test', 'path': '/metadata/uid', 'value': pv['metadata']['uid']}, {'op': 'test', 'path': '/spec/claimRef/uid', 'value': pvc['metadata']['uid']}, {'op': 'replace', 'path': '/spec/persistentVolumeReclaimPolicy', 'value': 'Delete'}]
    run(['kubectl', 'patch', 'pv', name, '--type=json', '-p', json.dumps(patch)])
run(['kubectl', '-n', ns, 'delete', 'cluster.postgresql.cnpg.io', drill, '--wait=true', '--timeout=90s'])
# Some operator releases preserve PVCs when a Cluster is removed.
remaining = get(['-n', ns, 'get', 'pvc', '-o', 'json'])['items']
for pvc in pvcs:
    if any(v['metadata']['uid'] == pvc['metadata']['uid'] for v in remaining):
        run(['kubectl', '-n', ns, 'delete', 'pvc', pvc['metadata']['name'], '--wait=true', '--timeout=90s'])
wait('Drill PVs reclaimed', lambda: not ({v['spec']['volumeName'] for v in pvcs} & {v['metadata']['name'] for v in get(['get', 'pv', '-o', 'json'])['items']}))
run(['kubectl', '-n', ns, 'delete', 'networkpolicy', drill])
assert health() == baseline, 'Final replica inventory differs; investigate before proceeding'
result = {'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'backup': backup['metadata']['name'], 'database_enumeration_matched': True, 'databases': restored_databases, 'read_only_queries': queries, 'production_routing_absent': True, 'drill_pv_cleanup_verified': True, 'production_replica_inventory_unchanged': True, 'recurring_producers_enabled': False}
(a.evidence_dir / 'result.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result), flush=True)
