# refraq Version Conventions

## 1. Scope

This document defines the installable product version: the legal git tag, which external contracts and which upgrade path that number speaks for, and how the next tag is chosen. It does not define image build, Release assets, or the site install procedure.

Related boundaries:

- Release trigger, image names, stamped compose, and site install: `docs/development.md`
- Environment files and variable ownership: `docs/env.md`
- Problem `code`: `docs/conventions-errors.md`
- Product-domain naming: `docs/modules.md`
- **Webhook** delivery: `docs/api-contracts-webhooks.md`
- **MCP endpoint**: `docs/api-contracts-metadata-mcp.md`

## 2. Tag Form

The installable version is a git tag `vX.Y.Z`. `X`, `Y`, and `Z` are integers written in canonical decimal form: `0`, then `1`, `2`, and so on, with no leading zero. `X` may be `0`. `v0.2.0` is legal. `v1.2`, `v01.2.0`, `v0.2`, and `v0.2.0-rc.1` are not.

That tag is the only release number. One tag names the api image, the web image, and the Release assets of that publish. The image tag is the same three numbers without the leading `v` (`docs/development.md`).

The FastAPI application `version` and `frontend/package.json` `version` are not this number. Publishing does not read them and does not update them.

A tag outside this grammar is not a version here, including when a workflow run starts for it.

## 3. External Contracts

Three contracts count. The **Management Console** does not.

| Contract | A break is a change to |
| --- | --- |
| Site HTTP API | The semantics of an existing request, including a problem `code` a caller already branches on (`docs/conventions-errors.md`) |
| **MCP endpoint** | The arguments or the result of an existing tool |
| **Webhook** | The HTTP request a delivery sends to the saved endpoint, or the response the platform treats as success (`docs/api-contracts-webhooks.md`) |

A semantic change includes an existing successful request that now fails, and a field or problem `code` whose existing meaning changes. An added optional field, an added endpoint, and an added tool are not a semantic change of an existing contract.

## 4. Standard Upgrade

The standard upgrade is the site procedure in `docs/development.md`: replace the site compose, leave the live `.env` in place, add any new keys from that release's `.env.example` by hand, then pull and start. Schema migration that runs on process start, including **Foundation Upgrade**, is part of that path.

The standard upgrade holds when that procedure finishes with existing data still present and the process up. A new required variable that `.env.example` and the release notes name, and that the process accepts once the operator adds it, still leaves the procedure intact.

The procedure is broken when it finishes with existing data gone, or when the process is still not up. A data-directory move that makes replace-and-start create an empty data directory is this case.

## 5. Bumps While The Major Is Zero

While the greatest legal tag has major `0`, the major component stays `0`. Breaks in §3 and §4 use a minor bump. `v1.0.0` is not selected by feature size. Several rules at once use the highest class: minor, then patch.

A product domain is a body of behavior that `docs/modules.md` names as a product domain. Management Foundation, the metadata foundation, and platform mechanisms are not a new product domain by appearing in that document.

### 5.1 Minor

A minor bump applies when any of these is true:

1. A product domain is in an installable image for the first time.
2. An existing external contract in §3 changes meaning.
3. A new environment variable has no default and the process does not start until the operator sets it.
4. The operator must move data once, or must take a manual step that process-start migration does not perform. §4's empty-data-directory case is this bump.

### 5.2 Patch

A patch bump applies when the change stays inside an existing product domain, leaves §3 unchanged, and leaves the standard upgrade as the operator's procedure:

- A compatible addition, including a new optional field, endpoint, or tool.
- A **Management Console** change, including a new screen and a removed screen.
- Process-start migration that keeps existing data.
- A new environment variable that has a default.

### 5.3 No Tag

Do not push a tag when the only changes are documents, tests, or comments.

## 6. Bumps From 1.0.0

`v1.0.0` is the first tag that promises compatibility inside that major: existing §3 contracts and the §4 upgrade still hold for later tags of the same major. The release author cuts it by making that promise. While every legal tag has major `0`, the only major bump is this cut, and the tag is `v1.0.0`.

From `v1.0.0` onward, the highest class wins: major, then minor, then patch.

| Bump | When |
| --- | --- |
| Patch | A defect fix. Existing §3 semantics stay. The standard upgrade is enough. |
| Minor | A compatible capability. A new required variable is a minor bump when §4 still holds after the operator adds it and existing §3 contracts remain. A new variable that has a default is a minor bump when it ships a capability. A **Management Console** change that adds or alters a capability, while §3 and §4 still hold, is a minor bump. A console-only defect fix stays a patch. |
| Major | An existing §3 contract breaks, or the §4 upgrade breaks. The empty-data-directory case is a major bump. |

A new optional field, endpoint, or tool is a minor bump in this era. A new product domain's first installable image is a minor bump unless a major rule also applies.

## 7. Choosing The Next Tag

When no legal tag exists, the first tag is `v0.1.0`.

Otherwise take every tag that matches §2 and compare `X`, `Y`, and `Z` as integers. The greatest is the base. The next tag is numerically greater than every existing legal tag. An older minor or an older major receives no further tag after a greater tag exists. A prior Release stays downloadable (`docs/development.md`).

An installable release is a tag for which both image manifests exist and the GitHub Release attaches the stamped compose (`docs/development.md`). A tag that has not reached that point is occupied.

When the base is not an installable release, the next tag is the base with its patch component increased by one. Repeat until the name is unused. Do not delete the occupied tag and push the same name.

When the base is an installable release, apply one bump:

| Bump | Next tag |
| --- | --- |
| Patch | Same major, same minor, patch increased by one |
| Minor | Same major, minor increased by one, patch `0` |
| Major | Major increased by one, minor `0`, patch `0` |

From `v0.4.2`, a patch bump is `v0.4.3`, a minor bump is `v0.5.0`, and the first major cut is `v1.0.0`. When the greatest tag is `v0.5.0` and that tag is not an installable release, the next tag is `v0.5.1`. From `v1.4.2`, a major bump is `v2.0.0`.

## 8. Forbidden

1. A pushed tag outside §2.
2. Reusing a legal tag name, including after a publish that never became an installable release.
3. A legal tag numerically less than an existing legal tag.
4. A major bump other than `v1.0.0` while every existing legal tag has major `0`.
5. Reading the distance between two tags as a promise that the older tag can be restored over data written by the newer one.

## 9. Non-Goals

- Image build, Release asset contents, and the site install steps (`docs/development.md`).
- A workflow check that rejects a tag. A missing `.github/release-notes/<tag>.md` does not block the Release. Operator steps for a bump stay in that release's notes (`docs/development.md`).
- **Channel Version**, **Entity Version**, and `draft_revision`.
- Treating the FastAPI application `version` or `frontend/package.json` `version` as the installable version.

## 10. References

- `docs/development.md`
- `docs/env.md`
- `docs/conventions-errors.md`
- `docs/modules.md`
- `docs/api-contracts-webhooks.md`
- `docs/api-contracts-metadata-mcp.md`
- `docs/glossary.md`
