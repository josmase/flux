#!/usr/bin/env python3
"""Restart one drained worker and verify persisted storage before proceeding.

Run on the Ansible jumphost, in order 204, 205, 206. Evidence stays outside
the cluster. Failures retain the cordon and stop; never bypass a PDB.
"""
import argparse
import datetime
import json
import os
import pathlib
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('node', choices=['204', '205', '206'])
p.add_argument('--evidence-root', required=True, type=pathlib.Path)
a = p.parse_args()
os.umask(0o077)
out = a.evidence_root / ('worker-restart-' + a.node)
out.mkdir(mode=0o700, parents=True, exist_ok=True)
assert not list(out.iterdir()), 'Review existing restart journal before retrying'
for previous in ['204', '205', '206'][:['204', '205', '206'].index(a.node)]:
    assert json.loads((a.evidence_root / ('worker-restart-' + previous) / 'result.json').read_text())['verified'] is True
node = 'kubernetes-node-' + a.node
host = 'kubernetes-' + a.node + '.local.hejsan.xyz'
repo = pathlib.Path('/tmp/codex-linstor-rollout/repo')
env = dict(os.environ, ANSIBLE_CONFIG=str(repo/'ansible/ansible.cfg'),
           ANSIBLE_HOME='/tmp/ansible-storage-reapply-home', ANSIBLE_LOCAL_TEMP='/tmp/ansible-storage-reapply-local',
           ANSIBLE_INVENTORY=str(repo/'ansible/inventory/production.ini'), ANSIBLE_VAULT_PASSWORD_FILE=str(repo/'ansible/.vault_pass'),
           ANSIBLE_ROLES_PATH=str(repo/'ansible/roles')+':'+str(repo/'vendor/k3s-ansible/roles'),
           ANSIBLE_COLLECTIONS_PATH=str(repo/'ansible/galaxy_collection'))
k = ['kubectl']
l = k + ['-n', 'piraeus-datastore', 'exec', 'deploy/linstor-controller', '--', 'linstor', '-m']
seq = 0


def run(argv, timeout=120):
    global seq
    seq += 1
    r = subprocess.run(argv, text=True, capture_output=True, env=env, timeout=timeout)
    (out / f'{seq:03d}.json').write_text(json.dumps({'argv': argv, 'rc': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr}, indent=2))
    assert r.returncode == 0, f'Command {seq} failed; stop and retain evidence/cordon'
    return r.stdout


def get(argv):
    value = json.loads(run(argv))
    if isinstance(value, list):
        assert not any(isinstance(v, dict) and v.get('ret_code', 0) < 0 for v in value), 'LINSTOR API failure'
    return value


def ansible(module, args):
    return run(['ansible', host, '--become', '-m', module, '-a', json.dumps(args)], timeout=1200)


def resources():
    return {(r['name'], r['node_name'], v['volume_number']): v.get('state', {}).get('disk_state') for r in get(l + ['resource', 'list'])[0] for v in r.get('volumes', [])}


baseline = resources()
assert baseline and set(baseline.values()) <= {'UpToDate', 'Diskless'}, 'Existing unhealthy replica'
diskful = {key for key, value in baseline.items() if value == 'UpToDate'}


def healthy():
    current = resources()
    return (all(current.get(key) == 'UpToDate' for key in diskful)
            and set(current.values()) <= {'UpToDate', 'Diskless'}
            and all(n['connection_status'] == 'ONLINE' for n in get(l + ['node', 'list'])[0]))


def wait(label, check, seconds=1800):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            print(label, flush=True)
            return
        time.sleep(10)
    raise RuntimeError(label + ' timed out; preserve cordon and evidence')


def cluster():
    return get(k + ['-n', 'cnpg-system', 'get', 'cluster.postgresql.cnpg.io', 'shared-postgres', '-o', 'json'])


def cnpg_ready():
    c = cluster()
    return c['status'].get('readyInstances') == c['spec']['instances'] and c['status'].get('currentPrimary') == c['status'].get('targetPrimary')


