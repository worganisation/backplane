# Manual release authentication

Dispatch `Semantic Release` on `main`, normally with `force-deployment=auto`.
After the existing production environment approval, Semantic Release writes
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

Checkout installs the SSH credential and verifies GitHub's host key with strict
checking. Semantic Release sets `remote.ignore_token_for_push=true` so Git pushes
use that SSH configuration, while API requests still use `GH_TOKEN`. The release
CLI runs on the runner using Python 3.14 and pinned Python Semantic Release
10.6.2, rather than in a Docker action with different filesystem paths for the
checkout-managed key. `pip` is supplied for the existing release build command.
Checkout's post-job cleanup removes its SSH credentials. Never print key values.

## Troubleshooting

Run `36049788133` failed with GH013 because its HTTPS bot-token push had no ruleset
bypass. Adding a deploy key alone is insufficient: checkout must use it, Semantic
Release must use SSH for pushes, and the ruleset must permit deploy-key bypass.

Check key titles/write permissions, secret names, and ruleset bypass actors without
reading secret values. An authentication failure indicates the key/SSH path;
GH013 indicates repository rules. Do not disable protections globally or add a
second release-preparation PR flow to work around missing release credentials.

After publication, verify `Deploy release` and the live deployed revision, then
confirm the music export returns HTTP 200 and advances its retained date. Do not
reset the export cursor: successful scheduled runs should clear the backlog.
