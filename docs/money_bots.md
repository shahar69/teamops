# Money Making Bots Content Automation

The Money Bots unit adds an AI-assisted workspace for spinning up social posts, Reddit-style narratives, and short-form video scripts. It lives at `/ui/ai-content` inside the backend and is also embedded in Dashy via the **Money Bots** section.

## Key concepts

- **Profiles** capture reusable tone, voice, platform focus, and guardrails. Operators can create, update, and delete them via the UI or `/ai/profiles` endpoints.
- **Jobs** log every generation run with metadata, generated copy, and current status. They can be queried with `/ai/jobs`.
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
| `/ai/schedule` | GET | List scheduled deliveries (optionally filtered by status). |
| `/ai/schedule` | POST | Create a scheduled drop for a job. |
| `/ai/schedule/{id}` | PUT | Update the platform or run time for a scheduled drop. |
| `/ai/schedule/{id}/cancel` | POST | Cancel a scheduled delivery. |
| `/ai/schedule/{id}/retry` | POST | Retry a failed or canceled delivery. |

## Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `AI_MODEL` | Model name for chat completions. | `gpt-4o-mini` |
| `AI_API_BASE` | Base URL for the chat completions endpoint. | `https://api.openai.com/v1` |
| `AI_API_KEY` | API key/token for the AI provider. | _empty_ |
| `AI_TIMEOUT` | Timeout in seconds for the AI call. | `45` |

If `AI_API_KEY` is not set, the backend stores a placeholder result and returns status `needs_config` so operators know configuration is required.

## Prompt design

Generations combine:

- The selected profile’s tone, voice, target platform, and guardrails.
- A content blueprint (social posts, Reddit story, or video script) that dictates structure.
- Operator-supplied keywords, briefs, and data sources.

Outputs are returned in Markdown with a hook, main body, platform captions, visual cues, and monetization ideas ready for post-processing or publishing.

## Audit trail

Profile changes, job deletions, and content runs are logged to the existing audit table so leadership can review usage.

## Scheduling dashboard

The Money Bots UI includes a **Publishing schedule** panel that groups upcoming
deliveries by platform and status. Operators can launch the scheduler directly
from any generated job, then reschedule, cancel, or retry failed drops inline.
The same API endpoints documented above power external integrations, making it
easy to plug the automation flow into other calendaring or posting tools.
