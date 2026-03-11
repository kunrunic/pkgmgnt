# EDR Remote Scan Design (PKGMGR + QuailLabU)

## Scope
- Remote-only EDR scan execution from QuailLabU.
- Execute per pkg_id.
- Transfer only release data (no full PKG payload).
- Store scan artifacts only in QuailLabU.

## Confirmed Requirements
- EDR scan runs on remote host only.
- QuailLabU initiates remote scan.
- Execution unit: pkg_id.
- Output stored in QuailLabU; other hosts do not retain artifacts.
- SSH uses RSA key + password prompt; password injection allowed.
- Release data scope is defined by pkg.yaml and the structure produced by:
  `update-pkg <pkg_id> --release`.
- EDR target path example:
  `/home/dev/PKG/SKTIN/<pkg_id>/<sub-root>/...`
- sub-root entries under a pkg_id do not duplicate.
- PDF is required; if automated creation is not supported, user generates PDF via SentinelOne console.

## Data Scope (Release Only)
- Source of truth: pkg.yaml.
- Transfer exactly the files/dirs created by `update-pkg --release`.
- No full PKG data is transferred; only release artifacts and metadata.

## Remote Execution Flow
1) QuailLabU prepares release payload for pkg_id using pkg.yaml + update-pkg release output.
2) QuailLabU transfers payload to remote EDR host:
   `/home/dev/PKG/SKTIN/<pkg_id>/<sub-root>/...`
3) QuailLabU runs on remote:
   - `sentinelctl scan start /home/dev/PKG/SKTIN/<pkg_id>`
   - Poll `sentinelctl scan status` until `finished`.
4) QuailLabU collects logs and stores outputs locally.

## Output Structure (QuailLabU)
- Keep existing text format for scan log:
  `<output_root>/<pkg_id>/<sub-root>/sentinelon 실행결과.txt`
- output_root is local to QuailLabU.

## Concurrency / Locking
- Prevent duplicate scans for the same pkg_id.
- Suggested approach:
  - Remote lock file: `/var/run/qualilabu/edr/<pkg_id>.lock`
  - If lock exists and scan is active, return "in progress".

## Auth and Security
- SSH with RSA key, password prompt allowed.
- Sudo password injection is allowed (no persistent storage of passwords).
- Log remote commands and responses in the output log.

## PDF Generation
### Preferred (Automated) if Supported
- Generate report via SentinelOne API (if endpoint exists).
- Download PDF via SentinelOne API using report_id.

### Fallback (Manual)
- User generates report in SentinelOne console.
- QuailLabU can optionally ingest the downloaded PDF.

## Interfaces (Draft)
- `pkgmgr actions send_edr --pkg-id <id>`:
  - Build release payload and transfer to EDR host path.
- `pkgmgr actions run_edr --pkg-id <id>`:
  - Start scan remotely, poll until finished, collect logs.
- Optional:
  - `pkgmgr actions fetch_edr_pdf --pkg-id <id> --report-id <id>`

## Open Questions
- SentinelOne API availability for report generation in the target tenant.
- Final list of files/dirs produced by `update-pkg --release` (confirm examples).
- Locking granularity: pkg_id only vs (pkg_id, system).

## Reference Structures (Provided Samples)
### QuailLabU pkgstore state
- Root: `/Users/kunrunic/WORK/data/pkgstore/state`
- Example paths:
  - `state/systems/AOCS/pkg/R675/readme/OCS2/README.txt`
  - `state/systems/AOCS/pkg/R675/release/release-20260129T153635.json`
  - `state/systems/AOCS/pkg/R675/release_artifacts/OCS2/release.v0.0.2.tar`
  - `state/systems/AOCS/pkg/R675/export/cksum_R675_20260129_v2.xlsx`

### Release package sample (update-pkg --release output)
- Root: `/Users/kunrunic/PKG/RELEASE/R675`
- Top-level:
  - `OCS2/`
  - `export/`
  - `release/`
  - `pkg.yaml`
- Example paths:
  - `export/cksum_R675_20260129_v2.xlsx`
  - `OCS2/bin/...`, `OCS2/lib/...`, `OCS2/data.ocs2/...`
  - `release/OCS2/release.v0.0.1.tar`
  - `release/OCS2/HISTORY/release.v0.0.1/...`
