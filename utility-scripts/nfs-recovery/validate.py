#!/usr/bin/env python3
"""Render actual adopters and the staged Jellyfin migration; no cluster access."""
import json
from pathlib import Path
import subprocess
import tempfile
import shutil
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / 'apps/base/components/nfs-stale-recovery'

def build(path):
    return [o for o in yaml.safe_load_all(subprocess.check_output(['kustomize', 'build', str(path)], text=True)) if o]

def deployment(objects, name):
    return next(o for o in objects if o['kind'] == 'Deployment' and o['metadata']['name'] == name)

def validate(objects, name):
    d = deployment(objects, name)
    spec = d['spec']['template']['spec']
    containers = spec['containers']
    assert len([c for c in containers if c['name'] == 'nfs-stale-recovery']) == 1
    c = next(c for c in containers if c['name'] == 'nfs-stale-recovery')
    assert '@sha256:' in c['image'], 'Production recovery image must be pinned by digest'
    cfg = json.loads(d['spec']['template']['metadata']['annotations']['nfs-recovery.josmase.io/config'])
    assert cfg['container'] in [x['name'] for x in containers]
    assert cfg['deployment'] == name
    assert all(p.startswith('/nfs-check/') and '..' not in p.split('/') for p in cfg['paths'])
    assert c['volumeMounts'] == [{'name': 'shared-storage', 'mountPath': '/nfs-check', 'readOnly': True}]
    assert c['securityContext']['runAsNonRoot']
    assert c['securityContext']['readOnlyRootFilesystem']
    assert c['securityContext']['capabilities']['drop'] == ['ALL']
    cm = next(o for o in objects if o['kind'] == 'ConfigMap' and o['metadata']['name'] == cfg['state_config_map'])
    assert 'data' not in cm, 'Flux must not manage runtime retry history'
    role = next(o for o in objects if o['kind'] == 'Role' and o['metadata']['name'] == cfg['state_config_map'])
    event_rule = next(r for r in role['rules'] if r['resources'] == ['events'])
    assert event_rule['verbs'] == ['create', 'list']
    assert not any(
        '*' in str(rule)
        or 'list' in rule['verbs']
        or 'create' in rule['verbs']
        for rule in role['rules']
        if rule is not event_rule
    )
    assert next(r for r in role['rules'] if r['resources'] == ['configmaps'])['resourceNames'] == [cm['metadata']['name']]
    assert next(r for r in role['rules'] if r['resources'] == ['deployments'])['resourceNames'] == [name]
    assert spec['serviceAccountName'] == cfg['state_config_map']
    return d

photos = build(ROOT / 'apps/production/photos')
immich = validate(photos, 'immich-server')
app = next(c for c in immich['spec']['template']['spec']['containers'] if c['name'] == 'immich-server')
assert app['startupProbe']['httpGet']['path'] == '/api/server/ping'
assert '/external-library' in str(app['readinessProbe']) and '/data' in str(app['readinessProbe'])
assert immich['spec']['strategy']['type'] == 'Recreate'
playback = build(ROOT / 'apps/production/media/playback')
old = deployment(playback, 'jellyfin')
assert any(c['name'] == 'log-watcher' for c in old['spec']['template']['spec']['containers']), 'Do not migrate Jellyfin before Immich observation'
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp)
    # Flattened existing output preserves all image/volume/probe transformations.
    # Remove only the obsolete watcher identities for the proposed migration.
    base = [o for o in playback if o['metadata']['name'] != 'jellyfin-log-watcher']
    shutil.copytree(COMPONENT, p/'component')
    (p/'base.yaml').write_text(yaml.safe_dump_all(base, sort_keys=False))
    (p/'rbac.yaml').write_text((COMPONENT/'examples/jellyfin-rbac.yaml').read_text())
    (p/'patch.yaml').write_text((COMPONENT/'examples/jellyfin-recovery.yaml').read_text())
    (p/'kustomization.yaml').write_text(yaml.safe_dump({'apiVersion':'kustomize.config.k8s.io/v1beta1','kind':'Kustomization','resources':['base.yaml','rbac.yaml'],'components':['component'],'patches':[{'path':'patch.yaml','target':{'kind':'Deployment','name':'jellyfin'}}]},sort_keys=False))
    migrated = build(p)
    new = validate(migrated, 'jellyfin')
    old_app = next(c for c in old['spec']['template']['spec']['containers'] if c['name'] == 'jellyfin')
    new_app = next(c for c in new['spec']['template']['spec']['containers'] if c['name'] == 'jellyfin')
    assert old_app == new_app, 'Jellyfin application/probes/mounts must stay unchanged'
    assert not any(c['name'] == 'log-watcher' for c in new['spec']['template']['spec']['containers'])
    assert old['spec']['template']['spec']['initContainers'] == new['spec']['template']['spec']['initContainers']
    # Two adopters in the same namespace, with isolated identities and budgets.
    selected = [o for o in photos if o['kind'] in ['Deployment','ServiceAccount','Role','RoleBinding','ConfigMap'] and (o['metadata']['name']=='immich-server' or o['metadata']['name']=='nfs-recovery-immich-server')]
    selected = json.loads(json.dumps(selected).replace('"namespace": "immich"','"namespace": "media"'))
    all_objects = selected + migrated
    identities = [(o['apiVersion'],o['kind'],o['metadata'].get('namespace',''),o['metadata']['name']) for o in all_objects]
    assert len(identities) == len(set(identities)), 'Duplicate rendered identities'
    validate(all_objects,'immich-server')
    validate(all_objects,'jellyfin')
print('Validated Immich adoption, staged Jellyfin migration, isolated state/RBAC, and preserved Jellyfin behavior.')
