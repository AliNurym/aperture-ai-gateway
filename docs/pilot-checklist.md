# Aperture pilot checklist

## Purpose

Test whether owner-approved, bounded workflows and recovery solve a recurring problem for agent or data-workflow developers. Three sessions are a small usability and problem-discovery sample, not proof of market demand.

The interview inside each pilot may contribute to a five-interview discovery effort, but three pilot sessions alone do not meet that proposed interview target.

## Recruit

Invite three independent developers who already run recurring CSV or Python jobs and can describe their current process. Prioritize people who delegate work to agents or need spending controls, durable recovery, or result-file verification. Do not count the project team as a pilot participant.

## Prepare

- Choose one stable commit and record its hash with the notes.
- Use a synthetic or sanitized dataset that the participant has permission to use. Do not ask for customer, health, financial, credential, or other sensitive production data.
- Use the local OFF_CHAIN preview unless the participant specifically needs Devnet settlement. State the actual worker mode and payment mode before starting.
- For trusted-local execution, disclose that reviewed Python runs on the host without a container boundary. Do not describe receipt signatures as proof of faithful computation.
- Prepare the same task and dataset for the participant's current method so the comparison is meaningful.
- Ask separately before recording a session. A usability pilot does not imply consent to publish a screen recording or quotation.

## Session flow

1. Before opening Aperture, run a 10–15 minute problem interview. Ask the participant to walk through the last real task of this kind, how often it recurs, which tools and people were involved, where time was spent, and what failed or needed manual recovery. Ask how they currently authorize another person, script, or agent to spend money or access inputs. Ask what they tried instead and why they stopped. Capture their words and concrete recent examples; do not introduce Aperture's features or suggest a pain point first.
2. Have them complete the task using their current method. Record elapsed time and manual steps.
3. Give only this neutral task: “Use the workspace to process these two CSV batches into one report, then open and verify the result files.” Do not coach unless they are blocked; record each hint.
4. Observe whether they can stage inputs, review the plan and spending limit, approve the workflow, follow progress, recover an accepted step after the prepared interruption, and verify and download the output.
5. Ask what was unclear, what they would remove, whether the result fits their work, and how they would handle the same task next time.
6. Ask whether they would use the workflow again in the next month and what, if anything, they would pay for. Treat answers as stated intent, not purchase evidence.

Keep the interview separate from the task observation in your notes. A participant who describes a problem is not automatically a product fit; a successful task is not automatically evidence of repeat demand. Avoid hypothetical feature wish lists until after observing their current workflow.

## Record one row per participant

| Field | Observation |
| --- | --- |
| Pilot ID and date | |
| Commit and execution mode | |
| Current workflow and recurrence | |
| Current-method elapsed time / manual steps | |
| Aperture setup time / completion time | |
| Unassisted completion | |
| Hints or blockers | |
| Interruption recovery completed | |
| Receipt and result files verified | |
| Result useful for their task | |
| Would use again next month? Why? | |
| Price volunteered without prompting | |
| Participant's exact feedback (with consent) | |

## Review after three sessions

Separate observations from interpretation. Look for repeated friction, completion without coaching, verified recovery, and explicit intent to reuse. Compare time and manual steps with each participant's own baseline. If a participant cannot finish, record the blocker and improve the product before claiming the workflow is self-serve. Do not infer willingness to pay from a hypothetical price answer.

Keep notes pseudonymous. Store no raw participant dataset, wallet secret, or personal contact details in this repository. Publish a participant's name, quote, screen, or data only with their explicit consent.
