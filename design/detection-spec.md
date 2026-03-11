# Detection Spec (Draft)

## Goal
- Detect changes inside `pkgmgr.yaml` management scope.
- Decide whether each changed file is a pkg management target.
- If it is a target, verify open-pkg update state.
- If it is not a target, ask for user confirmation as "changed but unused".
- Use Git only as a secondary signal.

## Primary Input
- Primary diff source: current filesystem scan vs `baseline.json`.
- Diff kinds: `added`, `modified`, `deleted`.
- `snapshot.json` is not the primary input for detect.

## Git Role
- Git results are emitted in `git_view` as supplemental diagnostics.
- Git differences increase warning count only.
- Git statuses do not participate in `fail_on`.

## Naming
- Use `detection` consistently (not `detaction`).

## Core Status Codes
- `IN_ACTIVE_PKG`
- `CHANGED_NOT_UPDATED`
- `DELETED_NOT_UPDATED`
- `TRACKED_CHANGED_NOT_IN_PKG`
- `UNTRACKED_NOT_IN_PKG`
- `CHANGED_BUT_UNUSED_CHECK_REQUIRED`
- `AMBIGUOUS_PKG`

## File to Pkg Mapping
- Candidate open pkg set comes from `include.releases` and latest update metadata.
- If multiple open pkg candidates exist, select pkg with latest update timestamp.
- If timestamps are equal or no update history exists, classify as `AMBIGUOUS_PKG`.

## Grouping Output
- Group shape: `pkg -> artifact class -> reason -> files`
- Artifact class examples:
  - `bin=<name>`
  - `lib=<name>`
  - `lua=<name>`
  - `sh=<name>`
  - `sql=<name>`
  - `data=<name>`
  - `etc=<name>`

## Output Sections
- `summary`
- `managed_by_reason`
- `unmanaged_by_reason`
- `by_reason`
- `managed_view`
- `unmanaged_view`
- `git_view` (currently for `GIT_UNTRACKED` indicator only)
- `ambiguous_only` (detailed file-level output for `AMBIGUOUS_PKG` only)
- `result` (policy verdict + exit code)

## Snapshot and Baseline
- `snapshot` is standalone runtime capture (`snapshot.json`).
- `snapshot` must not mutate baseline.
- Baseline updates are explicit operations (separate from snapshot).

## Lifecycle Hook
- On `close-pkg`, create point and refresh baseline in a controlled flow.
- Recommended order: `point create -> baseline refresh -> mark pkg closed`.
