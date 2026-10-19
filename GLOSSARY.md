# Mirko

Language for tracking 3GPP SA3 contributions during a meeting. It distinguishes the
official record (TDocs, agendas, decisions) from the ephemeral working material that
exists only for the duration of the meeting.

## Documents and lineage

**TDoc**:
A numbered 3GPP contribution (`S3-26XXXX`). The stable unit of the official record.
_Avoid_: Doc, document, paper

**Contribution**:
A TDoc together with what it is for (CR, pCR, discussion, LS, etc.). In Mirko it is
the same identity as the TDoc.
_Avoid_: Submission, input

**Initial TDoc**:
The first official TDoc number a contribution had before any revision.

**Revised TDoc**:
A new TDoc number produced by revising an earlier TDoc. An official revision always
gets a new number; it is never the same number with an `rN` suffix.
_Avoid_: New version, r1

**Revision**:
The official relationship in which one TDoc replaces another with a new number.
_Avoid_: Update, edit, new draft

**Merge**:
The official relationship in which several TDocs are combined into one new TDoc.

**Baseline**:
The one source TDoc of a merge that continues as the basis of the merged result. It
is marked `revised`; the other sources are marked `merged`.

**Merged source**:
A non-baseline TDoc that was combined into a merged TDoc.

**Replaces**:
The TDoc this one is based on. For a merge this names only the baseline.

**Replaced-by**:
The TDoc that replaced this one. For a merge, every source points to the merged
result, which is how merges are discovered.

**Lineage**:
The official ancestry of TDocs through revisions and merges.
_Avoid_: History, tree, family

**Lane**:
One TDoc's place in the lineage view, drawn as a continuous track. A lane is a TDoc,
not a file.

**Based-on**:
A weak lineage relationship inferred when only `Replaces` is available and the
counterpart is not confirmed.

## Working material

**Working Draft**:
A revision of a TDoc produced during the meeting and stored in `Drafts/`, named with
`-rN`. It is not a new official TDoc and is discarded after the meeting.
_Avoid_: Revision, version, draft TDoc

**Final Submission**:
The ZIP uploaded to `Inbox/` when a contribution is agreed or approved.
_Avoid_: Final TDoc, upload, zip

**Artifact**:
Any concrete file Mirko has seen: an initial document, a working draft, a final
submission, an agenda file, an Excel sheet, or an email.
_Avoid_: File, attachment

**Observation**:
A record that an artifact existed at a path, with a given size and modification
time, at a given moment. Observations are immutable.

**Ephemeral**:
Describes a working draft that exists only during the meeting and is expected to
disappear from the server afterward.

## Meeting record

**Agenda Item**:
The numbered section of the meeting agenda to which TDocs are allocated, e.g. `5.3.1.13`.
_Avoid_: Topic, section, slot

**Topic**:
The descriptive title of an agenda item.

**TDoc Allocation**:
The official assignment of TDocs to agenda items in the agenda/allocation table.

**Decision**:
The official state of a TDoc as recorded in the agenda/allocation table: `open`,
`withdrawn`, `revised`, `merged`, `approved`, `agreed`, `endorsed`,
`email approval`, `postponed`, `noted`, `not pursued`, `replied to`, `not treated`.
_Avoid_: Status, result

**Open**:
The only transient Decision: the TDoc has not reached a final outcome.

**Not treated**:
A Decision meaning the TDoc was not opened for discussion because of time.

**Replied to**:
A Decision applied to a received Liaison Statement that SA3 has answered.

**For**:
What a TDoc is being presented for: `Approval`, `Agreement`, `Discussion`,
`Endorsement`, `Decision`, or `Information`.

**Available (Avail)**:
Whether the document is present in `Inbox/`.

**Treated**:
Whether the document was at least opened in the meeting. Free-text minutes may be
attached to this field.

**Withdrawn (Wdrn)**:
A legacy boolean duplicating the `withdrawn` Decision. Mirko ignores it.

**Plenary**:
The full-group meeting session where TDoc decisions are taken.

**LS in / LS out**:
A Liaison Statement received by SA3 / sent by SA3.

**CR / pCR**:
A Change Request / a proposed Change Request.

**SID / WID**:
Study Item Description / Work Item Description.

**WI**:
Work Item.

**Release**:
The 3GPP release a document belongs to (e.g. Rel-19).

## Mirko concepts

**Tracked Set**:
The user-selected TDocs whose lineage Mirko actively follows. It is dynamic and
lives in the meeting state, not in the configuration file.

**Provisional TDoc**:
A TDoc the user has recorded before the official agenda confirms it, typically after
a verbal number assignment. It is marked unconfirmed until the agenda agrees.

**Hint**:
A speculative relationship suggested by a filename or an email. Hints are never
authoritative and are shown as ghost links until confirmed.

**Assertion**:
A dated claim about a relationship or state, with a source and a confidence. Every
statement from the agenda, the user, a filename, or an email is an assertion.

**Provenance**:
The record of where a fact or artifact came from (agenda, Excel, user, filename,
email, or a specific endpoint).

**Conflict**:
A disagreement between assertions about the same fact, most commonly a user link
versus the agenda.

**Branch**:
One of the competing outcomes of a conflict. The active branch is shown normally;
the obsolete branch is muted but retained.

**Muted**:
Describes an obsolete branch that remains inspectable but no longer contributes to
the current view.

**Discovery**:
The place where unattached but relevant signals appear, such as new TDoc numbers or
emails matching a tracked agenda item.

**Annotation**:
A user note attached to a TDoc or artifact.

**Position Tag**:
The classification of an annotation: `Support`, `Object`, or `Clarify`.

**Meeting Folder**:
The portable directory holding everything for one meeting. Moving it moves all of
Mirko's state.

**Endpoint**:
The single configured FTP/HTTPS server that Mirko polls for one meeting.

**Single-download policy**:
The rule that each distinct remote file content is fetched once and then served
from the local cache.

**Finalize**:
The act of freezing a meeting folder's record after the meeting, recomputing final
states and producing the export, while still allowing annotation.

## 3GPP bodies and roles

**SA3**:
The 3GPP Service and System Aspects Working Group 3 (security).

**MCC**:
The 3GPP Mobile Competence Centre, which supports meetings and document handling.

**Delegate**:
A participant attending on behalf of a member company.
