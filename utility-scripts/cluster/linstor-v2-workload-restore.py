#!/usr/bin/env python3
"""Restore one reviewed workload directly from S3 into an isolated scratch resource.

Run only against a reviewed baseline manifest and its exact remote full backup.
Production snapshots, volumes and remote objects are preserved. Failures retain
the drill and private command journal.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('workload', choices=[
    'grafana', 'sonarr-1', 'sonarr-2', 'sonarr-3', 'sonarr-4', 'sonarr-5', 'sonarr-6',
    'radarr-4', 'prowlarr',
])
p.add_argument('--evidence-dir', required=True, type=pathlib.Path)
p.add_argument('--baseline-manifest', type=pathlib.Path,
               default=pathlib.Path(__file__).resolve().parents[2] / 'docs' / 'LINSTOR_T3_6_BASELINE_MANIFEST_2026-11-13.json')
p.add_argument('--resume', action='store_true', help='Reuse the reviewed existing scratch resource and preserve its original journal')
p.add_argument('--cleanup-only', action='store_true', help='Clean only the exact validated scratch resources from a failed drill')
a = p.parse_args()
if a.cleanup_only and not a.resume:
    raise SystemExit('--cleanup-only requires --resume')
storage_class = os.environ.get('STORAGE_CLASS')
if not storage_class:
    raise SystemExit('STORAGE_CLASS must be set to the canonical LINSTOR StorageClass')
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
    stdout = result.stdout
    if 'resource-definition' in argv and 'list' in argv:
        sensitive_keys = {'secret', 'password', 'passphrase', 'token', 'access_key', 'secret_access_key', 'private_key', 'master_key'}
        def redact(value):
            if isinstance(value, dict):
                return {key: '[REDACTED]' if key.lower() in sensitive_keys else redact(item) for key, item in value.items()}
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value
        try:
            stdout = json.dumps(redact(json.loads(result.stdout)), indent=2)
        except (ValueError, TypeError):
            stdout = '[resource-definition output omitted]'
    (a.evidence_dir / f'{seq:03d}.json').write_text(json.dumps({'argv': argv, 'rc': result.returncode, 'stdout': stdout, 'stderr': result.stderr}, indent=2))
    assert result.returncode == 0, f'Command {seq} failed; preserve drill/evidence'
    return result.stdout


def get(argv):
    value = json.loads(run(argv))
    if isinstance(value, list):
        assert not any(isinstance(v, dict) and v.get('ret_code', 0) < 0 for v in value), 'LINSTOR API error; stopped'
    return value


def kube(*argv):
    return get(['kubectl'] + list(argv))


storage_definition = kube('get', 'storageclass', storage_class, '-o', 'json')
if storage_definition.get('provisioner') != 'linstor.csi.linbit.com':
    raise SystemExit(f'{storage_class} is not a LINSTOR StorageClass')


def create(obj):
    run(['kubectl', 'create', '-f', '-'], json.dumps(obj))


def resource_states():
    return {(r['name'], r['node_name'], v['volume_number']): v.get('state', {}).get('disk_state', 'Pending') for r in get(l + ['resource', 'list'])[0] for v in r.get('volumes', [])}


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
manifest_bytes = a.baseline_manifest.read_bytes()
manifest = json.loads(manifest_bytes)
assert manifest.get('generation') == remote, 'Unexpected reviewed baseline generation'
workloads = {
    'grafana': ('monitoring', 'grafana-data-linstor', 'kube-prometheus-stack-grafana', 'grafana'),
    'sonarr-1': ('media', 'sonarr-1-config-linstor', 'sonarr-1-sonarr', 'sonarr'),
    'sonarr-2': ('media', 'sonarr-2-config-linstor', 'sonarr-2-sonarr', 'sonarr'),
    'sonarr-3': ('media', 'sonarr-3-config-linstor', 'sonarr-3-sonarr', 'sonarr'),
    'sonarr-4': ('media', 'sonarr-4-config-linstor', 'sonarr-4-sonarr', 'sonarr'),
    'sonarr-5': ('media', 'sonarr-5-config-linstor', 'sonarr-5-sonarr', 'sonarr'),
    'sonarr-6': ('media', 'sonarr-6-config-linstor', 'sonarr-6-sonarr', 'sonarr'),
    'radarr-4': ('media', 'radarr-4-config-linstor', 'radarr-4-radarr', 'radarr'),
    'prowlarr': ('media', 'prowlarr-config-linstor', 'prowlarr', 'prowlarr'),
}
source_ns, claim, deployment_name, container_name = workloads[a.workload]
baseline_record = next(r for r in manifest['records'] if r['namespace'] == source_ns and r['pvc'] == claim)
assert baseline_record['ready_to_use'] is True and baseline_record['rustfs_upload_completed'] is True
assert baseline_record['remote_object_id_observed_in_signed_rustfs_listing'] is True
assert baseline_record['volume_snapshot_class'] == 'linstor-snapshot-s3-v2'
assert baseline_record['retention_label'] == 'baseline-protected; retain through old-generation cleanup and T7 acceptance'
row = [source_ns, claim, baseline_record['source_volume_handle'], baseline_record['priority'], 'yes']
source = baseline_record['source_volume_handle']
pvc = kube('-n', source_ns, 'get', 'pvc', claim, '-o', 'json')
pv = kube('get', 'pv', pvc['spec']['volumeName'], '-o', 'json')
assert pv['spec']['csi']['driver'] == 'linstor.csi.linbit.com' and pv['spec']['csi']['volumeHandle'] == source
remote_before = get(l + ['backup', 'list', remote])
candidates = [v for v in remote_before.get('linstor', {}).values()
              if v.get('origin_rsc') == source and v.get('origin_snap') == baseline_record['record_id']
              and v.get('restorable') is True and not v.get('based_on_id')]
assert len(candidates) == 1, 'The exact reviewed T3.6 baseline is not uniquely restorable'
backup = candidates[0]
info = get(l + ['backup', 'info', remote, '--id', backup['id']])
assert info['count'] == 1 and info['rsc'] == source, 'This drill requires the exact independent T3.6 full backup'
target_exists = any(r['name'] == target for r in get(l + ['resource-definition', 'list'])[0])
existing_namespace = next((v for v in kube('get', 'namespaces', '-o', 'json')['items'] if v['metadata']['name'] == ns), None)
assert target_exists == a.resume, 'Use --resume only for the existing reviewed drill'
if a.resume:
    restore_prefix = l + ['backup', 'restore', remote]
    assert any(r['rc'] == 0 and r['argv'][:len(restore_prefix)] == restore_prefix
               and r['argv'][len(restore_prefix) + 1] == target
               and r['argv'][-2:] == ['--id', backup['id']] for r in prior_records), 'Original journal must prove this exact scratch restore'
else:
    assert existing_namespace is None, 'Another isolated drill is present'
if a.resume and existing_namespace is not None:
    assert existing_namespace['metadata']['labels'].get('purpose') == 'isolated-workload-restore'
    scratch_pvc = kube('-n', ns, 'get', 'pvc', 'restored', '-o', 'json')
    scratch_pv = kube('get', 'pv', scratch_pvc['spec']['volumeName'], '-o', 'json')
    assert scratch_pv['spec']['csi']['volumeHandle'] == target and target.startswith('backup-v2-drill-')
    assert scratch_pv['spec']['claimRef']['uid'] == scratch_pvc['metadata']['uid']
    assert scratch_pv['spec']['claimRef']['namespace'] == ns
    if a.cleanup_only:
        scratch_pods = kube('-n', ns, 'get', 'pods', '-o', 'json')['items']
        assert len(scratch_pods) == 1, 'Cleanup-only requires exactly one identified scratch Pod'
        scratch_pod = scratch_pods[0]
    else:
        scratch_pod = kube('-n', ns, 'get', 'pod', 'restore-check', '-o', 'json')
    pod_claims = [v.get('persistentVolumeClaim', {}).get('claimName') for v in scratch_pod['spec']['volumes'] if v.get('persistentVolumeClaim')]
    assert 'restored' in pod_claims and claim not in pod_claims, 'Scratch Pod must mount only the isolated claim'
    if a.cleanup_only:
        run(['kubectl', '-n', ns, 'delete', 'pod', scratch_pod['metadata']['name'], '--wait=true', '--timeout=90s'])
        run(['kubectl', '-n', ns, 'delete', 'pvc', 'restored', '--wait=true', '--timeout=90s'])
        for snap in get(l + ['snapshot', 'list'])[0]:
            if snap.get('resource_name') == target:
                get(l + ['snapshot', 'delete', target, snap['name']])
        get(l + ['resource-definition', 'delete', target])
        wait('Isolated LINSTOR resource reclaimed', lambda: not any(k[0] == target for k in resource_states()))
        run(['kubectl', 'delete', 'pv', target, '--wait=true', '--timeout=90s'])
        run(['kubectl', 'delete', 'namespace', ns, '--wait=true', '--timeout=90s'])
        health()
        assert resource_states() == baseline, 'Production replica inventory differs after cleanup'
        remote_after = get(l + ['backup', 'list', remote])
        assert set(remote_after.get('linstor', {})) == set(remote_before.get('linstor', {})), 'Remote artifact set changed during drill cleanup'
        cleanup_result = {'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'workload': a.workload, 'scratch_cleanup_verified': True, 'production_replica_inventory_unchanged': True, 'remote_backups_preserved': True}
        (a.evidence_dir / 'cleanup.json').write_text(json.dumps(cleanup_result, indent=2))
        print(json.dumps(cleanup_result), flush=True)
        raise SystemExit(0)
    run(['kubectl', '-n', ns, 'delete', 'pod', 'restore-check', '--wait=true', '--timeout=90s'])
node = 'kubernetes-node-204'
if a.workload == 'gitlab-postgresql':
    # Reuse a node with the exact production image cached; no credentials copied.
    original_pod = kube('-n', source_ns, 'get', 'pod', 'gitlab-postgresql-0', '-o', 'json')
    node = original_pod['spec']['nodeName']
    image = next(c['image'] for c in original_pod['spec']['containers'] if c['name'] == 'postgresql')
else:
    deployment = kube('-n', source_ns, 'get', 'deployment', deployment_name, '-o', 'json')
    image = next(c['image'] for c in deployment['spec']['template']['spec']['containers'] if c['name'] == container_name)
    if a.workload == 'grafana':
        uid = 472
    else:
        selector = deployment['spec']['selector']['matchLabels']
        selector_arg = ','.join(f'{key}={value}' for key, value in sorted(selector.items()))
        pods = kube('-n', source_ns, 'get', 'pods', '-l', selector_arg, '-o', 'json')['items']
        running = [pod for pod in pods if pod.get('status', {}).get('phase') == 'Running' and pod.get('spec', {}).get('nodeName')]
        assert running, f'No running source Pod for {a.workload}; stopped before restore'
        node = running[0]['spec']['nodeName']
        uid = 1000
# This explicitly downloads to a NEW resource. CSI snapshot restores can reuse a
# local cache; such a clone alone would not verify an independent S3 download.
if not a.resume:
    get(l + ['backup', 'restore', remote, node, target, '--id', backup['id']])
wait('Independent S3 download complete', lambda: any(k[0] == target and v == 'UpToDate' for k, v in resource_states().items()))
if existing_namespace is None:
    create({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': ns, 'labels': {'purpose': 'isolated-workload-restore'}}})
    create({'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': 'deny-all-network', 'namespace': ns}, 'spec': {'podSelector': {}, 'policyTypes': ['Ingress', 'Egress']}})
    create({'apiVersion': 'v1', 'kind': 'PersistentVolume', 'metadata': {'name': target}, 'spec': {
        'capacity': pv['spec']['capacity'], 'accessModes': ['ReadWriteOnce'], 'storageClassName': storage_class,
        'persistentVolumeReclaimPolicy': 'Retain', 'claimRef': {'namespace': ns, 'name': 'restored'},
        'csi': {'driver': 'linstor.csi.linbit.com', 'volumeHandle': target, 'fsType': 'ext4'}}})
    create({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': 'restored', 'namespace': ns, 'labels': {'protection.josmase.dev/restore-drill': 'true'}}, 'spec': {
        'accessModes': ['ReadWriteOnce'], 'volumeName': target, 'storageClassName': storage_class, 'resources': {'requests': pv['spec']['capacity']}}})
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
elif a.workload == 'grafana':
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
else:
    script = r'''set -eu
    test -s /restore/config.xml
    set -- /restore/*.db*
    test -e "$1"
    printf "DRILL_CONFIG=present\n"
    sleep 1800
    '''
    mounts = [{'name': 'data', 'mountPath': '/restore', 'readOnly': True}]
    env = []
create({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'restore-check', 'namespace': ns}, 'spec': {
    'restartPolicy': 'Never', 'activeDeadlineSeconds': 600, 'nodeSelector': {'kubernetes.io/hostname': node},
    'securityContext': {'runAsUser': uid, 'runAsGroup': uid, 'fsGroup': uid},
    'containers': [{'name': 'verify', 'image': image, 'imagePullPolicy': 'IfNotPresent', 'command': ['/bin/sh', '-ec', script], 'env': env,
                    'resources': {'requests': {'cpu': '10m', 'memory': '128Mi'}, 'limits': {'cpu': '500m', 'memory': '1Gi'}}, 'volumeMounts': mounts}],
    'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'restored'}}]}})


def finished():
    pod = kube('-n', ns, 'get', 'pod', 'restore-check', '-o', 'json')
    assert pod['status'].get('phase') != 'Failed', 'Workload restore failed: preserve evidence'
    if a.workload not in ('grafana', 'gitlab-postgresql'):
        return pod['status'].get('phase') == 'Running'
    return pod['status'].get('phase') == 'Succeeded'


wait('Restored workload verification pod is ready', finished)
logs = run(['kubectl', '-n', ns, 'logs', 'restore-check'])
if a.workload == 'gitlab-postgresql':
    databases = json.loads(next(line.split('=', 1)[1] for line in logs.splitlines() if line.startswith('DRILL_DATABASES=')))
    query = json.loads(next(line.split('=', 1)[1] for line in logs.splitlines() if line.startswith('DRILL_QUERY=')))
    assert 'gitlabhq_production' in databases and query['read_only'] == 'on' and query['public_tables'] > 0
    verification = {'databases': databases, 'read_only_query': query}
elif a.workload == 'grafana':
    health_json = json.loads(next(line.split('DRILL_HEALTH=', 1)[1].strip() for line in logs.splitlines() if 'DRILL_HEALTH=' in line))
    assert health_json['database'] == 'ok'
    verification = {'application_health': health_json}
else:
    # The app image has no sqlite3 CLI. Stream only config.xml and SQLite
    # files from the isolated read-only mount; never journal their contents.
    archive_path = a.evidence_dir / '.restored-config.tar'
    with archive_path.open('wb') as archive_file:
        result = subprocess.run(['kubectl', '-n', ns, 'exec', 'restore-check', '--', '/bin/sh', '-ec', 'cd /restore && tar -cf - config.xml ./*.db*'], stdout=archive_file, stderr=subprocess.PIPE, timeout=300)
    seq += 1
    (a.evidence_dir / f'{seq:03d}.json').write_text(json.dumps({'argv': ['kubectl', '-n', ns, 'exec', 'restore-check', '--', 'tar', 'stream', 'restored config and SQLite files'], 'rc': result.returncode, 'stderr': result.stderr.decode(errors='replace')}, indent=2))
    assert result.returncode == 0, 'Could not stream restored SQLite files from the isolated read-only mount'
    extracted = pathlib.Path(tempfile.mkdtemp(prefix='linstor-sqlite-check-', dir=a.evidence_dir))
    try:
        with tarfile.open(archive_path, 'r:') as archive:
            members = archive.getmembers()
            assert members, 'Empty restored file archive'
            for member in members:
                parts = pathlib.PurePosixPath(member.name).parts
                if parts and parts[0] == '.':
                    parts = parts[1:]
                assert member.isfile() and len(parts) == 1 and parts[0] not in ('', '.', '..'), 'Unexpected path in restored file archive'
                member.name = parts[0]
            archive.extractall(extracted, members=members, filter='data')
        assert (extracted / 'config.xml').is_file() and (extracted / 'config.xml').stat().st_size > 0
        database_files = sorted(extracted.glob('*.db'))
        assert database_files, 'No SQLite databases found on restored volume'
        checked = []
        repairs = []
        for database in database_files:
            connection = sqlite3.connect(database)
            try:
                try:
                    rows = connection.execute('PRAGMA integrity_check').fetchall()
                except sqlite3.DatabaseError as error:
                    if database.name != 'logs.db' or 'malformed' not in str(error).lower():
                        raise
                    connection.close()
                    connection = None
                    database.unlink()
                    for suffix in ('-wal', '-shm'):
                        (extracted / (database.name + suffix)).unlink(missing_ok=True)
                    repairs.append({'database': database.name, 'action': 'removed malformed noncritical logs.db and SQLite sidecars from temporary local copy', 'reason': 'Servarr documented logs database recovery path', 'primary_database_checked': True})
                    checked.append(f'{database.name}:removed_noncritical_corrupt_logs')
                    continue
                if rows != [('ok',)]:
                    repairable = database.name == 'logs.db' and all(
                        message == 'wrong # of entries in index IX_Logs_Time'
                        or (message.startswith('row ') and message.endswith(' missing from index IX_Logs_Time'))
                        for (message,) in rows
                    )
                    index = connection.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='IX_Logs_Time'").fetchone()
                    assert repairable and index, f'SQLite integrity check failed: {database.name}: {rows[:12]}'
                    connection.execute('REINDEX IX_Logs_Time')
                    connection.commit()
                    assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)], f'SQLite integrity check still fails after isolated IX_Logs_Time rebuild: {database.name}'
                    repairs.append({'database': database.name, 'action': 'REINDEX IX_Logs_Time on temporary local copy', 'original_findings': len(rows), 'post_repair_integrity': 'ok'})
                else:
                    connection.close()
                    connection = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
                    assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
            finally:
                if connection is not None:
                    connection.close()
            if database.exists():
                checked.append(f'{database.name}:ok')
    finally:
        shutil.rmtree(extracted, ignore_errors=True)
        archive_path.unlink(missing_ok=True)
    verification = {'sqlite_integrity': checked, 'isolated_local_copy_repairs': repairs, 'config_xml_present': True, 'mounted_read_only': True}
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
          'baseline_snapshot': baseline_record['volumesnapshot'], 'baseline_snapshot_id': baseline_record['record_id'],
          'baseline_manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(), 'backup_id': backup['id'],
          'independent_s3_download': True, 'download_size_kib': info['dl_size_kib'], 'verification': verification,
          'network_isolated': True, 'production_replica_inventory_unchanged': True, 'remote_backups_preserved': True, 'scratch_cleanup_verified': True}
(a.evidence_dir / 'result.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result), flush=True)
