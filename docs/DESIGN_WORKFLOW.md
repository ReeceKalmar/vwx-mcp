# Design workflow and ownership

This guide is operating policy for agents, not implemented automatic recovery.
It adds no permission to clear holds, retry jobs, change focus or bypass background
mode. Follow the [current contract](VECTORWORKS_2027.md),
[background rules](BACKGROUND_WORK.md) and [maintenance protocol](MAINTENANCE_2027.md).

## Capability and completion

The bridge supports useful typed background design, but a complete unattended
landscape and house workflow is not yet verified. Generated adapters and successful
calls do not establish correct native geometry or a complete project lifecycle.
Scoped [architectural evidence](NATIVE_ARCHITECTURE_2027.md) covers Roof Face,
modern Slab and several straight-Wall cases, with retained discrepancies and
limits. Native Hardscape, Landscape Area, Plant PIO and site-model workflows need
their own verification; `create_plant` inserts an existing symbol. Consult
[coverage](TOOL_COVERAGE.md) and the [remaining work](ROADMAP.md) for the boundaries.

Preserve the requested native object outcomes. A mesh, generic solid or symbol
does not satisfy a requested editable architectural or landscape object unless
the user authorizes that change. Diagnostic conversions may support independent
checks while preserving the native design object. Preparation, authored objects,
verified geometry and saved deliverables are separate completion claims.

## Keep one design owner

One agent owns native work in the shared active drawing. Other agents may prepare
geometry, specifications, resource choices, code and offline checks concurrently.
Document guards do not create isolation; serialize native requests and coordinate
ownership before any document transition or maintenance action.

The design owner carries the task through ordinary planning, contract discovery,
document/readiness checks, authorized creation and edits, and later independent
readbacks. Existing authorization covers routine steps within its scope; each
documented step does not require a new handoff or confirmation. Use existing
typed tools and documented checks without building a new private framework for
routine work. Separate creation/reset from regeneration-dependent inspection.
A batch or sequence remains one job and has no rollback.

## Keep durable context concise

Maintain one private job register and a short current-status note derived from
it. Replace superseded status in that note; retain history in linked incident
records rather than appending contradictory next actions. A new agent needs:

- The ordered design queue, requested deliverables and single native owner.
- The exact drawing, last verified saved checkpoint and independently verified
  authored progress; keep prepared work in a separate field.
- The current incident, outstanding request disposition, existing hold and
  consumed attempts, with references to their original evidence.
- The next concrete action, its prerequisites and the return condition if blocked.

Keep customer addresses, drawings, credentials, leases, full logs and local
incident frameworks outside Git. In repository documentation, retain reusable
contracts and evidence limits. Start with this guide and the relevant subsystem
guide; load only the exact saved evidence needed for the current action.

## Classify the stop before escalating

Use the actual request disposition and current evidence, not an old scheduler
label alone. Preserve results and journals. Missing responses, fresh heartbeats
or a later idle label do not establish that a previous job never ran.

| Situation | Owner action and boundary |
|---|---|
| Environment unavailable **before publication**, with verified no outstanding work | Pause native work and continue independent preparation. This alone needs no code-repair handoff. Resume only after the environment is available and normal readiness, document identity and ownership checks pass. |
| Known rejection or correctable input | Read the exact rejection and SDK contract. If non-dispatch is established, there is no outstanding work, and existing hold/workflow clearance conditions permit it, the design owner can correct the input within the authorized task and make a new valid request. Preserve the rejected result. A background interaction block requires a supported route or the necessary attended scope; it is not permission to bypass policy. |
| Complete attributed response with a geometry discrepancy | Stop the affected operation. Separate accepted calls from verified geometry, preserve the objects and failed expectations, and use bounded documented readbacks and independent checks when host state permits. Continue independent design work. Escalate a concrete reproducible defect or uncertainty that requires repair investigation; do not replay setters or joins to make an assertion pass. |
| Outstanding queued/claimed job, unknown completion, crash, unexplained publication or existing hold | Stop new native work and reconcile the exact request, result, scheduler state and document through the documented protocol. Bring in maintenance when that state requires it. Preserve leases, queue entries, fences, consumed attempts and evidence. No automatic replay, cleanup or takeover. |

Verify “no outstanding work” through the documented fresh readiness checks,
including queue/publication records and completion state. Separately establish
whether the request was published. For an already published request, `VW_JOB_UNCLAIMED`
with `dispatched=false` establishes non-dispatch only after atomic removal proves
that request was not claimed. A saved queue snapshot may precede that removal;
it does not by itself prove work remains queued now. This transport result does
not clear other work, an explicit hold or a consumed one-use workflow claim.
Require fresh checks and the existing clearance conditions; do not reset the
workflow claim. Follow
[background diagnostics](BACKGROUND_WORK.md#verify-without-desktop-control).

A minimized host with a queued job belongs to the unresolved-work case, even if
minimization explains why dispatch stopped. This guide does not clear any existing
incident or consumed attempt. Restoring availability alone does not authorize a
new mutation or retry. Never force-kill Vectorworks, inject mouse/keyboard input,
change focus, use force flags or direct IPC to bypass the typed background route,
or clear an unknown lease or completion fence.

## Keep progress and handoffs bounded

While native work is paused, continue work that does not depend on the unresolved
document state: dimensions, layouts, independent expected geometry, object and
resource specifications, supported API contracts, offline checks and the next
reviewable plan. Label these as preparation; do not report them as authored or
verified Vectorworks work. Exploratory live tests require an explicitly authorized
disposable drawing and the [testing rules](TESTING_2027.md). Reconciliation of an
existing project uses its authorized owner, bounded readbacks and the incident's
return conditions; it is not permission to experiment on the project.

Maintenance is for a concrete reproducible defect, authorized deployment/restart
or uncertain execution state. A routine unavailable environment with
proven non-publication and no outstanding work stays with the design owner.
Unexpected prompts or startup problems can still require user action; background
mode does not implement unattended recovery from every application failure.

When a handoff is necessary, send one concise incident packet containing:

- The requested native outcome, authorized scope and current document owner.
- The failed operation and exact request/run reference, disposition, response or
  error, and relevant readiness/document evidence; distinguish facts from unknowns.
- The smallest reproducible discrepancy, existing holds and preserved artifacts,
  with any actions already consumed clearly identified.
- One reviewable return condition: the specific reconciliation, verified fix or
  user action needed, what remains unverified, and who resumes native ownership.

Keep the packet in the existing task/evidence record and reference it on return;
do not repeat the whole investigation or route routine next steps back through
maintenance. A return transfers evidence and ownership, not blanket readiness.
The design owner checks that the return condition is met, performs the normal
current document/readiness checks and continues the authorized task. Source fixes,
deployment and live verification remain distinct claims.
