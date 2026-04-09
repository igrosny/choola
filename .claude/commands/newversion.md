# New Version Release

You are helping the user cut a new release for the `choola` pip package. Follow these steps exactly and in order.

## Step 1 — Find the last release

Read `CHANGELOG.md` and extract:
- The **last released version** (the most recent `## [x.y.z] - YYYY-MM-DD` heading, ignoring `[Unreleased]`)
- The **release date** in `YYYY-MM-DD` format

## Step 2 — Collect commits since that release

Run the following git command to get all commits after the release date:

```bash
git log --oneline --after="<release_date>" --no-merges
```

List every commit message. Do not filter yet.

## Step 3 — Summarize into changelog entries

Group the commits into the standard Keep a Changelog sections that apply:
- **Added** — new features, new nodes, new CLI commands
- **Changed** — modifications to existing behavior
- **Fixed** — bug fixes
- **Removed** — deleted features or files
- **Infrastructure** — build, CI, packaging, config changes
- **Frontend** — UI changes (JSX, CSS, Vite, etc.)

Rules:
- Drop trivial commits (typos, formatting, "wip", "cleanup" with no substance)
- Merge similar commits into a single bullet
- Each bullet must be a complete sentence starting with an imperative verb (Add, Fix, Update, Remove…)
- Omit any section that has no entries

## Step 4 — Determine the new version

Apply Semantic Versioning to the **last released version**:
- If there are breaking changes → bump **major**
- If there are new features (Added section non-empty) → bump **minor**
- Otherwise → bump **patch**

Tell the user the proposed new version and the bump reason **before making any file changes**, and ask for confirmation if the bump type is ambiguous or if there are no commits to release.

## Step 5 — Update CHANGELOG.md

Insert a new section **above** the last release (but below `## [Unreleased]`) in this format:

```markdown
## [<new_version>] - <today's date YYYY-MM-DD>

### Added
- ...

### Changed
- ...

### Fixed
- ...
```

Include only sections that have entries. Do not touch the `[Unreleased]` section or any earlier entries.

## Step 6 — Update pyproject.toml

Change the `version` field in `pyproject.toml` to the new version string.

## Step 7 — Confirm what changed

Show the user:
1. The new version number
2. The exact diff of the two files changed (`CHANGELOG.md` and `pyproject.toml`)

Do not run `git commit` or `pip` commands unless the user explicitly asks.

$ARGUMENTS
