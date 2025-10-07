# Money Making Bots Content Automation

The Money Bots unit adds an AI-assisted workspace for spinning up social posts, Reddit-style narratives, and short-form video scripts. It lives at `/ui/ai-content` inside the backend and is also embedded in Dashy via the **Money Bots** section.

## Key concepts

- **Profiles** capture reusable tone, voice, platform focus, and guardrails. Operators can create, update, and delete them via the UI or `/ai/profiles` endpoints.
- **Jobs** log every generation run with metadata, generated copy, and current status. They can be queried with `/ai/jobs`.
- **Schedules** let operators queue previously generated jobs for timed delivery to downstream tooling. They are polled by the backend scheduler and emitted when due.
- **Generations** call the configured chat completion provider to produce Markdown output that includes hooks, body, captions, and monetization prompts.

## API surface

| Endpoint | Method | Description |
| --- | --- | --- |
| `/ai/profiles` | GET | List saved content profiles. |
| `/ai/profiles` | POST | Create a new profile. |
| `/ai/profiles/{id}` | PUT | Update an existing profile. |
| `/ai/profiles/{id}` | DELETE | Remove a profile. |
| `/ai/jobs` | GET | List recent generation jobs (optionally filtered by `profile_id`). |
| `/ai/jobs/{id}` | GET | Retrieve job details. |
| `/ai/jobs/{id}` | DELETE | Delete a job log entry. |
| `/ai/content` | POST | Trigger a new generation run. |
| `/ai/schedule` | GET | List scheduled deliveries (filterable by `job_id` or `status`). |
| `/ai/schedule` | POST | Schedule a previously generated job for future delivery. |
| `/ai/schedule/{id}` | DELETE | Cancel a pending or queued schedule entry without removing the job. |

## Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `AI_MODEL` | Model name for chat completions. | `gpt-4o-mini` |
| `AI_API_BASE` | Base URL for the chat completions endpoint. | `https://api.openai.com/v1` |
| `AI_API_KEY` | API key/token for the AI provider. | _empty_ |
| `AI_TIMEOUT` | Timeout in seconds for the AI call. | `45` |
| `AI_SCHEDULE_INTERVAL_SECONDS` | Poll interval for the scheduler loop that picks up due items. | `60` |
| `AI_SCHEDULE_BATCH_SIZE` | Maximum number of due items processed per scheduler tick. | `20` |

If `AI_API_KEY` is not set, the backend stores a placeholder result and returns status `needs_config` so operators know configuration is required.

## Prompt design

Generations combine:

- The selected profile’s tone, voice, target platform, and guardrails.
- A content blueprint (social posts, Reddit story, or video script) that dictates structure.
- Operator-supplied keywords, briefs, and data sources.

Outputs are returned in Markdown with a hook, main body, platform captions, visual cues, and monetization ideas ready for post-processing or publishing.

## Audit trail

Profile changes, job deletions, content runs, and schedule lifecycle events (create/cancel plus automated state transitions) are logged to the existing audit table so leadership can review usage.

## Scheduling lifecycle

The scheduler runs inside the FastAPI app using a lightweight async background task. Every `AI_SCHEDULE_INTERVAL_SECONDS`, it looks for rows in `ai_content_schedule` with `status = 'pending'` and a `publish_at` timestamp that has passed. Matching rows are atomically flipped to `queued` along with delivery metadata (e.g., last enqueue time). Failures move the row to `error` and capture the exception string in the metadata blob for later review.

Operators can:

- Create a schedule by POSTing `job_id`, `platform`, and `publish_at` (ISO8601) to `/ai/schedule`.
- List schedules, filtering by status or job, to monitor queued work.
- Cancel pending/queued schedules via `DELETE /ai/schedule/{id}`, which preserves the job but marks the row as `canceled` and records who performed the action.

Because deliveries are tracked in the shared table, downstream workers can safely pick up queued rows without risking double-processing thanks to the `FOR UPDATE SKIP LOCKED` semantics used during dispatch.
