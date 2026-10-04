# Native controller oracle checkpoint

Base19a3e1c remains frozen and NONINSTALLABLE. This delta changes only conservative
cold native open/recovery budgets (30 seconds, explicit deadline still wins), the QA
oracle and documentation. No browser driver, debug port, hidden CDP attachment,
auth bypass, persistent grant, live switch or OS policy change is introduced.

Independent headed Edge testing reports five renderer/session scenarios PASS:
authenticated DOM, reload, multitab, revoke retaining draft and recovery/explicit retry.
That supported Playwright renderer seam is separate from the exact default OwnedBrowser
app window. No frontend/auth bug is confirmed by the old phase20 timeout.

UIA RuntimeId is not a document generation contract. Posted F5 is not acknowledged
reload delivery. Corrected tools/qa_owner_native.py stops as BLOCKED if authenticated
DOM is not observable, and otherwise BLOCKED until a supported fresh-document observer
exists. It never produces a green reload gate from title/PID or accessibility IDs.
Reports are required outside the application. One corrected actual Edge/Tk run on a
unique synthetic port confirmed exact window/kernel handoff and scoped CLI, then
BLOCKED_NATIVE_DOM_OBSERVABILITY (30 UIA elements, no expected authenticated navigation
control). Owned close and transient profile removal completed. No further probing.

## Minimal manual acceptance gate for an authorized operator

Use a fresh synthetic pointer/data root and private browser profile, unique free port,
local-only/no-refresh, actual default launcher/Tk controller. Never use production or
an existing personal profile. Confirm the retained browser handle/handoff metadata.

1. Observe populated authorized task/pipeline UI in that exact Edge app window, not
   merely title/PID/static sidebar. Record absence of owner-session dialog. If that
   meaningful UI is inaccessible to the supported observer/operator, stop BLOCKED.
2. Deliver a real browser reload using supported browser UI or direct operator input.
   Confirm completion and a fresh document via an approved fixture document-generation
   marker/observer; identity of UIA elements, posted messages and window title are
   insufficient. A nonpersisted throwaway UI marker may be used only if browser
   restoration cannot make the evidence ambiguous. Otherwise keep the gate UNVERIFIED.
3. In another window/tab of the same private profile, confirm populated authorized UI.
   Put a throwaway unsaved pipeline draft in the first window. Revoke through the real
   Tk controller; observe its session dialog while retaining the draft. Recover through
   that controller and explicitly retry the first window; observe authorized UI/draft.
4. After explicit synthetic draft closure, restart through Tk. Confirm new epoch and
   unchanged synthetic runtime, old authority refusal and authorized new UI. Close
   through Tk, including explicitly consented windowless owned background cleanup.
   Verify every retained child exited and the private profile was removed; preserve
   any unverified process/profile rather than terminate a discovered PID.

Required report: exact commit, isolated port, meaningful UI/document observations,
commands/actions acknowledged, bounded timings, owned cleanup result and precise
remaining blockers. Do not record cookie/capability/credential values. If the exact
retained app window has no supported fresh-document observer, this combined gate
cannot be automated here; schedule manual acceptance in the next authorized interactive
session. Separate headed renderer tests do not substitute for it. No user-ready claim.
