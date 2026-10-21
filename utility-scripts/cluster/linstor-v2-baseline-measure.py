#!/usr/bin/env python3
"""Read-only measurement of all reviewed v2 full backups for retention sizing."""
import argparse
import datetime
import json
import pathlib
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--evidence-dir', type=pathlib.Path, required=True)
a = p.parse_args()
a.evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
l = ['kubectl', '-n', 'piraeus-datastore', 'exec', 'deploy/linstor-controller', '--', 'linstor', '-m']


def get(argv):
    result = subprocess.run(argv, text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, 'Read failed: ' + ' '.join(argv)
    value = json.loads(result.stdout)
    assert not (isinstance(value, list) and any(isinstance(v, dict) and v.get('ret_code', 0) < 0 for v in value)), 'LINSTOR read returned an API error'
    return value


k = ['kubectl', '-n', 'piraeus-datastore', 'get', 'configmap']
manifest = get(k + ['linstor-backup-generation-manifest', '-o', 'json'])['data']
assert manifest['reviewed'] == 'true' and manifest['backupGeneration'] == 'rustfs-linstor-backups-v2'
job = get(['kubectl', '-n', 'piraeus-datastore', 'get', 'job', 'linstor-backup-v2-bootstrap-v4', '-o', 'json'])
assert job['status'].get('succeeded') == 1
backups = get(l + ['backup', 'list', 'rustfs-linstor-backups-v2'])
(a.evidence_dir / 'remote.json').write_text(json.dumps(backups, indent=2))
volumes = []
chains = []
for row in manifest['resources.tsv'].splitlines():
    namespace, pvc, resource, tier, retain = row.split('\t')
    assert retain == 'yes'
    matches = [v for v in backups.get('linstor', {}).values() if v['origin_rsc'] == resource and v.get('restorable') is True and not v.get('based_on_id')]
    assert len(matches) == 1, 'Expected one exact initial full per canonical resource: ' + resource
    b = matches[0]
    info = get(l + ['backup', 'info', 'rustfs-linstor-backups-v2', '--id', b['id']])
    assert info['count'] == 1 and info['rsc'] == resource
    (a.evidence_dir / (resource + '-info.json')).write_text(json.dumps(info, indent=2))
    volumes.append({'namespace': namespace, 'pvc': pvc, 'resource': resource, 'tier': tier, 'backup_id': b['id'], 'snapshot': b['origin_snap'], 'download_bytes': info['dl_size_kib'] * 1024, 'allocated_bytes': info['alloc_size_kib'] * 1024})
    chains.append({'namespace': namespace, 'pvc': pvc, 'resource': resource, 'tier': tier, 'id': b['id'], 'snapshot': b['origin_snap'], 'start_timestamp': b['start_timestamp']})
    print('Measured ' + namespace + '/' + pvc, flush=True)
cnpg = []
for b in backups.get('linstor', {}).values():
    if b.get('origin_snap') in ('snapshot-7384f14a-b892-4b2c-84bf-46a0ec01879f', 'snapshot-dc07d7d5-3f7f-4eda-8b09-51e364a8d472'):
        assert b.get('restorable') is True
        info = get(l + ['backup', 'info', 'rustfs-linstor-backups-v2', '--id', b['id']])
        assert info['count'] == 1
        cnpg.append({'resource': b['origin_rsc'], 'backup_id': b['id'], 'snapshot': b['origin_snap'], 'download_bytes': info['dl_size_kib'] * 1024})
assert len(volumes) == 50 and len(cnpg) == 2
standard = sum(v['download_bytes'] for v in volumes if v['tier'] == 'standard')
critical = sum(v['download_bytes'] for v in volumes if v['tier'] == 'critical')
coordinated = sum(v['download_bytes'] for v in cnpg)
raw_retained = standard * 7 + critical * 14 * 5 + coordinated * 14 * 4
metadata_allowance = 2**30
# Four six-hour increments per daily critical chain, each conservatively sized
# as a measured full, plus 25% growth/transient-shipping allowance globally.
forecast = ((raw_retained + metadata_allowance) * 5 + 3) // 4
gate = get(k + ['linstor-protection-gate-status', '-o', 'json'])['data']
free = int(gate['rustfsFilesystemFreeBytes'])
assert int(datetime.datetime.now(datetime.timezone.utc).timestamp()) - int(gate['checkedAt']) < 600
measured_initial = standard + critical + coordinated
# A lower bound on stored bytes gives a conservative initial free-space forecast.
additional = max(0, forecast - max(0, measured_initial - 2**20))
projected_free = max(0, free - additional)
result = {'measured_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'backup_generation': manifest['backupGeneration'],
          'canonical_non_cnpg_count': len(volumes), 'coordinated_snapshot_count': len(cnpg), 'volumes': volumes, 'cnpg': cnpg,
          'measured_initial_download_bytes': measured_initial, 'standard_daily_full_bytes': standard, 'critical_daily_full_bytes': critical, 'cnpg_recovery_set_bytes': coordinated,
          'retention_projection': {'standard_full_chains': 7, 'critical_full_chains': 14, 'critical_increments_per_chain': 4, 'incremental_assumption': 'each increment equals a measured full', 'cnpg_full_recovery_sets': 56,
                                   'metadata_allowance_bytes': metadata_allowance, 'growth_and_transient_multiplier': '1.25', 'retained_forecast_bytes': forecast,
                                   'observed_filesystem_free_bytes': free, 'initial_additional_forecast_bytes': additional, 'forecast_free_bytes': projected_free,
                                   'minimum_free_bytes': 2**40, 'filesystem_capacity_passes': projected_free >= 2**40},
          'recurring_producers_enabled': False}
(a.evidence_dir / 'result.json').write_text(json.dumps(result, indent=2))
(a.evidence_dir / 'bootstrap-chains.json').write_text(json.dumps(chains, indent=2))
print(json.dumps({'measurement_complete': True, 'canonical': len(volumes), 'retained_forecast_bytes': forecast, 'forecast_free_bytes': projected_free}), flush=True)
