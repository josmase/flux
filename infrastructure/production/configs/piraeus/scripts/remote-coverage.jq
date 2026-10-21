# Verify every canonical standalone resource and the newest coordinated CNPG set.
($remote[0].linstor // {}) as $backups |
[$manifest[0].data["resources.tsv"] | split("\n")[] | select(length > 0) | split("\t") | .[2]] as $required |
(all($required[]; . as $resource | any($backups[]; .origin_rsc == $resource and .restorable == true))) as $standalone |
([$cnpg[0].items[] | select(.status.phase == "completed" and .spec.cluster.name == "shared-postgres")] |
  sort_by(.metadata.creationTimestamp) | last) as $latest |
([$snapshots[0].items[] | {key: .metadata.name, value: .}] | from_entries) as $snaps |
([$contents[0].items[] | {key: .metadata.name, value: .}] | from_entries) as $content |
($latest != null and all($cnpg[0].items[]; .status.phase != "failed" or .metadata.creationTimestamp <= $latest.metadata.creationTimestamp) and ($latest.status.snapshotBackupStatus.elements | map(.type) | sort) == ["PG_DATA", "PG_WAL"] and
  all($latest.status.snapshotBackupStatus.elements[];
    $snaps[.name] as $snap |
    $content[$snap.status.boundVolumeSnapshotContentName // "missing"] as $c |
    (($c.status.snapshotHandle // "") | split("/")) as $handle |
    $snap.status.readyToUse == true and $snap.metadata.deletionTimestamp == null and
    $snap.spec.volumeSnapshotClassName == "linstor-snapshot-s3-v2" and
    any($snap.metadata.ownerReferences[]?; .kind == "Backup" and .uid == $latest.metadata.uid) and
    (($c.status.snapshotHandle // "") | startswith("S3://rustfs-linstor-backups-v2/")) and
    any($backups[]; .origin_rsc == $handle[3] and .origin_snap == $handle[4] and .restorable == true))) as $coordinated |
{standalone: $standalone, coordinated: $coordinated, valid: ($standalone and $coordinated)}
