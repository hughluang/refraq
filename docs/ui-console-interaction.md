# refraq UI: Console Interaction

## 1. Purpose

This document defines which feedback channel carries each kind of feedback, how the Management Console runs a state-changing verb, how it reports success and failure, how live status stays current, and how motion and color scheme behave.

It does not define page chrome, list tables, or record-form field rules. It does not define when a domain verb is legal.

Related boundaries:

- `docs/ui-console-layout.md`
- `docs/ui-console-record-form.md`
- `docs/conventions-errors.md`
- `docs/business-jobs.md`

## 2. Safety Classes

Every header action, row action, and inline toggle declares one safety class. The class is a required field on the action value (`frontend/src/components/feedback/consoleAction.ts`). An object without it does not type-check.

| Class | When | What the operator sees |
| --- | --- | --- |
| `confirm` | Irreversible or high-impact: delete, token deactivate or delete, identity provider disable, User disable, **Job** or **Channel Run** cancel, settings reset, deprecate, drop, publish, and opening the next **Entity** version from the record header | A confirm dialog names the record, states the consequence, says the action cannot be undone, and focuses Cancel |
| `undoable` | The inverse returns the prior state and leaves nothing it cannot undo: **Scheduled Task** enable and disable, group member add and remove, token restore, dictionary restore | The verb runs immediately. The success notification offers Undo for 8 seconds. Undo calls the inverse and refreshes the same list or record |
| `immediate` | No risk, including enabling a User, enabling an identity provider, and starting a **Scheduled Task** run | The verb runs immediately. Success and failure use the same notification rules, with no Undo |

Disabling a User is confirm. It signs that User out of every session, and enabling them again does not restore those sessions. Token restore and dictionary restore stay undoable: deactivating the token again, or deprecating the dictionary again, returns the prior flag. Existing dictionary links stay, and no session is revoked.

A confirm dialog that must collect an extra field (a cascade checkbox, a password, a publish preview) may compose `ConfirmActionModal` directly. The verb is still `confirm`: it does not run before the operator accepts.

## 3. Feedback Channels

The Console has four feedback channels. Each piece of feedback belongs to exactly one.

| Channel | Carries | Lifetime |
| --- | --- | --- |
| Notification | The outcome of an operator-triggered backend interaction: submit, row and header verbs, first load, manual refresh, and the login page | Section 5 |
| Field | Client validation of that input, a mapped `422` error, and an input-derived warning such as low brand contrast | While the input holds the value |
| Status | A condition of the record, result, or surface on screen: a `StatusBadge` with its explanation in a tooltip, a freshness marker, and the `unloaded` state | While the condition holds |
| Callout | Fixed business copy about the form, record, or surface it sits on | While the surface shows it |

1. No outcome renders as a sentence in the content region. A failure is a notification. The content region shows content or a status.
2. A load that failed with nothing to show is the `unloaded` status. It is distinct from empty and no-match: it does not say there is no data, and it does not offer the empty action. The status retries on click and disappears when a retry succeeds. The error notification carries the problem and the same retry.
3. Background polling and automatic refresh are not operator-triggered. Their failure is a freshness marker on the status they refresh (Section 7), not a notification.
4. A Callout states what the surface is, or a rule of the business behind it. A business attribute of the record may decide whether it shows, for example a hidden capability that the operator has turned on. It never carries an outcome, a computed warning, or a backend response. Tones are `info` and `notice`. A Callout has no error tone, no `role="alert"`, and no close control.
5. `Callout` (`frontend/src/components/feedback/Callout.tsx`) is the only importer of `Alert` from `@mantine/core`. `frontend/src/compositionRules.test.ts` enforces it.

ADR 0070 records why `Alert` is not a message channel.

## 4. Mutation Feedback

`useConsoleMutation` (`frontend/src/components/feedback/useConsoleMutation.tsx`) binds one operation to the triggering control.

