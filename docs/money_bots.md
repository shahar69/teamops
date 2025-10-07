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
| `AI_SCHEDULE_INTERVAL_SECONDS` | Poll interval for the scheduler loop that picks up due items. | `60` |
| `AI_SCHEDULE_BATCH_SIZE` | Maximum number of due items processed per scheduler tick. | `20` |

### Publisher credentials

Publisher connectors load credentials from environment variables (or the root `.env.production` file). Prefix everything with `PUBLISHER_` so the scheduler can validate configuration before making API calls.

| Platform | Required variables | Notes |
| --- | --- | --- |
| Reddit (script app) | `PUBLISHER_REDDIT_CLIENT_ID`, `PUBLISHER_REDDIT_CLIENT_SECRET`, `PUBLISHER_REDDIT_USERNAME`, `PUBLISHER_REDDIT_PASSWORD`, `PUBLISHER_REDDIT_USER_AGENT` | Uses a personal-use script application with password grant to submit text posts. |
| Twitter / X | `PUBLISHER_TWITTER_API_KEY`, `PUBLISHER_TWITTER_API_SECRET`, `PUBLISHER_TWITTER_ACCESS_TOKEN`, `PUBLISHER_TWITTER_ACCESS_SECRET`, `PUBLISHER_TWITTER_BEARER_TOKEN` | Requires elevated API v2 access with OAuth 1.0a user context for publishing threads. |
| YouTube Shorts | `PUBLISHER_YOUTUBE_CLIENT_ID`, `PUBLISHER_YOUTUBE_CLIENT_SECRET`, `PUBLISHER_YOUTUBE_REFRESH_TOKEN`, `PUBLISHER_YOUTUBE_CHANNEL_ID` | Uses the YouTube Data API to upload Shorts under the configured channel. |

Populate `.env.production` with production secrets (see the example committed in the repo) or export them in your deployment environment. The publisher modules read from the process environment first and fall back to this file for local development.

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
