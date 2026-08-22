# Dependency license audit

Audit date: 2026-08-22. Scope: application dependency lockfiles and the three candidate runtime images. Model code and weight terms are audited separately in [`../../MODEL_LICENSES.md`](../../MODEL_LICENSES.md).

## Method

- `pnpm licenses list --prod --json` for the production JavaScript graph;
- `cargo metadata --format-version=1 --locked` for every locked Rust package;
- Python distribution metadata and the Trivy runtime-image package inventory for the worker's `--no-dev` environment;
- Trivy full license classification and generated SBOMs for API, worker and capsule images.

Operating-system scanners often associate every license present in a Debian source package with each emitted binary package. These findings are retained in the image SBOM but evaluated as separately distributed, unmodified system components—not as the license of SMCP source code.

## Application dependency results

- JavaScript production graph: 275 packages; all reported expressions are Apache-2.0, MIT, ISC, BSD-2-Clause, BSD-3-Clause, Unlicense, BlueOak-1.0.0 or 0BSD.
- Rust graph: no missing license expression. All packages offer a permissive choice; `r-efi` includes MIT or Apache-2.0 alternatives alongside LGPL-2.1-or-later.
- Python worker runtime: no package lacks license metadata. `certifi` is MPL-2.0 and `psycopg`/`psycopg-binary` are LGPL-3.0-only; both are recorded in [`../../THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md). Other runtime packages report permissive Apache, BSD, MIT, PSF or compatible dual-license expressions.
- Python SDK runtime: dependency-free apart from the Apache-2.0 package itself.

`pathspec` lacks a machine-readable expression in the local development environment, but is a dev-only transitive dependency of tooling and is absent from the worker runtime image.

### Dependency-review classifier exception

GitHub dependency review currently reports `pkg:pypi/psycopg-binary@3.3.4` as `GPL-3.0-or-later`. The release's verified PyPI metadata declares [`LGPL-3.0-only`](https://pypi.org/project/psycopg-binary/3.3.4/), consistent with the [upstream Psycopg repository license](https://github.com/psycopg/psycopg/blob/3.3.4/LICENSE.txt). The workflow therefore contains an exact, version-pinned PURL exception for this package only. GPL and AGPL remain denied globally; any Psycopg version change requires re-auditing the package metadata and updating or removing the exception.

## Policy

- Do not introduce GPL or AGPL application dependencies into distributed binaries without an explicit legal/architecture decision.
- Weak-copyleft dependencies require notice, unmodified redistribution and satisfaction of their source/relinking terms.
- Unknown license metadata blocks enabling or distributing a model weight and requires manual review for application code.
- Re-run this audit against the release tag's SBOM; lockfile review does not substitute for artifact review.

## Candidate-image SBOM review

The pre-v0.1.0 API, worker and capsule candidates were rebuilt from the audited worktree and emitted as SPDX 2.3 JSON. Every first-party package discovered in the images (`@smcp/api`, `@smcp/schemas` and `smcp-compression-worker`) declares `Apache-2.0`. Remaining `NOASSERTION` records are the OCI document root, the Debian distribution/root packages, a small number of Debian binary packages whose source copyright inventory is mixed, and `benchmarks`/`transport` test-fixture package manifests embedded in licensed upstream npm distributions; none is an unlicensed first-party dependency.

Release CI repeats this check against the exact, single-build candidate before publication. The same SPDX files are attached to the release and bound to the published image digest with an SBOM attestation.