1. The control shows progress and a second submit is ignored while the operation is in flight.
2. Success title is the localized outcome paired with the record name.
3. When the caller passes `applyApiError`, details that map onto a field show on that field. A `422` whose every detail mapped sends no notification. Every other failure, including the unmapped details of a `422`, is one error notification.
4. After success, and again after a successful undo, the caller refreshes the affected list or record.

## 5. Notifications

Notifications render at the top right, at most three visible at a time (`frontend/src/providers/notification-provider.ts`). Types are `success`, `info`, `warning`, and `error`, each with an icon from the console icon set. Success and info close after 4 seconds. Warning and error stay until dismissed. A progress notification keeps its id so the result replaces it in place.

1. A new notification shows at once. It never waits behind a visible one.
2. When a new notification would exceed the visible limit, the oldest visible success or info is dismissed first, then the oldest warning or error.
3. A notification with the same type and title as a visible one updates that one and shows how many times it repeated. It does not add a second.
4. An error notification for a failed load carries a retry action.

## 6. Problem Presenter

`problemMessage` (`frontend/src/lib/problem.ts`) is the main line of an error. It returns the localized `problems.{code}` string, or the localized `problems.unknown` string when that code has no entry. It never uses the server `detail` as the main message. For `TAG_IN_USE`, when the refusal carries non-negative integer `entity_count` and `channel_count`, that main line states both counts from those extensions, including zero. A refusal that does not carry both counts uses the sentence without counts.

Server `detail`, `request_id`, and unmapped field details sit in a details disclosure with click-to-copy (`ProblemDetails`) inside the error notification. Copy goes through `copyText`.

## 7. Live Status

`useLiveStatus` polls a **Job**, **Channel Run**, or schedule run.

1. The interval is 2 seconds while the status is non-terminal.
2. Polling pauses while the document is hidden and resumes when it is visible.
3. Polling stops at a terminal status.
4. The last result stays on screen during a refresh.
5. The operator can refresh by hand.
6. A failed fetch keeps the last data and adds a freshness marker to the status badge. Hovering it shows the last successful update. Clicking it refreshes. It clears on the next successful fetch.
7. Status changes are announced in a polite live region.

A **Job** reference shows the status badge and the translated kind, with the id as secondary text, and opens **Job** detail.

## 8. Shortcuts

| Shortcut | Effect |
| --- | --- |
| Ctrl+K or Cmd+K | Open the command palette |
| `/` | Focus the list search on the current list |
| `[` | Toggle navigation between expanded and rail |

Single-key shortcuts are ignored while focus is in an editable field and while the channel canvas has focus (a `.react-flow` ancestor). Ctrl+K and Cmd+K open the palette even then.

### 8.1 Channel canvas shortcuts

These shortcuts apply only while focus is inside the channel canvas (a `.channel-canvas-stage` ancestor). Undo, redo, fit, zoom, shortcut help, select all, and arrow-key nudging do not run while focus is in an editable field, the node settings panel, or a modal. Escape still closes an open canvas overlay, including from a field in that overlay, unless that field already handled the key. Delete and Backspace remove the selection only while the graph can be edited. Copy, cut, paste, and duplicate follow that same focus rule. Copy still runs while the graph is locked or the canvas is browsing. Cut, paste, and duplicate do not change the graph then. Tab opens the node picker when focus is in the canvas and no overlay is open. While an overlay is open, Tab moves focus.

