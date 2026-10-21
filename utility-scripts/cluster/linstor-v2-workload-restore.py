#!/usr/bin/env python3
"""Restore one reviewed workload directly from S3 into an isolated scratch resource.

Run after serial bootstrap completes. Production snapshots, volumes and remote
objects are preserved. Failures retain the drill and private command journal.
"""
import argparse
import datetime
import json
import pathlib
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('workload', choices=['gitlab-postgresql', 'grafana'])
p.add_argument('--evidence-dir', required=True, type=pathlib.Path)
p.add_argument('--resume', action='store_true', help='Reuse the reviewed existing scratch resource and preserve its original journal')
a = p.parse_args()
a.evidence_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
ns = 'linstor-workload-restore-validation'
remote = 'rustfs-linstor-backups-v2'
target = 'backup-v2-drill-' + a.workload
l = ['kubectl', '-n', 'piraeus-datastore', 'exec', 'deploy/linstor-controller', '--', 'linstor', '-m']
prior_records = [json.loads(f.read_text()) for f in sorted(a.evidence_dir.glob('[0-9]*.json'))]
seq = max((int(f.stem) for f in a.evidence_dir.glob('[0-9]*.json')), default=0)


def run(argv, data=None):
    global seq
    seq += 1
    result = subprocess.run(argv, input=data, text=True, capture_output=True, timeout=120)
    (a.evidence_dir / f'{seq:03d}.json').write_text(json.dumps({'argv': argv, 'rc': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}, indent=2))
    assert result.returncode == 0, f'Command {seq} failed; preserve drill/evidence'
    return result.stdout


def get(argv):
    value = json.loads(run(argv))
    if isinstance(value, list):
        assert not any(isinstance(v, dict) and v.get('ret_code', 0) < 0 for v in value), 'LINSTOR API error; stopped'
    return value


def kube(*argv):
    return get(['kubectl'] + list(argv))


def create(obj):
    run(['kubectl', 'create', '-f', '-'], json.dumps(obj))


def resource_states():
    return {(r['name'], r['node_name'], v['volume_number']): v['state']['disk_state'] for r in get(l + ['resource', 'list'])[0] for v in r.get('volumes', [])}


if a.resume:
    record = next(r for r in prior_records if r['argv'][-2:] == ['resource', 'list'])
    original = json.loads(record['stdout'])[0]
    baseline = {(r['name'], r['node_name'], v['volume_number']): v['state']['disk_state'] for r in original for v in r.get('volumes', [])}
else:
    baseline = resource_states()
assert set(baseline.values()) <= {'UpToDate', 'Diskless'}, 'Pre-existing replica degradation'


def health():
    current = resource_states()
    assert all(current.get(k) == v for k, v in baseline.items()), 'Production replica degradation: stopped'
    assert all(n['connection_status'] == 'ONLINE' for n in get(l + ['node', 'list'])[0]), 'Satellite offline: stopped'
    pools = [v for v in get(l + ['storage-pool', 'list'])[0] if v['storage_pool_name'] == 'linstor-thin']
    assert len(pools) == 3 and all(v['free_capacity'] * 100 >= v['total_capacity'] * 20 for v in pools), 'Capacity violation: stopped'


def wait(label, check):
    end = time.monotonic() + 1800
    while time.monotonic() < end:
        health()
        if check():
            print(label, flush=True)
            return
        time.sleep(10)
    raise RuntimeError(label + ' timed out; preserve drill/evidence')


health()
job = kube('-n', 'piraeus-datastore', 'get', 'job', 'linstor-backup-v2-bootstrap-v4', '-o', 'json')
assert job.get('status', {}).get('succeeded') == 1, 'Serial production bootstrap must finish first'
manifest = kube('-n', 'piraeus-datastore', 'get', 'configmap', 'linstor-backup-generation-manifest', '-o', 'json')['data']
assert manifest['reviewed'] == 'true' and manifest['backupGeneration'] == remote
source_ns, claim = ('gitlab', 'gitlab-postgresql-linstor-v2') if a.workload == 'gitlab-postgresql' else ('monitoring', 'grafana-data-linstor')
row = next(r.split('\t') for r in manifest['resources.tsv'].splitlines() if r.split('\t')[:2] == [source_ns, claim])
source = row[2]
pvc = kube('-n', source_ns, 'get', 'pvc', claim, '-o', 'json')
pv = kube('get', 'pv', pvc['spec']['volumeName'], '-o', 'json')
assert pv['spec']['csi']['driver'] == 'linstor.csi.linbit.com' and pv['spec']['csi']['volumeHandle'] == source
remote_before = get(l + ['backup', 'list', remote])
candidates = [v for v in remote_before.get('linstor', {}).values() if v.get('origin_rsc') == source and v.get('restorable') is True]
assert candidates, 'No restorable v2 backup for canonical workload'
backup = max(candidates, key=lambda v: v['finished_timestamp'])
info = get(l + ['backup', 'info', remote, '--id', backup['id']])
assert info['count'] == 1, 'This drill requires the independent bootstrap full backup'
target_exists = any(r['name'] == target for r in get(l + ['resource-definition', 'list'])[0])
existing_namespace = next((v for v in kube('get', 'namespaces', '-o', 'json')['items'] if v['metadata']['name'] == ns), None)
assert target_exists == a.resume and (existing_namespace is not None) == a.resume, 'Use --resume only for the existing reviewed drill'
if a.resume:
    assert existing_namespace['metadata']['labels'].get('purpose') == 'isolated-workload-restore'
    scratch_pvc = kube('-n', ns, 'get', 'pvc', 'restored', '-o', 'json')
    scratch_pv = kube('get', 'pv', scratch_pvc['spec']['volumeName'], '-o', 'json')
    assert scratch_pv['spec']['csi']['volumeHandle'] == target and target.startswith('backup-v2-drill-')
    assert scratch_pv['spec']['claimRef']['uid'] == scratch_pvc['metadata']['uid']
    assert scratch_pv['spec']['claimRef']['namespace'] == ns
    scratch_pod = kube('-n', ns, 'get', 'pod', 'restore-check', '-o', 'json')
    assert any(v.get('persistentVolumeClaim', {}).get('claimName') == 'restored' for v in scratch_pod['spec']['volumes'])
    run(['kubectl', '-n', ns, 'delete', 'pod', 'restore-check', '--wait=true', '--timeout=90s'])
