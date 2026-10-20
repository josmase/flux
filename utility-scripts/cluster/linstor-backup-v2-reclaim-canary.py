#!/usr/bin/env python3
"""Finish normal CSI reclaim for explicitly named Released disposable canary PVs."""
import argparse
import json
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--pv', action='append', required=True)
a = p.parse_args()
assert len(a.pv) == len(set(a.pv)) == 2, 'Exactly two reviewed canary PVs required'
namespace = 'linstor-backup-validation'

def get(args):
    return json.loads(subprocess.check_output(['kubectl'] + args, text=True))

pvcs = get(['get', 'pvc', '-A', '-o', 'json'])['items']
reviewed = []
for name in a.pv:
    pv = get(['get', 'pv', name, '-o', 'json'])
    spec = pv['spec']
    ref = spec['claimRef']
    assert pv['status']['phase'] == 'Released'
    assert ref['namespace'] == namespace and ref['name'] in ('source', 'restored')
    assert spec['csi']['driver'] == 'linstor.csi.linbit.com'
    assert spec['csi']['volumeHandle'] == name
    assert spec['capacity']['storage'] == '256Mi'
    assert not any(c['spec'].get('volumeName') == name for c in pvcs)
    reviewed.append(pv)
assert {v['spec']['claimRef']['name'] for v in reviewed} == {'source', 'restored'}
for pv in reviewed:
    patch = [{'op': 'test', 'path': '/metadata/uid', 'value': pv['metadata']['uid']},
             {'op': 'test', 'path': '/spec/claimRef/uid', 'value': pv['spec']['claimRef']['uid']},
             {'op': 'test', 'path': '/status/phase', 'value': 'Released'},
             {'op': 'replace', 'path': '/spec/persistentVolumeReclaimPolicy', 'value': 'Delete'}]
    subprocess.run(['kubectl', 'patch', 'pv', pv['metadata']['name'], '--type=json', '-p', json.dumps(patch)], check=True)
print('Exact disposable PVs returned to ordinary CSI deletion; no finalizers changed.')
