# Agile and Git workflow

Owner: Isaac Hernandez. Updated October 29, 2026. Local workflow and CI are prepared;
remote branch protection, issue board and PR enforcement have not been configured.

## Tasks and acceptance

Use [the backlog](agile-backlog.md) with Backlog, Ready, In Progress, Review, Done
and Blocked. Each task takes at most two working days; at its boundary demonstrate
results or create a separate continuation. Tie the eventual issue, branch and PR
to its LD ID, owner, planned week, acceptance criteria and dependencies. Record
completed/unfinished goals, blockers and next goals at the weekly check-in.

A documentation task can finish with accepted documents and passing contract/link
checks. A feature task needs demonstrated behavior. A deployment task needs actual
release/recovery evidence. Do not mark integration Done because a plan exists.

## Branches and environments

Use short-lived `feature/<area>`, `fix/<area>`, `docs/<area>` or `integration/<area>`
branches and review through PRs into `dev`. The local `dev` branch contains the
combined foundation, backend and authentication work pending publication approval.
Keep teammates' feature branches and commit histories intact. Release candidates
move from `dev` to `main` through a separate reviewed PR.

Suggested owner branches include feature/public-website, feature/catering-form,
feature/pricing-api, feature/authentication, feature/email-automation and
feature/database-schema. `integration/staging` is optional coordination only; it
has not been created and is not required for each document edit.

Main holds reviewed release candidates. Development, test/staging and production
are separate running environments; the current DEV runtime is localhost. First demonstrate
changes locally, run PR checks/review, then approve a scoped staging release. Production
requires its own release decision. Avoid maintaining extra branches without a purpose.

```sh
# Example only: inspect local work before choosing an unused branch name.
git status --short --branch
git switch -c feature/your-task dev
git diff --check
git diff
# Stage explicit reviewed paths and inspect the staged diff before asking to commit.
```

Isaac requires explicit approval before each commit or push, as clarified on
October 29. Remote repository settings remain unchanged. Use focused commit
subjects such as `feat(foundation): add shared app shells` or
`docs(contracts): record database mappings`. Keep credentials, customer data and
emojis out of commits. Review new untracked files as well as tracked diffs.

## PRs and CI

Use the [PR template](../.github/pull_request_template.md) and [review checklist](code-review.md).
Record task/week, problem and resulting behavior, owner/consumers, acceptance evidence,
config/schema impact and blockers. Attach UI screenshots when a browser is available;
label unavailable UI verification. Use synthetic examples for API changes.

Isaac reviews shared boundaries; feature owners review their areas; Bryson reviews
DB work. Contract changes require affected consumers. Someone other than the author
provides approval; local preparation is not that approval. Obtain Isaac's prior approval
before changing teammate-owned features, with reason, owner and minimal impact.

The [foundation workflow](../.github/workflows/foundation-checks.yml) runs on PR/push:
contract/examples/links/config checks, backend tests with disposable MySQL, and frontend
build. It uses read-only repository permissions and has no deployment job. Remote
execution is recorded in GitHub Actions after publication. Once actual runs exist, configure its successful
job names as required checks; do not claim settings are enforced already.
The [DEV publication review](dev-review.md) records the initial combined change;
the [release workflow](release-workflow.md) describes later environment promotions.

## Conflicts

1. Preserve local work before fetching/updating. Never discard another owner's changes.
2. Merge the base into shared feature branches; rebase private work only by agreement.
3. Resolve each conflict with its owner, comparing intended interfaces and examples.
4. Rerun affected checks and review the final diff. Avoid force-pushing shared history.
5. Escalate incompatible API or migration changes to Isaac before merging.

## Definition of done and protection

Done requires clear ownership/acceptance, actual applicable checks, addressed review,
reproducible setup, accurate docs, safe secrets/data handling and dependent-owner handoff.
Migrations also require compatibility/recovery evidence. Record failed, blocked and
unexecuted checks explicitly.

Recommend required PRs, at least one independent approval, resolved conversations,
working required checks and no direct/force pushes to main. Remote settings need
explicit authorization. Add CODEOWNERS only after verifying team GitHub handles;
no protections or CODEOWNERS enforcement are claimed here.
