# PlayNYU plan

What is done, what is next, and what can go wrong. Updated 2026-11-26.
The board and the issues are the source of truth for owners and dates.
Deploy order is `testing` first, then `main` (see [WORKFLOW.md](WORKFLOW.md)).

## Progress

| Milestone | Epic | State |
|---|---|---|
| E4 Schedule matches and browse facilities | #29 | Done. Scheduling, round-robin, facilities and the map are live |
| E5 Scores and standings | #30 | #151, #159 and #160 finish it |
| E6 Overview and notifications | #31 | Closed |
| E7 Chat, comments and moderation | #32 | Chat, direct messages, forums, comments and blocking are live. #158 and #299 remain |
| E8 Setup and deploy | #33 | The code reads `DATABASE_URL` (#136). The testing site has none set, so it still runs on SQLite and loses its data on each deploy (checked 2026-11-26). Production's settings live in the production AWS account. #150 is this file |
| E9 Secure and observe | #34 | Audit log and permission sweep done with #153 and #155. #165, #166 and #167 remain |

## Next steps

In this order:

| # | Ticket | Work | Depends on |
|---|---|---|---|
| 1 | #165 | Structured logs, with verification links and emails kept out | – |
| 2 | #299 | Reports ask for a reason, and the queue shows it | – |
| 3 | #158 | Hidden messages show as "Removed by a League Admin" | #299 |
| 4 | #298 | A captain hands off the role, then leaves | – |
| 5 | #300 | Pre-created accounts type the password once | – |
| 6 | #166 | Error tracking | An account for the service |
| 7 | – | Point the testing site at Neon: create the project and set `DATABASE_URL` on `playnyu-test` ([DATABASE.md](DATABASE.md)) | A Neon project for testing |
| 8 | #167 | Backup restore test | Step 7, and access to the Neon projects |
| 9 | #51 | LLD and wiki with the agreed profile fields | – |

Close each epic when its last ticket closes.

## Risks

- Every merge to `main` deploys production. Check the testing site first.
- A merge that adds a migration runs it on the deploy, on real data.
- #300 changes sign-up and email links. Review it for account takeover.
- The Neon free plan stops writes when its storage is full (see [DATABASE.md](DATABASE.md)).

## Open questions

- Which sports don't allow draws? Every sport allows them until a League Admin changes it on the sport's edit page.
- Which error-tracking service (#166)?