node = 'kubernetes-node-204'
if a.workload == 'gitlab-postgresql':
    # Reuse a node with the exact production image cached; no credentials copied.
    original_pod = kube('-n', source_ns, 'get', 'pod', 'gitlab-postgresql-0', '-o', 'json')
    node = original_pod['spec']['nodeName']
    image = next(c['image'] for c in original_pod['spec']['containers'] if c['name'] == 'postgresql')
else:
    deployment = kube('-n', source_ns, 'get', 'deployment', 'kube-prometheus-stack-grafana', '-o', 'json')
    image = next(c['image'] for c in deployment['spec']['template']['spec']['containers'] if c['name'] == 'grafana')
# This explicitly downloads to a NEW resource. CSI snapshot restores can reuse a
# local cache; such a clone alone would not verify an independent S3 download.
if not a.resume:
    get(l + ['backup', 'restore', remote, node, target, '--id', backup['id']])
    wait('Independent S3 download complete', lambda: any(k[0] == target and v == 'UpToDate' for k, v in resource_states().items()))
    create({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': ns, 'labels': {'purpose': 'isolated-workload-restore'}}})
    create({'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': 'deny-all-network', 'namespace': ns}, 'spec': {'podSelector': {}, 'policyTypes': ['Ingress', 'Egress']}})
    create({'apiVersion': 'v1', 'kind': 'PersistentVolume', 'metadata': {'name': target}, 'spec': {
        'capacity': pv['spec']['capacity'], 'accessModes': ['ReadWriteOnce'], 'storageClassName': 'linstor',
        'persistentVolumeReclaimPolicy': 'Retain', 'claimRef': {'namespace': ns, 'name': 'restored'},
        'csi': {'driver': 'linstor.csi.linbit.com', 'volumeHandle': target, 'fsType': 'ext4'}}})
    create({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': 'restored', 'namespace': ns, 'labels': {'protection.josmase.dev/restore-drill': 'true'}}, 'spec': {
        'accessModes': ['ReadWriteOnce'], 'volumeName': target, 'storageClassName': 'linstor', 'resources': {'requests': pv['spec']['capacity']}}})
if a.workload == 'gitlab-postgresql':
    uid = 1001
    script = r'''set -eu
    test "$(cat /restore/data/PG_VERSION)" = 14
    chmod 0700 /restore/data
    printf "local all all trust\n" > /tmp/drill-pg-hba.conf
    printf "data_directory='/restore/data'\nhba_file='/tmp/drill-pg-hba.conf'\nlisten_addresses=''\nunix_socket_directories='/tmp'\nport=55432\nshared_buffers='128MB'\nssl=off\narchive_mode=off\n" > /tmp/drill-postgresql.conf
    rm -f /restore/data/postmaster.pid
    /opt/bitnami/postgresql/bin/pg_ctl -D /restore/data -o '-c config_file=/tmp/drill-postgresql.conf' -w start
    /opt/bitnami/postgresql/bin/psql -XqAt -v ON_ERROR_STOP=1 -h /tmp -p 55432 -U postgres -d postgres -c "SELECT 'DRILL_DATABASES=' || json_agg(datname ORDER BY datname)::text FROM pg_database WHERE datallowconn;"
    /opt/bitnami/postgresql/bin/psql -XqAt -v ON_ERROR_STOP=1 -h /tmp -p 55432 -U postgres -d gitlabhq_production -c "SELECT 'DRILL_QUERY=' || json_build_object('database',current_database(),'read_only',current_setting('transaction_read_only'),'public_tables',(SELECT count(*) FROM pg_tables WHERE schemaname='public'))::text;"
    /opt/bitnami/postgresql/bin/pg_ctl -D /restore/data -m fast -w stop
    '''
    mounts = [{'name': 'data', 'mountPath': '/restore'}]
    env = [{'name': 'PGOPTIONS', 'value': '-c default_transaction_read_only=on'}]
