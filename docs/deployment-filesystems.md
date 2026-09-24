# Vault writes and deployment filesystems

Atomic replacement requires the temporary file and destination to be on the same
filesystem. Running both paths inside one LXC does not guarantee this. Always
create temporary files in the destination directory; do not use the default
system temporary directory or fall back to a non-atomic copy. Temporary files
must be cleaned up on success and failure, and a failed replacement must leave
the existing note intact. The helper's regression tests enforce these properties.

## Observed deployment: 24 September 2026

Read-only inspection of the `backplane` LXC (108, `10.0.0.108`) found:

| Path | Mount | Filesystem | Source |
| --- | --- | --- | --- |
| `/tmp` | `/tmp` | `tmpfs` | `tmpfs` |
| `/root/obsidian/vaults/my-vault` | `/` | ZFS | `data/vmdata/subvol-108-disk-0` |

The paths had different device IDs (205 and 59 respectively). Device IDs and
mount layouts are observations, not permanent configuration values. Python's
default temporary directory was `/tmp`; AnyIO was 4.14.2. The deployed revision
was `58b4af0ce1377a274398d49c34999d746ad593d8`.

`backplane.service` runs as root in `/root/backplane`, using
`.venv/bin/python -m backplane.mcp`. `PrivateTmp` and `ProtectSystem` were disabled.
Its environment file is `/root/backplane/.env`; do not print or copy its secrets.
Both output streams append to `/var/log/backplane/backplane.log`, so the systemd
journal alone does not contain application exception traces.

`obsidian-sync.service` was active, running `ob sync --path
/root/obsidian/vaults/my-vault --continuous` as root. Its log is
`/var/log/backplane/obsidian-sync.log`. The vault resolved to the same path, with
no symlink redirect. Both mounts had free space. No service or mount settings
were changed during inspection.

## Failure and diagnosis

The music export PATCH reached `/api/obsidian/daily-note`, but creating the
September 19 note failed with `OSError: [Errno 18] Invalid cross-device link`:
a `/tmp/backplane-*.tmp` file could not be atomically renamed into `Daily Notes`.
The API returned HTTP 500. Home Assistant correctly retained its September 19
export cursor for retry. This was a filesystem-boundary failure, not an API
routing, disk-capacity, or stopped-sync-service problem.

Useful read-only checks inside the LXC:

```sh
findmnt -T /tmp -o TARGET,SOURCE,FSTYPE,OPTIONS
findmnt -T /root/obsidian/vaults/my-vault -o TARGET,SOURCE,FSTYPE,OPTIONS
stat -c '%n device=%d permissions=%a owner=%U:%G' /tmp /root/obsidian/vaults/my-vault
systemctl show backplane -p User -p WorkingDirectory -p PrivateTmp -p ProtectSystem
systemctl is-active backplane obsidian-sync
```

Inspect a bounded portion of the application log around the failed request;
avoid sharing unrelated note content or credentials. Check the running service's
mount namespace too if future sandboxing introduces a private namespace.

## Rollout verification

After an approved deployment and Backplane restart, verify an actual music
export returns HTTP 200, updates the intended daily note, and only then advances
`input_datetime.music_listening_export_date`. Verify the note syncs to Obsidian.
Do not reset the cursor to today: the existing 15-minute retry schedule processes
one outstanding day per successful run. Confirm the backlog clears and a later
nightly export succeeds. Merge or passing tests alone do not prove deployment.
