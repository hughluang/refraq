# refraq UI: Console Interaction

## 1. Purpose

This document defines how the Management Console runs a state-changing verb, how it reports success and failure, how live status stays current, and how motion and color scheme behave.

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

## 3. Mutation Feedback

`useConsoleMutation` (`frontend/src/components/feedback/useConsoleMutation.tsx`) binds one operation to the triggering control.

1. The control shows progress and a second submit is ignored while the operation is in flight.
2. Success title is the localized outcome paired with the record name.
3. A field or form error, when the caller passes `applyApiError`, stays on the form frame (`FormErrorSummary`). Every other failure is an error notification.
4. After success, and again after a successful undo, the caller refreshes the affected list or record.

## 4. Notifications

Notifications render at the top right, at most three at a time (`frontend/src/providers/notification-provider.ts`). Each type has an icon from the console icon set. Success and info close after 4 seconds. Errors stay until dismissed. A progress notification keeps its id so the result replaces it in place.

## 5. Problem Presenter

`problemMessage` (`frontend/src/lib/problem.ts`) is the main line of an error. It returns the localized `problems.{code}` string, or the localized `problems.unknown` string when that code has no entry. It never uses the server `detail` as the main message.

Server `detail` and `request_id` sit in a details disclosure with click-to-copy (`ProblemDetails`, also used by `FormErrorSummary`). Copy goes through `copyText`.

## 6. Live Status

`useLiveStatus` polls a **Job**, **Channel Run**, or schedule run.

1. The interval is 2 seconds while the status is non-terminal.
2. Polling pauses while the document is hidden and resumes when it is visible.
3. Polling stops at a terminal status.
4. The last result stays on screen during a refresh.
5. The operator can refresh by hand.
6. A failed fetch keeps the last data, shows an inline stale notice, and offers retry.
7. Status changes are announced in a polite live region.

A **Job** reference shows the status badge and the translated kind, with the id as secondary text, and opens **Job** detail.

## 7. Shortcuts

| Shortcut | Effect |
| --- | --- |
| Ctrl+K or Cmd+K | Open the command palette |
| `/` | Focus the list search on the current list |
| `[` | Toggle navigation between expanded and rail |

Single-key shortcuts are ignored while focus is in an editable field and while the channel canvas has focus (a `.react-flow` ancestor). Ctrl+K and Cmd+K open the palette even then.

### 7.1 Channel canvas shortcuts

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

The palette sections are Recent, Go to, Create, Records, and Actions. Recent is the latest eight record visits for this User in this browser. Go to lists permitted **Console Navigation** modules. Create lists modules that have a create route and create permission. Records searches the list endpoints for Users, Roles, Sources, Entities, Dictionaries, Channels, Business Domains, and User Groups when the actor may list that module, five results each, after a 250 ms pause. A failed module is omitted. A response for an older query is ignored. Actions toggle the color scheme, toggle navigation width, change language, and open **Account Center**. The palette footer lists the shortcuts with key hints.

## 8. Motion

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

## 9. Color Schemes

The console offers light, dark, and system. System is the default. The choice is stored in this browser and applied by a pre-paint script before the first paint, so the first frame matches the stored scheme. It is a display choice: not an **Account Center** preference and not **Site Branding**. The brand palette is the same in both schemes. The logo sits on the surface in both schemes.

## 10. Non-Goals

- Domain rules for when a verb is legal.

## 11. References

- `docs/ui-console-layout.md`
- `docs/ui-console-record-form.md`
- `docs/conventions-errors.md`
- `docs/business-jobs.md`
- `docs/business-branding.md`
