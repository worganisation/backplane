# Manual releases with protected main

The `Semantic Release` workflow is dispatched manually on `main`. It never
pushes a version commit directly to `main`: repository rules require a PR and
successful checks, including for the release bot.

1. Leave `publish-version` blank and select `force-deployment` (`auto` normally).
   Python Semantic Release calculates the version and commits the version files,
   changelog and lockfile locally, with remote push and GitHub release creation disabled. A local
   temporary tag is created for the release tool's outputs but is never pushed. The workflow pushes a unique preparation branch;
   Auto-Create PR opens its draft PR. If no release is due, no branch is pushed.
2. Review that preparation PR, run its checks and merge it normally. Preparation
   and merge do not publish a release or deploy. Duplicate preparation runs may
   create separate PRs; close obsolete ones instead of merging both.
3. Dispatch `Semantic Release` on `main` again, setting `publish-version` to the
   prepared version (for example `0.8.0` or `0.8.0-rc.1`). The force selector is
   ignored in this mode. Validation requires matching project, runtime and lock
   versions and refuses an existing tag. GitHub creates the release tag at the
   exact main commit captured by this dispatch, not a subsequently moving branch.
4. A stable published release triggers `Deploy release`. Prereleases do not deploy.
   Verify that workflow and then the live service; publication alone is not proof
   of successful deployment.

Keep the existing GitHub environment approval gates. The configured bot token
must be able to push preparation branches and create releases. Unlike the built-in
GitHub token, its release event can trigger the separate deployment workflow.
No branch-protection exemption or direct push to main is needed.

## September 24 failure

Run `36049788133` failed with GH013 when the old single-step workflow tried to
push its generated release commit to main. GitHub required a PR and two status
checks. It failed before publishing a release, so no deployment was triggered.
Do not rerun the old workflow revision: merge this workflow fix, then dispatch
the preparation flow above. If publishing fails, inspect whether a tag or release
was created before retrying; do not delete or move published tags automatically.