def satellite_inventory():
    pods = get(k + ['-n', 'piraeus-datastore', 'get', 'pods', '-o', 'json'])['items']
    pod = next(v for v in pods if v['spec'].get('nodeName') == node and v['metadata']['name'].startswith('linstor-satellite.') and not v['metadata'].get('deletionTimestamp'))
    base = k + ['-n', 'piraeus-datastore', 'exec', pod['metadata']['name'], '-c', 'linstor-satellite', '--']
    pvs = get(base + ['pvs', '--reportformat', 'json', '--units', 'b', '--nosuffix', '-o', 'pv_name,pv_uuid,pv_mda_count,pv_mda_used_count,pv_mda_size', '--select', 'vg_name=linstor_vg'])['report'][0]['pv']
    assert len(pvs) == 2
    old = next(v for v in pvs if v['pv_name'] == '/dev/sdb')
    new = next(v for v in pvs if v['pv_name'] == '/dev/sdc')
    assert int(old['pv_mda_used_count']) == 0 and int(new['pv_mda_count']) == int(new['pv_mda_used_count']) == 2
    assert float(new['pv_mda_size']) >= 2 * 2**30 - 2**20
    vg = get(base + ['vgs', '--reportformat', 'json', '--units', 'b', '--nosuffix', '-o', 'vg_name,vg_free,vg_mda_free,vg_mda_copies', 'linstor_vg'])['report'][0]['vg'][0]
    assert vg['vg_mda_copies'] == 'unmanaged' and float(vg['vg_mda_free']) >= 16 * 2**20
    pool = get(base + ['lvs', '--reportformat', 'json', '--units', 'b', '--nosuffix', '-o', 'lv_name,lv_size,data_percent,lv_profile', 'linstor_vg/linstor_thin'])['report'][0]['lv'][0]
    assert float(pool['lv_size']) >= (814 if a.node == '206' else 740) * 2**30
    assert float(pool['data_percent']) < 80 and pool['lv_profile'] == 'linstor_thin_autoextend'
    profile = run(base + ['cat', '/etc/lvm/profile/linstor_thin_autoextend.profile'])
    assert 'thin_pool_autoextend_threshold = 75' in profile and 'thin_pool_autoextend_percent = 5' in profile
    disks = get(base + ['lsblk', '--json', '--bytes', '--output', 'PATH,SERIAL,SIZE,TYPE,MOUNTPOINTS'])
    assert sum(d.get('serial') == 'linstor-expand-' + a.node for d in disks['blockdevices']) == 1
    lvs = get(base + ['lvs', '--reportformat', 'json', '--units', 'b', '--nosuffix', '-a', '-o', 'lv_name,lv_uuid,lv_size', 'linstor_vg'])['report'][0]['lv']
    path = '/tmp/backup-v2-pre-restart-' + a.node + '.vg'
    run(base + ['vgcfgbackup', '-f', path, 'linstor_vg'])
    run(base + ['cat', path])
    return {'pvs': pvs, 'vg': vg, 'pool': pool, 'lvs': lvs}


