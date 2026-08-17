# Public History Sanitization Execution Record

## Status

Authorized by the repository owner on 2026-08-14. The original repository was
retained as an owner-controlled private archive, and a separate repository was
created for the sanitized source. That source tree passed the text,
binary-container, spreadsheet-property, and credential gates before its
neutral root commit was created.

The public repository was created from that root and made public on
2026-08-14. Its root is
`0b1061ff567a09981e2cef450a838b5073d55edb` (`Establish sanitized public
source`); the original graph, packages, tags, receipts, and releases were not
copied. Focused source checks passed (`33 passed, 5 skipped`). The only
credential scanner alert was a deterministic test-only ledger identifier; it
is a non-secret false-positive category and its value is intentionally not
recorded here.

The public repository has no public tag, Release asset, or Pages deployment.
The `codex/tauri2-unified-desktop` development line has been prepared from the
sanitized public `main`; it remains a source/Draft-PR line and does not create
binary, Tag, Release, Feed, or platform-release evidence. Security governance
enables DCO, Dependabot, Secret Scanning, Push Protection, and private
vulnerability reporting. A post-public inventory remains required after any
ref-creating governance work to prove every public ref is a descendant of the
sanitized root.

## Published Ref Policy

The public repository follows this policy:

- `main` begins at the sanitized root; every later public head or bot pull
  request ref must be its descendant.
- Pre-publication tags are not recreated; a future tag must identify a newly
  built and audited public version.
- The original repository and all of its refs remain private and untouched.

The final inventory must establish that no public head, tag, pull-request ref,
Release, asset, fork, cache, Pages deployment, or LFS object exposes the
retired graph. Local-only refs, stashes, worktrees, and the private archive
are not public-release inputs.

At the public-transition inventory, only the sanitized `main` was a
maintained public source branch. Later automation pull-request refs are
permitted only when they descend from that root and remain subject to the same
inventory rule.

## Public Graph Form

The public repository begins with one sanitized root snapshot rather than a
value-by-value rewrite of the existing commit graph. The scoped audit found
interconnected business-validation narratives, identifiers, and factual
records spread through historical documentation. A clean root prevents an
incomplete textual replacement from leaving linkable historical facts in an
otherwise public commit.

The private archive retains the original graph for owner-only recovery. The
clean public root has neutral commit identity and contains only the reviewed
current source state; it makes no continuity claim about prior release
identities.

## Authorized Transformation Categories

The rewrite removes or replaces all material in these categories with neutral
descriptions. This record intentionally does not reproduce original values.

- Real local-machine paths from every platform, including path-bearing
  verification records, temporary worktree locations, and user-home paths.
- Any private company, customer, supplier, project, portfolio, or person
  identifier, whether or not it appears beside a path or source invoice.
- Any real business-validation prose, records, filenames, container metadata,
  spreadsheet properties, or source-invoice facts.
- Historic commit subjects, bodies, author/committer/tagger identities, and
  commit/tag signatures. The clean root has neutral identity and no inherited
  tag or signature; copyright attribution remains in `NOTICE`.
- Actual credential or private-key material, if the final verification finds
  any. Public keys and deterministic non-secret test fixtures are not treated
  as credentials.

The public `InvoiceHub` project name, the declared public repository owner,
and the contributor copyright attribution are intentional public identity and
are outside this replacement scope.

## Private Backup And Rollback

- Backup ID: `<owner-private-backup-id>`.
- Storage: `<repository-private-git-dir>/publication-sanitization-backups/`
  under an owner-only directory, outside tracked files and outside every
  remote ref.
- Contents: an all-ref Git bundle, the pre-rewrite worktree patch, and an
  archive of untracked governance inputs.
- Access: the repository owner's local account only; it must never be pushed,
  attached to a Release, or copied into the public working tree.
- Rollback owner: the repository owner. A rollback may restore the private
  archive only in a separately isolated private repository; it must not
  re-expose the retired graph publicly.

## Replacement Version Policy

No pre-sanitization archive is a public release input. Its embedded source
identity belongs to the private graph and cannot be represented by the new
public graph. The first public development version is `v0.3.0-alpha.1`; any
future public binary must be newly built and audited from the sanitized source
graph under a new, higher version.

## Candidate Content Audit

| Field | Record |
| --- | --- |
| Hypothesis | The candidate source tree contains only synthetic fixtures and no remaining private local paths, business identifiers, private release identities, or credentials. |
| Decision changed by result | Pass permits creation of the clean root commit; a real finding requires a local replacement before any commit or remote write. |
| Minimal sample | Every text file in the candidate tree, all tracked-style binary containers, and spreadsheet document properties. |
| Stop condition | Stop at the first real sensitive finding in a category; use one representative finding per category unless the mechanism differs. |

The candidate audit is run once after all replacements. It is not a substitute
for the post-rewrite all-ref gate below.

## Focused Regression Gate

| Field | Record |
| --- | --- |
| Hypothesis | The public-document, version-link, release-contract and synthetic-fixture replacements preserve the affected source contracts. |
| Decision changed by result | Pass permits retaining the clean root candidate and beginning remote verification; a failure limits the fix to the affected documentation, fixture, or release-metadata module. |
| Minimal sample | Documentation contract, summary/cost fixture, release identity, update, source snapshot, Windows contract, and macOS contract tests. |
| Stop condition | Stop on the first failure mechanism; after a fix, rerun only that affected category. Do not run a full regression for this publication-only change. |

## Verification Gate

One post-rewrite all-public-ref verification is authorized. Its experiment
record is fixed here to avoid refresh-only scans:

| Field | Record |
| --- | --- |
| Hypothesis | The rewritten `main` and retained public tags contain no values in the authorized transformation categories. |
| Decision changed by result | Pass permitted the repository to become public; any finding would have kept it private and blocked Release, Feed, and Tauri-public-branch work. |
| Minimal sample | Every ref that will remain public after the ref replacement, including all reachable commits and tags. |
| Stop condition | Stop on the first real sensitive finding; otherwise stop after one completed content scan and one credential scan. |

The verification uses `gitleaks 8.30.1` and a non-emitting business-data
classifier over every retained commit, tree, blob, tag object, text blob, and
candidate binary/container or spreadsheet metadata. Known deterministic test
fixtures are documented as false positives by category only rather than
rotated as credentials.

## Hosting Inventory Gate

Before the public-visibility change, the inventory covered the repository's
remote heads, tags, pull-request head refs, Releases and assets, LFS objects,
and hosting fork/cache state where the hosting API exposes them. After the
public transition, repeat the remote ref and hosting inventory whenever a
governance action creates new refs: every ref must descend from the sanitized
root, and no tag or Release asset may point at the retired graph. A missing
authenticated hosting API result is a blocker, not evidence that the hosting
surface is empty.
