# Manual release authentication

Dispatch `Semantic Release` on `main`, normally with `force-deployment=auto`.
Semantic Release writes
version metadata, pushes its release commit and tag, and creates a GitHub
release. A stable published release triggers `Deploy release`; a prerelease does
not deploy. Merge and branch push events do not initiate releases.

## Required repository setup

- A dedicated write-enabled repository deploy key, with its private half stored
  in the Actions secret `DEPLOY_KEY`.
- A `DeployKey` bypass actor on the `main` ruleset, with `always` bypass. This
  bypass applies to repository deploy keys collectively, not one key ID. Adding
  it is a repository-owner decision; do not silently change branch protections.
- `WORGARSIDE_DEV_TOKEN` remains the GitHub API credential used to create releases.
  A deploy key authenticates Git operations but cannot create a GitHub release
  through the API. The bot token also allows the published event to trigger the
  separate deployment workflow.

The GCF reusable workflow owns SSH setup, host verification, credential cleanup
and release invocation. It uses GitHub's published SSH host keys and SSH on port
443, while `remote.ignore_token_for_push=true` keeps Git pushes on SSH and
`GH_TOKEN` authenticates release API requests. Backplane selects Python 3.14. All callers use the shared CC self-hosted runner
and one Renovate-managed stable PSR pin; the shared GitPython pin is retained.

The caller is managed in GCF at
`gha_sync/workflows/template/semantic-release.template.yml`. Change shared behavior
in GCF and caller settings at that sync source before updating this repository.
The initial caller pins the shared implementation commit; GCF's release pin
updater replaces it with a published version during a later release. Merge the
GCF change before this caller, then perform the separately authorized release.
Never print key values.

## Application deployment

Stable published releases deploy from the shared CC Linux runner over LAN SSH to `10.0.0.108`. GCF's `actions/lan-ssh` provisions temporary SSH files with strict host-key verification and cleans them up automatically. Infrastructure owns the runner's TCP 22 allowlist and the guest's deployment public key.

Set `DEPLOY_SSH_PRIVATE_KEY` in Actions secrets and `DEPLOY_SSH_KNOWN_HOSTS` in Actions variables, using independently verified entries for `10.0.0.108`. Keep `DEPLOY_SSH_USER=root` and `BACKPLANE_INSTALL_DIR=/root/backplane` configured. Use the `production-deploy` environment or repository settings for private repositories on GitHub Free. The workflow checks out the exact release tag on the host and invokes `just _deploy-current`.

## Troubleshooting

For SSH failures, check runner-to-host TCP 22 connectivity, the matching deployment public key and the verified known-hosts entry. Never disable strict host-key checking. For release publication failures, check repository deploy-key write access and ruleset bypass actors without exposing secret values. An authentication failure indicates the key/SSH path; GH013 indicates repository rules. Keep the documented branch protections intact.

After publication, verify `Deploy release` and the live deployed revision, then confirm the music export returns HTTP 200 and advances its retained date. Do not reset the export cursor: successful scheduled runs should clear the backlog.
