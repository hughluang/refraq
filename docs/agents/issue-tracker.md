# Issue tracker: Local Markdown

Issues and specs for this repo live as markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- Open feature directories live at the top level of `.scratch/`. Completed ones live under `.scratch/archive/` (see Completed work)
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`, never a single combined tickets file
- Triage state is recorded as a `Status:` line near the top of each issue file (see `triage-labels.md` for the role strings)
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/` (creating the directory if needed).

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a file with one **child** file per ticket.

- **Map**: `.scratch/<effort>/map.md` (the Notes / Decisions-so-far / Fog body).
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`, with the question in the body. A `Type:` line records the ticket type (`research`/`prototype`/`grilling`/`task`); a `Status:` line records `claimed`/`resolved`.
- **Blocking**: a `Blocked by: NN, NN` line near the top. A ticket is unblocked when every file it lists is `resolved`.
- **Frontier**: scan `.scratch/<effort>/issues/` for files that are open, unblocked, and unclaimed; first by number wins.
- **Claim**: set `Status: claimed` and save before any work.
- **Resolve**: append the answer under an `## Answer` heading, set `Status: resolved`, then append a context pointer (gist + link) to the map's Decisions-so-far in `map.md`.

## Completed work

The top level of `.scratch/` is the open set. A feature directory stays there while any of its work is still open.

When every issue is `done` and the resulting behavior is in `docs/`, or the directory is a finished research note with no remaining ticket, move the whole directory to `.scratch/archive/<feature-slug>/` and set the spec's `Status:` line to `done`. Add that line under the title when it is missing. The archived spec is the local record; the current rule stays in `docs/`. `.scratch/` is gitignored, so the archive is the only copy.

Leave citations in `.process/` as they are. In any file that is still open, and inside the moved directory, rewrite a moved path from `.scratch/<feature-slug>/` to `.scratch/archive/<feature-slug>/`.

When a finished research note names a gap that has no ticket, leave one pointer sentence on a directory that stays open, then archive the note.

A scan for open work reads the top-level directories and skips `.scratch/archive/`.