| Shortcut | Effect |
| --- | --- |
| Double-click or Enter | Open the settings panel for the node |
| Tab | Open the node picker when no canvas overlay is open |
| Shift+click | Add or remove that node or edge from the selection |
| Shift+drag | Box-select |
| Ctrl+A or Cmd+A | Select every node and edge |
| Ctrl+C or Cmd+C | Copy the selection |
| Ctrl+X or Cmd+X | Cut the selection when the graph can be edited |
| Ctrl+V or Cmd+V | Paste when the graph can be edited. The pointer is the top-left anchor when it is inside the canvas; otherwise the copy is offset by 40px |
| Ctrl+D or Cmd+D | Duplicate the selection when the graph can be edited |
| Arrow keys | Nudge the selection by 8px |
| Shift+arrow keys | Nudge the selection by 40px. Presses within 500ms are one undo step |
| Delete or Backspace | Delete the selection when the graph can be edited |
| Ctrl+Z or Cmd+Z | Undo |
| Shift+Ctrl+Z or Shift+Cmd+Z | Redo |
| Ctrl+Y or Cmd+Y | Redo |
| Shift+1 | Fit the view |
| Ctrl+= or Cmd+= | Zoom in |
| Ctrl+- or Cmd+- | Zoom out |
| Ctrl+0 or Cmd+0 | Zoom to 100% |
| ? | Open keyboard shortcut help |
| Escape | Close the open canvas overlay, or clear the selection when none is open |

Right-click opens a menu at the pointer on a node, a multi-selection, an edge, or empty canvas. Each item shows its shortcut. Delete uses the danger color. While browsing, the menu keeps settings, copy, and fit view. A run lock hides items that change the graph.

The palette sections are Recent, Go to, Create, Records, and Actions. Recent is the latest eight record visits for this User in this browser. Go to lists permitted **Console Navigation** modules. Create lists modules that have a create route and create permission. Records searches the list endpoints for Users, Roles, Sources, Entities, Dictionaries, Channels, and User Groups when the actor may list that module, five results each, after a 250 ms pause. A failed module is omitted. A response for an older query is ignored. Actions toggle the color scheme, toggle navigation width, change language, and open **Account Center**. The palette footer lists the shortcuts with key hints.

## 9. Motion

Motion tokens live in `frontend/src/theme/tokens.ts`.

| Token | Value |
| --- | --- |
| Fast | 120 ms |
| Base | 200 ms |
| Slow | 300 ms |
| Feedback delay | 200 ms |

Easing is standard, enter, and exit. Overlay transitions use the base duration. Motion is for overlays, navigation width, section collapse, notification enter and exit, the route progress bar, pending indicators, and the **Data Channel** canvas motions listed below. Route content, list refetch, and polling refresh do not animate, and motion does not shift layout.

While motion is allowed, Data Channel canvas motion uses opacity, transform, box-shadow, and stroke. It does not move layout. The canvas motions are:

- The edge that enters the node currently running flows along its stroke by animating `stroke-dashoffset`. That flow may be slower than the transition tokens above.
- The running node's status icon rotates.
- When a node's phase changes from running, or from no phase, to succeeded, its status icon appears once. A node that is already succeeded on first load does not play that appearance.
- A node or **Channel Note** created in this session fades in. Pasting, duplicating, and inserting count as creating. Undo and redo do not replay that entrance.
- An edge connected in this session draws along its stroke. The running edge takes priority over that draw.
- Selection and hover change color at the fast duration. That covers the selection ring, the node border, handles, and edge color and width.
- Viewport controls transition at the base duration.

A reduced-motion preference freezes every canvas motion and keeps the running edge in its running color, solid rather than flowing.

The node settings overlay may fade in and out. That motion does not shift layout. A reduced-motion preference shows and hides the overlay immediately.

`respectReducedMotion` is set. Every custom transition and keyframe follows the reduced-motion preference.

## 10. Color Schemes

The console offers light, dark, and system. System is the default. The choice is stored in this browser and applied by a pre-paint script before the first paint, so the first frame matches the stored scheme. It is a display choice: not an **Account Center** preference and not **Site Branding**. The brand palette is the same in both schemes. The logo sits on the surface in both schemes.

## 11. Non-Goals

- Domain rules for when a verb is legal.

## 12. References

- `docs/ui-console-layout.md`
- `docs/ui-console-record-form.md`
- `docs/conventions-errors.md`
- `docs/business-jobs.md`
- `docs/business-branding.md`
- `docs/adr/0070-alert-is-not-a-message-channel.md`
