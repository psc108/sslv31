# Docs — Developer Reference

## Table of Contents

1. [Overview](#1-overview)
2. [Libraries, Shelves & Documents](#2-libraries-shelves--documents)
3. [Reading a Document](#3-reading-a-document)
4. [Editing a Document](#4-editing-a-document)
5. [Annotations & Highlights](#5-annotations--highlights)
6. [Map View](#6-map-view)
7. [Structured / Card View](#7-structured--card-view)
8. [Search](#8-search)
9. [Error Knowledge Base](#9-error-knowledge-base)
10. [Bug Tracker](#10-bug-tracker)
11. [Linking Docs to JAR Analyser Reports (First Seen)](#11-linking-docs-to-jar-analyser-reports-first-seen)
12. [Roles & Permissions](#12-roles--permissions)
13. [API Reference](#13-api-reference)
14. [Rubbish & Recovery](#14-rubbish--recovery)

---

## 1. Overview

Docs is LabTool's own knowledge base — a Library → Shelf → Document hierarchy for writing, reading, and organising markdown content, with a full CodeMirror editor, highlighting/annotations, a relationship map, an alternate card-based reading view, and full-text search. Two other features built on top of it live in the same section: an **Error Knowledge Base** (searchable regex-pattern error entries, each an ordinary Doc) and a **Bug Tracker** (structured bug filing tied to specific JAR Analyser reports, with cross-report pattern detection).

Everything is stored and searched server-side (real SQL, not an in-browser index) — there is no separate storage backend to configure.

### Feature summary

| Feature | Where to find it |
|---------|-----------------|
| Browse libraries/shelves/documents | Docs → Libraries |
| Read a document (TOC, wiki-links, callouts) | Library → Shelf → open a document |
| Edit a document (CodeMirror, split preview, minimap) | Document → ✏️ Edit |
| Highlights & notes | Select text while reading (operator+) |
| Relationship map (wiki-links / shared headings / shared keywords) | Shelf list → 🗺 Map |
| Structured / Card view | Document → 🗂️ Structured toggle |
| Full-text search | `GET /docs/search` |
| Error Knowledge Base | Docs → 🔍 Error KB Search |
| Bug Tracker | Docs → 🐛 Bugs |
| Cross-navigation from JAR Analyser (Report Bug / N bugs / N docs first seen here) | JAR Analyser → any report or service view |
| First-seen report link on a document | Document reader → "First seen on" line (operator+) |

---

## 2. Libraries, Shelves & Documents

The hierarchy is **Library → Shelf → Document**. A Library is a top-level collection (e.g. "SSL Runbooks", "Bug Resolutions", one per Error KB category); each Library holds one or more Shelves; each Shelf holds Documents.

A Document is **versioned**: every save creates a brand-new row rather than overwriting in place (matching a "new version per save" model, not a diff-based one). The document you see when browsing a shelf is always the highest version for that shelf+name pair; older versions remain retrievable (`GET /docs/{id}/versions`) but aren't shown in listings.

**Version History** — click the `v{n} 🕐` label next to a document's title (top-right of the reader) to open its version history. Pick any two versions from the dropdowns to see a simple line-by-line diff (older on the left, newer on the right, regardless of which order you picked them in) — additions in green, removals in red. Documents with only one version show a note that there's nothing to compare yet.

Deleting a document moves every version of it to **Rubbish** rather than removing it outright — see [Section 14](#14-rubbish--recovery).

**Moving** — a "Move" link on a document or shelf row (operators and admins) repoints it onto a different shelf or library, in place, without losing anything: every version, annotation, and comment travels with it. A document can't move onto a shelf that already has a document with the same name (whether live or sitting in that shelf's Rubbish — the destination has to be free first). Shelves have no such restriction, since shelf names aren't required to be unique within a library.

**Bulk actions** — checkboxes appear on each document row (operators and admins) once a shelf has documents; select any number and a toolbar appears above the list with "Move selected" (same destination picker as a single move) and, for admins, "Delete selected" (moves them all to Rubbish). Each document in the batch is handled independently — a name conflict on one doesn't block the rest, and you're told how many succeeded versus failed.

---

## 3. Reading a Document

The reader renders full markdown (GFM tables, task lists, strikethrough, autolinks, syntax-highlighted code blocks, footnotes) plus LabTool-specific extensions:

- **Wiki-links** — `[[Document Name]]` or `[[Document Name|Custom Label]]` resolve to another doc by name (via search) and navigate without a full page reload.
- **Callouts** — `> [!NOTE]`, `[!TIP]`, `[!WARNING]`, `[!IMPORTANT]`, `[!CAUTION]`, `[!DANGER]` on the first line of a blockquote render as a labelled callout box (ℹ️ Note, 💡 Tip, ⚠️ Warning, ❗ Important, 🔶 Caution, 🚨 Danger).
- **Footnotes** — standard GFM syntax: `text needing a citation[^1]` with a matching `[^1]: the footnote text` anywhere else in the document. Renders as a numbered reference with a jump-to-definition link and a backlink from the definition, at the bottom of the document.
- **Mermaid diagrams (Improvements Plan Stage 15)** — a fenced code block written ` ```mermaid ` instead of a language name renders as an actual diagram (flowcharts, sequence diagrams, ER diagrams, and everything else Mermaid supports) instead of a syntax-highlighted code block. Invalid diagram syntax shows a clear error message with the raw source underneath rather than silently failing or breaking the rest of the page. Works identically in the editor's live split-view preview. Note: Mermaid's own `[[Subroutine]]`-style node-shape syntax inside a diagram is never mistaken for a `[[Wiki Link]]` — wiki-link/callout substitution is skipped entirely inside any fenced code block.

Also present: a table-of-contents sidebar built from the actual rendered headings with scroll-spy (the current section highlights as you scroll); click any heading in the document body to collapse everything under it until the next heading of equal-or-shallower level; a reading-progress bar; a word count and estimated reading time; and breadcrumbs (Library / Shelf / Document name) linking back to the shelf.

A **Document / Structured** toggle in the top-right switches to the [card view](#7-structured--card-view) — **Structured is now the default** when opening any document; switch to Document view for the full markdown reading experience described above (Structured falls back to Document automatically if a doc doesn't have enough heading structure to build cards from).

**Export (Improvements Plan Stage 17)** — two buttons next to the Document/Structured toggle:
- **⬇ PDF** downloads the current version as a formatted PDF (title, library/shelf/version/updated-at header, then the rendered content — tables, code blocks, and blockquotes all keep their styling). Wiki-links render as plain bold text rather than clickable links (a static PDF has nowhere for them to navigate to) and callouts render as their labelled blockquote. **Mermaid diagrams are not rendered** — PDF generation runs with no browser or JavaScript engine, so a mermaid code block shows its raw diagram source as plain text instead of the rendered diagram; view it in the normal reader (or Structured view) for the actual diagram.
- **⬇ MD** downloads the exact raw markdown as stored — no wiki-link/callout conversion, no HTML stripping, byte-for-byte what was authored. Meant for portability/backup (re-importing elsewhere, keeping a copy in git) rather than a rendered view; use PDF for that instead.

Both are available to every role that can read the document (same as viewing it) — export doesn't require edit access.

---

## 4. Editing a Document

The editor is CodeMirror 6-based (line numbers, fold gutter, bracket/quote autoclose, active-line highlight, full undo/redo history) with:

- A toolbar: **Bold**, *Italic*, Heading, Link, Bulleted list, Inline code, Code block, Table (inserts a 2-column skeleton), Undo, Redo, Find & Replace (opens CodeMirror's built-in search panel).
- A **Split** toggle showing a live-rendered preview (the same renderer used by the reader) alongside the raw markdown.
- A **minimap** — a compact canvas overview of the whole document (headings in blue, code in green, bullets in amber, tables in purple, body text in gray) with a draggable viewport indicator; click anywhere on it to jump to that line.
- Autosave every 30 seconds while there are unsaved changes, a browser warning before navigating away with unsaved changes, and Ctrl/Cmd+S to save immediately.

Saving always creates a new version (see [Section 2](#2-libraries-shelves--documents)) — there is no in-place overwrite of document content. (The document's [first-seen report link](#11-linking-docs-to-jar-analyser-reports-first-seen) is the one exception: that's metadata, not content, and is updated in place without bumping the version.)

---

## 5. Annotations & Highlights

Operators and admins can select any text while reading a document to open a floating colour picker (5 fixed colours: yellow, green, blue, pink, orange) and create a highlight. Clicking an existing highlight opens a popover to change its colour, add or edit a note (shown as the highlight's tooltip), or delete it (admin-only).

Highlights are anchored to the *rendered* text, not raw markdown positions, and are re-located on every page load by matching the highlighted text plus a little surrounding context — this keeps highlights correctly placed even if unrelated parts of the document change. If a highlight's exact text can't be found and placed, it no longer disappears without a trace: an amber notice ("N highlights from an earlier version of this document couldn't be placed on this version") appears above the document, dismissible per-count so it reappears if further highlights later fail too.

Highlights carry forward automatically when a document is edited and saved — each save copies every highlight from the previous version onto the new one (original note/colour/created-by/created-date preserved), so editing a document doesn't reset its highlights to zero. If the edit removed the exact text a highlight was on, the carried-forward highlight will show up in the re-anchor notice above rather than being silently lost.

---

## 6. Map View

Reached from a Library's shelf list (🗺 Map), the map view renders every current document in that library as a node in a force-directed graph, with edges computed server-side from:

- **Wiki-links** — a real `[[reference]]` from one doc to another.
- **Shared headings** — two docs that both have a heading with the same text.
- **Shared keywords** — two docs that share three or more significant words (6+ letters, appearing more than once, past a small stopword list).

Each edge type has its own colour and an individual show/hide filter; a text box filters nodes by name (non-matches dim rather than disappear); node size scales with the document's word count. Supports drag, pan, zoom (mouse wheel), a Fit-to-View button, and an Export PNG button.

**Manual layout persistence (Improvements Plan Stage 14):** dragging a node now pins it in place — clicking it without moving still opens the document as before, but a real drag keeps it fixed instead of springing back into the simulation. Nothing is saved automatically; click **Save Layout** to persist every pinned node's position for next time, or **Reset Layout** to unpin everything and let the simulation re-arrange freely again (also clears the saved layout). Undragged nodes keep auto-arranging around whatever's pinned. Only a single library's own map can save a layout — there's no library row to save one onto for the view below.

**🗺️ All Libraries Map**, on the Docs home screen, is the same relationship graph computed across every library's current documents at once instead of just one — this is the only place a wiki-link between two documents in *different* libraries (e.g. an Error KB doc linking into a Bug Resolutions doc) actually shows up as an edge, since a single library's own map only ever sees that library's own documents. No manual layout persistence here (nodes still drag for the current session, just not saved) — this is an exploration view across the whole corpus, not one library's own map.

---

## 7. Structured / Card View

**The default view when opening any document.** An alternate reading mode that reinterprets a document's heading structure as tiers of cards: each `##` heading becomes a colour-coded tier; each `###` heading under it becomes a card (a `##` with no `###` children becomes one card itself). A card's body is auto-shaped from its content — a paragraph becomes a summary, bullet/task lists become a checklist, tables become pills, code blocks become a snippet, and callouts become a footnote. Each card also gets a category badge guessed from its heading text (Data, Auth, Deploy, Test, and roughly twenty other categories) — the keyword→category mapping is admin-editable under Settings → **Structured View Categories** (Improvements Plan Stage 13): add, edit, delete, or reorder rules (a rule is a regex pattern matched case-insensitively against the heading; first match wins, checked top to bottom), with no code change needed. A heading matching nothing falls back to a generic "Section" badge. Wiki-links (`[[Document Name]]`, as used in KB "See Also" lists) work here too — they render as clickable links in card bodies, bullet lists, and the detail panel, same as in Document view.

Click a card to open a detail panel; use the filter box to narrow by text; use a tier's "Highlight section" control to dim everything outside it; tiers are individually collapsible; full keyboard navigation (arrows/Home/End/Enter/Escape) is supported. Documents with too little heading structure to produce more than one card fall back to Document view automatically, with a one-click switch back to Structured if more structure is later added.

---

## 8. Search

**🔎 Search Docs**, on the Docs home screen, is real full-text search: a ranked list of documents with a highlighted excerpt showing why each one matched — click a result to open it. Under the hood (Improvements Plan Stage 11), `GET /docs/search` uses SQLite's FTS5 extension for tokenised, relevance-ranked matching against document name and content (the latest version of each document only), a real upgrade over the plain substring `ILIKE` matching it replaced. Words are prefix-matched and ANDed together, so `cert renew` finds documents containing both a word starting "cert" and a word starting "renew," not necessarily as an exact phrase — a small trade-off against the old behaviour's "matches any substring anywhere," made in exchange for actual relevance ranking. (On a non-SQLite deployment, the endpoint transparently falls back to the old ILIKE matching — no ranking or snippet, but the same results in name/updated-date order.)

It also accepts `first_seen_report_id`/`first_seen_sub_report_id` instead of (or in combination with) a text query, which is how the [report-side "N docs first seen here" badge](#11-linking-docs-to-jar-analyser-reports-first-seen) and its results list are served — at least one of `q`, `first_seen_report_id`, or `first_seen_sub_report_id` is required.

---

## 9. Error Knowledge Base

Reached via Docs → 🔍 Error KB Search. Each KB entry is an ordinary Doc — organised one Library per error category (Keystone, RabbitMQ, SSL/TLS, ...) — whose content encodes a regex match pattern and severity as two parseable lines at the top, followed by normal markdown (plain-English explanation, Likely Causes, Fix Steps, and a See Also section that can wiki-link to related entries). A doc with no `**Pattern:**` line is just a normal document and is invisible to KB search.

Four tabs:

- **Search** has two modes, switched with the pills at the top:
  - **📋 Paste Error Text** — paste a stack trace or error message; it's tested against every KB entry's regex pattern (an exact-signature match, not a keyword search). If nothing matches, it automatically falls back to a topic search on the same text and shows anything related under an amber "no exact pattern match, but…" notice, rather than leaving you at a dead end.
  - **🔎 Browse by Topic** — real keyword search across KB entry titles and content (Improvements Plan Stage 11 follow-up), for when you want to browse by subject ("keystone certificate") rather than paste an exact error. Ranked and snippeted the same way as [Search Docs](#8-search) when running on SQLite — KB entries are ordinary Docs, so this reuses the same index — with a plain substring fallback on other database backends. A row of topic pick-list chips sits above the keyword box, one per KB category with an entry count, multi-select — click one or more to browse every entry in those categories directly, with or without also typing a keyword; selecting a category narrows a keyword search to just that category, and clicking with no keyword at all lists everything in it. "Clear topics" resets the selection.
- **🧵 Decode** — paste a full log excerpt or stack trace (including any `Caused by:`/`Suppressed:` chain) and it's parsed into its actual exception structure (`app/services/stack_trace_parser.py`) rather than treated as one flat blob:
  - Each exception in the chain is matched against the KB **independently**, so a wrapped root cause's own text isn't diluted by the outer wrapper exception's text — the same reasoning behind the root-cause logic Diagnose now shares (below).
  - The **deepest** exception in each independent incident's chain (a single paste can contain more than one unrelated incident) is flagged **🎯 Likely root cause** — Java wraps and rethrows as an error propagates up the call stack, so the outermost/first-seen exception is usually just packaging, never `Suppressed:` exceptions (a sibling branch, not the causal chain).
  - Every stack frame is checked against every class this tool has ever scanned from an analysed jar upload (`JarStringConstant`, tenant-wide, not scoped to one report) — a recognised frame shows a **📍 service name** badge that deep-links straight into that service in the JAR Analyser, landing on the Source tab when the class has also been decompiled (Section 36 of the JAR Analyser guide).
  - Frames are split into your own application code (shown by default) and JDK/framework/proxy plumbing (Spring, Tomcat, CGLIB, reflection, etc. — collapsed behind a "Show N framework frames" toggle), so a 100+ frame trace doesn't bury the handful of frames actually worth reading.
- **🔬 Diagnose** — pick a real JAR Analyser report and paste an error; unlike Decode (which searches every analysed upload), this stays scoped to the one report you picked, since the point of Diagnose is "what does this mean for *this* report specifically." Under the hood it now shares Decode's own exception-chain parsing: the KB search runs against each root-cause exception's own class+message rather than the whole raw paste, and a trace's own frames are correlated against *this report's own services* (not every service in the report indiscriminately) whenever a frame names a class this tool recognises — narrowing `context_findings` down to the actual service involved instead of every service's matching config key. A pasted snippet with no real stack frames (most short/manually-typed error descriptions) can't correlate anything and falls back to searching the whole report, exactly as before. Each result also carries a **🐛 Create Bug** button — opens Bug Tracker's New Bug form prefilled with the exception class/message, the KB entry's severity, the matched config findings (as "Relevant config"), the KB category as a tag, and a link to the report (plus the specific service, when every finding agrees on one) — the raw pasted text goes into Logs/stack traces so nothing has to be retyped.
- **📊 Usage** (Improvements Plan Stage 16) — every KB entry ranked by how often it's actually matched real error text, most/least-matched toggle, with a "N matches · last matched \<date\>" badge (or a grey "0 matches" badge for entries that have never fired). Three entry points count as a real "match" for this tracking: a **Paste Error Text** search (pattern mode), a **Decode** run, and a **Diagnose** run — a Browse by Topic keyword search does not count, since it's a browse, not a signature match. An entry sitting at 0 matches for a long time is a genuine signal that its pattern may be too narrow, mistitled, or simply describes an error nobody has hit yet — worth reviewing periodically.

This is a runtime match, not a persisted link — the same KB entry can match many reports, and nothing about a match is saved *against the report*. (Contrast with [Section 11](#11-linking-docs-to-jar-analyser-reports-first-seen), which *is* a persisted, single-origin link on an ordinary doc.) The Usage tab's match counters are the one exception — they persist, but only as an aggregate count per KB entry, not a record of which reports triggered them.

### Ansible / Build Manager integration

The same pattern-matching engine also runs against Build Manager job failures — a genuinely different signal source from JAR Analyser reports, matched with the exact same mechanism rather than a second, parallel lookup table. A failed job's own `fatal:`/`FAILED!` output lines, failed hosts, and playbook are matched against every KB entry's regex, exactly like a Paste Error Text search:

- **In the "Report Bug" form** — opening the New Bug form from a job (see [Section 10's Build Manager origin](#10-bug-tracker)) shows a "📖 Error KB matches" panel under the Ansible Output field, once the failure text matches anything. This is a real, user-facing lookup, so it counts toward the Usage tab the same as a Paste Error Text search or a JAR Analyser Diagnose run.
- **In auto-filed bugs (Stage 22)** — if the opt-in auto-filer creates a new bug, any KB matches for that job's failure are appended to the description as a short "Error KB matches" list (title + first fix step). This does *not* count toward Usage — the auto-filer is an unattended background scanner, the same category of caller Stage 16 already excludes from usage tracking for exactly this reason (see the caveat in the bullet list above).
- Like every KB search in this app, matching is deliberately loose (regex first, then a keyword-overlap fallback) — a real result can include a plausible-but-wrong match alongside the right one. Treat every match as "worth checking," not a diagnosis.

**Adding a new Ansible failure entry** works exactly like any other KB entry — there's no separate table or file to maintain, no code change, and no fixed shelf/library requirement (a doc anywhere is eligible; the code just organises the existing ones under an "Ansible" library / "Errors" shelf by convention). To add one:

1. In Docs, create (or reuse) a Library for the category — "Ansible" already exists for general playbook/connectivity failures; a product-specific failure might fit better under that product's own KB library if one exists.
2. Add a new Doc under that library's "Errors" shelf (any shelf works; "Errors" is just the existing convention), with content in this exact shape:

   ```
   **Severity:** high
   **Pattern:** `regex matching the real failure text|another alternative`

   Plain-English explanation of what actually went wrong.

   ## Likely Causes

   - cause one
   - cause two

   ## Fix Steps

   1. first thing to check
   2. second thing to try

   ## See Also

   - [[Another KB Doc Title]]
   ```

3. `**Severity:**` and `` **Pattern:** ` ` `` must each be on their own line exactly as shown (severity is a single word; pattern is a regex in backticks, case-insensitively matched against the job's own failure text) — everything else is normal markdown. A doc with no `**Pattern:**` line is simply not a KB entry.
4. Base the pattern on real failure text where possible (copy the actual `fatal:`/`FAILED!` line from a real job's Ansible Output rather than guessing the wording) — a pattern that's too broad will surface as noisy false-positive matches on unrelated failures, same trade-off as any other KB entry.
5. No rebuild, migration, or restart needed — a new KB doc is picked up by the next `/diagnose` call or auto-filed bug immediately, the same as any other Docs edit.

---

## 10. Bug Tracker

Reached via Docs → 🐛 Bugs (also nested here rather than as its own top-level section, to keep the mode switcher from growing indefinitely). A bug has a structured intake form (severity, frequency, scope, environment, repro steps, expected/actual behaviour, logs, infra-specific fields like Terraform diffs and TLS/network details), a status workflow (open → investigating → resolved/closed/wont-fix) with a full timeline, threaded comments, and an optional link to *either* a specific JAR Analyser report/service *or* a Build Manager job it was filed against (Improvements Plan Stage 19) — never both on the same bug.

**The Dashboard is the landing view** — opening Bugs shows metrics first, with a Dashboard/List switcher in the header (and a "+ New Bug" button next to it, for operators) to get to the full list or file something new. The two cross-navigation entry points below skip straight past the dashboard to the view they're actually asking for.

- **Filing from a report** — every report and service view in JAR Analyser has a "🐛 Report Bug" button (pre-fills the report/service link) and, once any bugs exist for it, a "🐛 N bugs" badge linking to a pre-filtered list.
- **Cross-report pattern detection** — a bug's detail page has a "Seen in N reports" section: besides the report it was originally filed against, an operator can mark it as "Also seen on this report" for any other report/service, and the report-side badge counts both. Filing a new bug also runs a live duplicate-suggestion check against existing bugs, offering to link the current report as another sighting instead of creating a duplicate — on SQLite, this is real FTS5-ranked matching (Improvements Plan Stage 11), the same engine backing the List view's search box; on other database backends it falls back to a simple keyword-overlap score (no AI either way).
- **Duplicate linking** — the duplicate-suggestion check above covers "this same bug turned up on another report/job"; it doesn't cover two people each independently filing their *own* bug for the same underlying issue, since neither filer saw the other's report at the time. A bug's detail page has a "🔗 Mark as duplicate" button (operators+) that opens a search-and-pick panel over existing bugs (same FTS5/keyword search as everywhere else); picking a target marks the current bug as a duplicate of it. This doesn't delete or field-merge the two bugs — the duplicate keeps its own comments/history/attachments exactly as they were — it auto-closes the duplicate (unless it was already resolved or wont-fix), moves its occurrences (and its own primary report/job origin, as a new occurrence) onto the target so the target's "Seen in N places" reflects the combined footprint, and shows an amber banner on the duplicate linking to the target. Picking a target that's itself already a duplicate resolves to *its* target automatically, so links never chain more than one hop. Admins can "Unmark" to undo the link itself (the status change and moved occurrences aren't reverted — same "undo stops treating it as linked, it doesn't rewind history" shape as unlinking an occurrence).
- **Automated related-bug scan** — every JAR Analyser report also gets scanned automatically, right after analysis finishes, against the corpus of open bugs (Improvements Plan Stage 12) — no need to go file a new bug to discover a match. A "🐛 N Related Bugs" panel appears on the report view when anything looks related, using the same ranking as the duplicate-suggestion check above but scored against what the analysis actually found (consistency findings, actuator exposure risks, errors/warnings, purpose narratives) rather than a bug's own title/description. Click a related bug to jump straight to it. This is a "worth checking" signal, not a confirmed match — it's deliberately loose (any shared word counts), so it can surface false positives on generic finding language as well as real matches. Runs best-effort: a scan failure never fails the analysis itself, and a report analysed before this feature existed simply has no panel until it's re-analysed. **Build Manager jobs get the identical treatment (Improvements Plan Stage 21)**: a job that finishes failed (and isn't about to be auto-retried) is scanned against its own `fatal:`/`FAILED!` output lines and failed hosts, surfacing an amber "🐛 Related Bugs" strip on the job's terminal view — same ranking, same "worth checking, not confirmed" caveat, same best-effort guarantee.
- **Automatic bug filing on Ansible failure (Improvements Plan Stage 22, opt-in, off by default)** — a Settings page toggle ("Automatic Bug Filing") goes one step further than the scan above: if a failed Build Manager job's scan finds nothing close enough, a new bug is filed automatically instead of just leaving it in the job log for someone to notice. If the scan *does* find a match, that's treated as a recurrence — a `BugOccurrence` is added to the existing bug rather than filing a duplicate, so one flaky failure that keeps happening doesn't spawn a fresh bug every run. Auto-filed bugs are reported by "Automated (Ansible failure scan)" (never a real user) and carry an `auto_created` flag, shown in Bug Tracker as a "🤖 Auto-filed" badge in both the list and the bug's own header, and filterable via the API (`auto_created=true`). Runs at the same "outcome is final, not a dry run" point in the job pipeline as the scan itself, and is equally best-effort — a failure here is logged and never blocks the job. Today's failure data is thin (hostnames + exit code from a regex over raw output), so the *first* auto-filed bug for a brand-new failure pattern will often still need someone to open the job log to see what actually broke — this beats the failure being invisible, but it's not a root-cause summary. Deliberately scoped to Build Manager/Ansible only for v1.
- **Auto-filed, awaiting triage** — since nobody chose to file an auto-filed bug, a still-open one is easy to miss among manually-filed bugs. The Dashboard has a dedicated "🤖 Auto-filed, awaiting triage" stat card (count of bugs with `auto_created=true` and `status=open` — an auto-filed bug that's already investigating, resolved, closed, or wont-fix no longer counts, since someone has acted on it) that jumps straight to the List view pre-filtered to exactly that set. The List view also has its own "🤖 Auto-filed only" toggle for filtering to auto-created bugs regardless of status, independent of the Dashboard shortcut.
- **Editing a bug** — a bug's detail page has an "✏️ Edit" toggle (operators+, next to the severity/tags row) for changing the title, description, severity, or frequency picked when it was originally filed. Status, assignee, resolution, and tags each already had their own inline edit affordance (the status dropdown, assignee dropdown, resolution textarea, and bulk tag actions from the List view) — this covers the four fields that previously had none, using the same `PATCH /bugs/{id}` the API already supported for them.
- **Assignment** — a bug can be assigned to a real LabTool account (a dropdown of active users, not free text — set from the "New Bug" form or changed any time from a bug's detail page). The Dashboard shows a "My Open Bugs" count, and the list view has a "🙋 My Bugs" toggle that filters to bugs assigned to whoever's logged in.
- **Dashboard** — status/severity breakdowns, average time-to-resolution, "top affected reports", and "My Open Bugs" (open + investigating bugs assigned to you).
- **Export** — the current filtered bug list can be exported as markdown (⬇ Export button, from the List view) — respects the "My Bugs" filter too.
- **Save to Docs** — once a bug has a resolution written, "📄 Save to Docs" writes it into a shared "Bug Resolutions" library/shelf as an ordinary, searchable Doc (re-saving updates that same doc with a new version rather than duplicating it). The new doc's [first-seen link](#11-linking-docs-to-jar-analyser-reports-first-seen) is set automatically from the bug's own report/service — no need to set it by hand unless you want it to point somewhere else.
- **Promote to KB** — next to "Save to Docs", a resolved bug with a written resolution also gets a "📖 Promote to KB" button, for the case where a fix is genuinely reusable rather than one-off. It jumps straight to the [Error Knowledge Base](#9-error-knowledge-base)'s New Entry tab with Title, Severity, and Plain-English Description prefilled from the bug (from its resolution text), Pattern prefilled with a regex-escaped copy of the bug's own `fatal:`/`FAILED!` line if the description has one (still worth checking against the real failure text before saving — auto-escaping doesn't guarantee a well-scoped pattern), and the category defaulted to the existing "Ansible" library when the bug was filed against a Build Manager job. Nothing is saved until "Create Entry" is pressed — same review-before-save flow as filling the form out by hand.
- **Attachments (Improvements Plan Stage 18)** — a bug's detail page has an Attachments card (above Comments) for screenshots, logs, or any other file, up to 25 MB each, rather than pasting everything as text. Operators+ can upload (a plain file picker, no drag-and-drop); every role that can view the bug can download; only admins can delete an attachment. Uploading logs a timeline entry the same way a comment does. Deleting a bug moves it to Rubbish as usual — attached files aren't touched until the bug is actually purged (by hand or by the 30-day retention sweep), at which point they're removed from disk along with everything else.
- **Build Manager origin (Improvements Plan Stages 19–20)** — a bug can be filed against a Build Manager job, not just a JAR Analyser report/service: a job's own terminal view (Build Manager → Jobs → select a job) has the same "🐛 Report Bug" button and "🐛 N bugs" badge JAR Analyser reports already have, pre-filling the job link, Title, Actual Behaviour, and Ansible Output (playbook, failed hosts, exit code, and the run's own `fatal:`/`FAILED!` lines) so filing doesn't mean re-typing context the system already has. A recognised exit code also gets a short "(commonly: ...)" hint (e.g. exit code 4 usually means an unreachable host on current Ansible, though older docs call it a parser error) — a pointer to check first, not a diagnosis, since ansible-playbook's own exit codes are inconsistently documented across versions. The Stage 22 auto-filer's description gets the same exit-code hint. If the job belongs to an environment, the form also pre-fills OS/distro, per-host product versions, IP allocations, and issued certs into the Environment/TLS/Network fields, plus a per-host role breakdown into Relevant config. This works even after the environment itself has since been destroyed (routine for test/build workflows) — every job that ran against an environment captures a snapshot of that build context (`build_snapshot_json`) at the moment it's submitted, since `destroy_environment()` hard-deletes the environment row and only detaches the job's `environment_id`, not preserves the environment's own data. The prefill uses that snapshot when present, falling back to a live environment lookup for jobs submitted before this snapshot existed; the Relevant config line notes "[from build snapshot - environment may since have been destroyed]" when it came from the snapshot rather than a live environment. All pre-filled fields stay fully editable before saving, and a job with no environment link at all (a plan-only or TLS-verify job, or one that predates both the snapshot and a still-live environment) simply leaves those blank rather than guessing. A bug's "Seen in N places" section on its detail page shows a 🏗️ job badge instead of a report link when it's job-scoped. A bug is linked to a report *or* a job, never both — the API rejects setting both at once, and the New Bug form only shows a report/service picker when it *wasn't* opened from a job (a job-origin bug shows its job link as a fixed line instead). There's no manual job picker yet — "Also seen on another report" (linking an *existing* bug to an *additional* origin) is still report-only; linking an additional job as an occurrence is API-only for now.
- **Deleting a bug** doesn't remove it immediately — it moves to Rubbish, recoverable by an admin for 30 days. See [Section 14](#14-rubbish--recovery).
- **Bulk actions** — checkboxes appear on each row in the List view (operators and admins); select any number to reveal a toolbar for setting a status on all of them at once, or adding/removing a tag across all of them at once. Each bug is handled independently, so one already at the target status (or missing the tag) doesn't stop the rest.
- **Activity badge** — a 🔔 badge next to the "🐛 Bugs" heading shows how many updates (status changes, comments, occurrence links) have happened on bugs you're assigned to or reported since you last opened the tracker, excluding your own actions. It clears automatically the moment you land on the Dashboard.
- **Email alerts** — if you'd rather get emailed than watch the badge, subscribe under Notifications → My Preferences to "Bug assigned to you", "Bug status changed", and "Bug occurrence linked". These are scoped to your own username automatically, so you'll only be emailed about bugs assigned to you or that you reported — not every bug in the system. Requires an administrator to have SMTP configured (Notifications → SMTP Settings); if it isn't, the badge above still works with no setup needed.

---

## 11. Linking Docs to JAR Analyser Reports (First Seen)

Any document — not just a bug or a KB entry — can optionally record the report (and, if known, the specific service) where the issue behind it was **first seen**. This is a single origin link, not the Bug Tracker's multi-report occurrence tracking: it answers "where did the story behind this doc begin," not "which reports has this recurred on."

Set it either while creating a document or retroactively at any time from the reader (the "First seen on" line — click "+ Set first seen report" if unset, or "Change"/"Clear" if already set). It's metadata, not content: setting or clearing it does **not** create a new document version, and it carries forward automatically onto the next version whenever the document is actually edited and saved.

Every report and service view in JAR Analyser shows a "📄 N docs first seen here" badge once any documents are linked to it, opening a filtered results list.

---

## 12. Roles & Permissions

Docs, the Error Knowledge Base, and the Bug Tracker all share the same three-tier model:

| Role | Can do |
|------|--------|
| **admin** | Full CRUD, including delete (libraries, shelves, documents, annotations, bugs, comments, occurrences) |
| **operator** | Create, read, update — everything except delete |
| **auditor / readonly** | Read-only |

---

## 13. API Reference

All under `/api/v1/`.

| Endpoint | Purpose |
|---|---|
| `GET/POST /docs/libraries`, `DELETE /docs/libraries/{id}` | Library CRUD |
| `GET /docs/libraries/{id}/shelves` | List shelves in a library |
| `GET /docs/libraries/{id}/map` | Relationship graph data for the Map view, including any saved manual layout |
| `PUT /docs/libraries/{id}/map/layout` | Save (or, with an empty body, reset) a library's manually-dragged Map View node positions |
| `GET /docs/map` | Relationship graph across every library at once — the "All Libraries Map" |
| `POST /docs/shelves`, `DELETE /docs/shelves/{id}` | Shelf CRUD |
| `GET /docs/shelves/{id}/docs` | List documents on a shelf (latest version only) |
| `GET /docs/search` | Full-text search, or first-seen reverse lookup |
| `GET /docs/error-kb/search?mode=pattern\|topic` | Error Knowledge Base search — regex-pattern match or topic keyword search |
| `POST /docs/error-kb/decode` | Decode tab — parses pasted text into its exception chain, matches each exception against the KB independently, cross-references every frame against every analysed service |
| `GET /docs/error-kb/categories` | Distinct KB categories with entry counts — powers Browse by Topic's pick-list |
| `GET /docs/error-kb/usage` | Match-count usage stats for every KB entry, most-matched first |
| `GET /docs/{id}`, `GET /docs/{id}/versions` | Fetch a document / its version history |
| `GET /docs/{id}/diff?against={id}` | Line-based diff between two versions |
| `GET /docs/{id}/export/pdf` | Download the current version as a formatted PDF |
| `GET /docs/{id}/export/markdown` | Download the current version's raw markdown, exactly as stored |
| `POST /docs`, `POST /docs/{id}/save` | Create a document / save a new version |
| `PATCH /docs/{id}/first-seen` | Set or clear the first-seen report link (in place, no new version) |
| `POST /docs/{id}/move` | Move a document (all versions) onto a different shelf |
| `POST /docs/shelves/{id}/move` | Move a shelf onto a different library |
| `POST /docs/bulk-move`, `POST /docs/bulk-delete` | Move / Rubbish multiple documents at once (per-item results) |
| `DELETE /docs/{id}` | Move a document (all versions) to Rubbish |
| `GET /docs/trash`, `POST /docs/{id}/restore`, `DELETE /docs/trash/{id}` | List Rubbish / restore / permanently purge a document |
| `GET/POST /docs/{id}/annotations`, `PATCH/DELETE /docs/annotations/{id}` | Annotation CRUD |
| `GET /bugs`, `GET /bugs/search`, `GET /bugs/similar` | Bug list / full-text search / duplicate suggestions |
| `POST /bugs/bulk/status`, `POST /bugs/bulk/tag` | Bulk status change / tag add-remove across multiple bugs (per-item results) |
| `GET /bugs/dashboard`, `GET /bugs/export` | Dashboard metrics / markdown export |
| `POST /bugs`, `GET/PATCH/DELETE /bugs/{id}` | Bug CRUD — DELETE moves it to Rubbish |
| `GET /bugs/trash`, `POST /bugs/{id}/restore`, `DELETE /bugs/trash/{id}` | List Rubbish / restore / permanently purge a bug |
| `PATCH /bugs/{id}/status` | Status transition |
| `POST /bugs/{id}/comments`, `DELETE /bugs/{id}/comments/{id}` | Comment CRUD |
| `POST /bugs/{id}/occurrences`, `DELETE /bugs/{id}/occurrences/{id}` | Link/unlink an additional report sighting |
| `POST /bugs/{id}/save-to-docs` | Save a resolved bug's write-up into Docs |
| `POST /bugs/{id}/attachments`, `GET /bugs/{id}/attachments/{id}/download`, `DELETE /bugs/{id}/attachments/{id}` | Attachment upload / download / delete (25 MB max) |
| `GET/POST /category-rules`, `PATCH/DELETE /category-rules/{id}` | Structured View category rule CRUD — write ops are admin-only |

---

## 14. Rubbish & Recovery

Deleting a document or a bug doesn't remove it immediately — it moves to **Rubbish**, recoverable for **30 days** before it's purged automatically. This applies to Documents (all versions of the document move together) and Bugs; Libraries and Shelves are still deleted immediately and permanently, since deleting one of those is a deliberate structural action, not the kind of single-item accidental click Rubbish is meant to protect against.

**Where to find it** — from the Docs home screen (the library list), click **🗑️ Rubbish**. Admin-only, same as the delete action itself. It has two tabs, Documents and Bugs, each listing what's currently deleted, when, and by whom (where known).

- **Restore** puts the item back exactly as it was. For a document, this restores every version, not just the latest — the whole thing comes back. If a new, unrelated document has since taken the same name on the same shelf, restore is blocked (409) until that name is freed up or the restore target is purged instead.
- **Purge** permanently and immediately deletes the item — this is the "empty rubbish" action for a single entry, and cannot be undone.
- Items nobody purges by hand are removed automatically by a background sweep once they've been in Rubbish for 30 days.

Items in Rubbish don't appear anywhere else — not in shelf listings, search results, the Map view, the Error Knowledge Base, or Bug dashboard/list/export — until they're restored.