else:
    uid = 472
    script = r'''set -eu
    /run.sh &
    server=$!
    trap 'kill -TERM "$server" 2>/dev/null || true' EXIT
    attempt=0
    while [ "$attempt" -lt 60 ]; do
      if result="$(wget -q -O- http://127.0.0.1:3000/api/health 2>/dev/null)"; then
        printf '%s' "$result" > /tmp/drill-health.json
        kill -TERM "$server"
        wait "$server"
        printf 'DRILL_HEALTH=%s\n' "$(tr -d '\r\n' < /tmp/drill-health.json)"
        exit 0
      fi
      attempt=$((attempt + 1))
      sleep 5
    done
    exit 1
    '''
    mounts = [{'name': 'data', 'mountPath': '/var/lib/grafana'}]
    env = [{'name': 'GF_UNIFIED_ALERTING_ENABLED', 'value': 'false'}, {'name': 'GF_ANALYTICS_REPORTING_ENABLED', 'value': 'false'}, {'name': 'GF_ANALYTICS_CHECK_FOR_UPDATES', 'value': 'false'}]
create({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'restore-check', 'namespace': ns}, 'spec': {
    'restartPolicy': 'Never', 'activeDeadlineSeconds': 600, 'nodeSelector': {'kubernetes.io/hostname': node},
    'securityContext': {'runAsUser': uid, 'runAsGroup': uid, 'fsGroup': uid},
    'containers': [{'name': 'verify', 'image': image, 'imagePullPolicy': 'IfNotPresent', 'command': ['/bin/sh', '-ec', script], 'env': env,
                    'resources': {'requests': {'cpu': '100m', 'memory': '512Mi'}, 'limits': {'memory': '2Gi'}}, 'volumeMounts': mounts}],
    'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'restored'}}]}})


def finished():
    pod = kube('-n', ns, 'get', 'pod', 'restore-check', '-o', 'json')
    assert pod['status'].get('phase') != 'Failed', 'Workload restore failed: preserve evidence'
    return pod['status'].get('phase') == 'Succeeded'


wait('Restored workload verification finished', finished)
logs = run(['kubectl', '-n', ns, 'logs', 'restore-check'])
if a.workload == 'gitlab-postgresql':
    databases = json.loads(next(line.split('=', 1)[1] for line in logs.splitlines() if line.startswith('DRILL_DATABASES=')))
    query = json.loads(next(line.split('=', 1)[1] for line in logs.splitlines() if line.startswith('DRILL_QUERY=')))
    assert 'gitlabhq_production' in databases and query['read_only'] == 'on' and query['public_tables'] > 0
    verification = {'databases': databases, 'read_only_query': query}
else:
    health_json = json.loads(next(line.split('DRILL_HEALTH=', 1)[1].strip() for line in logs.splitlines() if 'DRILL_HEALTH=' in line))
    assert health_json['database'] == 'ok'
    verification = {'application_health': health_json}
health()
run(['kubectl', '-n', ns, 'delete', 'pod', 'restore-check', '--wait=true', '--timeout=90s'])
run(['kubectl', '-n', ns, 'delete', 'pvc', 'restored', '--wait=true', '--timeout=90s'])
# Static PV uses Retain: explicitly delete only the isolated target through LINSTOR.
for snap in get(l + ['snapshot', 'list'])[0]:
    if snap['resource_name'] == target:
        get(l + ['snapshot', 'delete', target, snap['name']])
get(l + ['resource-definition', 'delete', target])
wait('Isolated LINSTOR resource reclaimed', lambda: not any(k[0] == target for k in resource_states()))
run(['kubectl', 'delete', 'pv', target, '--wait=true', '--timeout=90s'])
run(['kubectl', 'delete', 'namespace', ns, '--wait=true', '--timeout=90s'])
health()
assert resource_states() == baseline, 'Final production replica inventory differs'
remote_after = get(l + ['backup', 'list', remote])
assert set(remote_after.get('linstor', {})) == set(remote_before.get('linstor', {})), 'Remote artifact set changed during drill'
result = {'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'workload': a.workload, 'tier': row[3], 'source': source_ns + '/' + claim,
          'backup_id': backup['id'], 'independent_s3_download': True, 'download_size_kib': info['dl_size_kib'], 'verification': verification,
          'network_isolated': True, 'production_replica_inventory_unchanged': True, 'remote_backups_preserved': True, 'scratch_cleanup_verified': True}
(a.evidence_dir / 'result.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result), flush=True)
