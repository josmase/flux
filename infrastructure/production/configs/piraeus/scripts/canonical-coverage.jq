# Inputs: current PVC/PV/workload inventory and the reviewed generation manifest.
($pvs[0].items | map(select(.spec.csi.driver == "linstor.csi.linbit.com") |
  {key: .metadata.name, value: .spec.csi.volumeHandle}) | from_entries) as $handles |
[$pvcs[0].items[] | select(.status.phase == "Bound" and $handles[.spec.volumeName] != null) |
  {namespace: .metadata.namespace, name: .metadata.name, handle: $handles[.spec.volumeName], labels: (.metadata.labels // {})}] as $volumes |
([$workloads[0].items[] as $w |
  (if $w.kind == "Pod" then $w.spec
   elif $w.kind == "CronJob" then $w.spec.jobTemplate.spec.template.spec
   else $w.spec.template.spec end) as $spec |
  ($spec.volumes[]? | select(.persistentVolumeClaim != null) |
    {namespace: $w.metadata.namespace, name: .persistentVolumeClaim.claimName}),
  (if $w.kind == "StatefulSet" then
    $w.spec.volumeClaimTemplates[]? as $template |
    ($template.metadata.name + "-" + $w.metadata.name + "-") as $prefix |
    $volumes[] | select(.namespace == $w.metadata.namespace and (.name | startswith($prefix))) |
    {namespace: .namespace, name: .name}
   else empty end)] | unique) as $references |
[$volumes[] as $v | select(any($references[]; .namespace == $v.namespace and .name == $v.name)) | $v |
  select((.namespace == "immich" and (.name | contains("model"))) | not) |
  select((.namespace == "growlog" and (.name | contains("cache"))) | not) |
  select(.labels["protection.josmase.dev/restore-drill"] != "true")] as $canonical |
[$canonical[] | select((.namespace == "cnpg-system" and .labels["cnpg.io/cluster"] == "shared-postgres") | not)] as $standalone |
[$manifest[0].data["resources.tsv"] | split("\n")[] | select(length > 0) | split("\t") |
  {namespace: .[0], name: .[1], handle: .[2], tier: .[3], retain: .[4], fields: length}] as $rows |
[$standalone[] as $v | select(any($rows[]; .namespace == $v.namespace and .name == $v.name and .handle == $v.handle) | not) | $v] as $missing |
[$rows[] as $r | select(any($standalone[]; .namespace == $r.namespace and .name == $r.name and .handle == $r.handle) | not) | $r] as $stale |
{
  currentCanonicalCount: ($canonical | length),
  declaredCanonicalCount: ($manifest[0].data.canonicalVolumeCount | tonumber),
  missing: $missing,
  staleMappings: $stale,
  valid: (($missing | length) == 0 and ($stale | length) == 0 and
    ($canonical | length) == ($manifest[0].data.canonicalVolumeCount | tonumber) and
    ($rows | length) > 0 and ($rows | length) == ($rows | unique_by(.handle) | length) and
    all($rows[]; .fields == 5 and .retain == "yes" and (.tier == "standard" or .tier == "critical")))
}