assert healthy() and cnpg_ready()
status = get(k + ['-n', 'piraeus-datastore', 'get', 'configmap', 'linstor-backup-generation-status', '-o', 'json'])['data']
assert status['cnpgDeletionVerified'] == 'true' and status['representativeRestoresVerified'] == 'true'
gate = get(k + ['-n', 'piraeus-datastore', 'get', 'configmap', 'linstor-protection-gate-status', '-o', 'json'])['data']
assert gate['backupReady'] == 'false', 'Recurring producers must remain paused'
remote = get(l + ['backup', 'list', 'rustfs-linstor-backups-v2'])
assert all(not v.get('shipping') for v in remote['linstor'].values())
backups = get(k + ['-n', 'cnpg-system', 'get', 'backup', '-o', 'json'])['items']
assert all(v.get('status', {}).get('phase') in ['completed', 'failed'] for v in backups)
before = satellite_inventory()
export = 'backup-v2-worker-' + a.node + '-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json'
get(l + ['controller', 'export-db', '../../../tmp/' + export])
run(k + ['-n', 'piraeus-datastore', 'exec', 'deploy/linstor-controller', '--', 'cat', '/tmp/' + export])
primary = cluster()['status']['currentPrimary']
pod = get(k + ['-n', 'cnpg-system', 'get', 'pod', primary, '-o', 'json'])
if pod['spec']['nodeName'] == node:
    pods = get(k + ['-n', 'cnpg-system', 'get', 'pods', '-l', 'cnpg.io/cluster=shared-postgres', '-o', 'json'])['items']
    standby = next(v for v in pods if v['spec']['nodeName'] != node and v['metadata']['name'] != primary and all(c['ready'] for c in v['status']['containerStatuses']))
    run(['/tmp/codex-linstor-rollout/kubectl-cnpg', '-n', 'cnpg-system', 'promote', 'shared-postgres', standby['metadata']['name']])
    wait('Controlled CNPG switchover complete', lambda: cnpg_ready() and cluster()['status']['currentPrimary'] == standby['metadata']['name'])
run(k + ['get', 'pdb', '-A', '-o', 'json'])
run(k + ['drain', node, '--ignore-daemonsets', '--delete-emptydir-data', '--dry-run=server', '--timeout=60s'])
ansible('ansible.builtin.command', {'argv': ['systemctl', 'is-active', 'lvm2-monitor.service']})
ansible('ansible.builtin.command', {'argv': ['cat', '/etc/lvm/profile/linstor_thin_autoextend.profile']})
boot_before = get(k + ['get', 'node', node, '-o', 'json'])['status']['nodeInfo']['bootID']
print('Preflight and fresh metadata backups complete for ' + node, flush=True)
run(k + ['drain', node, '--ignore-daemonsets', '--delete-emptydir-data', '--timeout=600s'], timeout=700)
assert healthy(), 'Unexpected replica degradation during drain'
ansible('ansible.builtin.reboot', {'reboot_timeout': 600, 'connect_timeout': 10, 'post_reboot_delay': 15, 'msg': 'Approved LINSTOR metadata persistence acceptance'})
wait('All LINSTOR replicas healthy after ' + node + ' restart', healthy)
after = satellite_inventory()
assert {v['pv_uuid'] for v in before['pvs']} == {v['pv_uuid'] for v in after['pvs']}, 'PV identity changed'
assert {v['lv_uuid']: (v['lv_name'], v['lv_size']) for v in before['lvs']} == {v['lv_uuid']: (v['lv_name'], v['lv_size']) for v in after['lvs']}, 'Unexpected LV change'
boot_after = get(k + ['get', 'node', node, '-o', 'json'])['status']['nodeInfo']['bootID']
assert boot_before != boot_after, 'Worker OS reboot not confirmed'
ansible('ansible.builtin.command', {'argv': ['systemctl', 'is-active', 'lvm2-monitor.service']})
ansible('ansible.builtin.command', {'argv': ['lvs', '-o', 'lv_name,seg_monitor,lv_profile', 'linstor_vg/linstor_thin']})
run(k + ['uncordon', node])
wait('CNPG fully recovered after ' + node + ' restart', cnpg_ready)
assert healthy()
result = {'node': node, 'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'verified': True,
          'os_boot_id_changed': True, 'pdb_respected': True, 'pv_identities_preserved': True, 'lv_inventory_preserved': True,
          'metadata_areas_persisted': True, 'metadata_free_bytes': int(float(after['vg']['vg_mda_free'])),
          'pool_size_bytes': int(float(after['pool']['lv_size'])), 'pool_used_percent': float(after['pool']['data_percent']),
          'vg_reserve_bytes': int(float(after['vg']['vg_free'])), 'all_replicas_healthy': True, 'cnpg_instances_ready': True}
(out / 'result.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result), flush=True)
