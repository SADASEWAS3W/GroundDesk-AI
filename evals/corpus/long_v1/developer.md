# API Webhooks and Integrations Handbook

## Choose the connection mechanism

The platform offers a REST API, event notifications through webhooks, and integrations with named external tools. An API request asks the platform to perform or return something. A webhook sends an HTTP notification when a supported event occurs. A configured integration connects a listed tool through its authorization flow. Choose the mechanism that matches the problem before looking for its configuration page.

These mechanisms are related but should not be conflated. The API key page is not the webhook endpoint page, and a named integration's permissions are not a substitute for understanding an API request. When reporting a developer issue, identify whether it concerns a request made to the REST API, an event delivery received by an endpoint, or an external tool connection.

## Begin with the REST API

The REST API is available at api.example.com/v1. Generate an API key from Settings > Developer > API Keys. The API uses Bearer token authentication. Keep credentials out of examples shared in a support conversation; describing the authentication mechanism does not require revealing the key itself. This is credential-handling advice rather than a new API feature.

Full API documentation with interactive examples is available at docs.example.com/api. SDKs are provided for Python, JavaScript, and Go. The documentation location and SDK languages help developers find an appropriate starting point, but do not specify every endpoint's request or response schema. Use the API reference for those endpoint-specific details.

## Check the plan-specific request budget

API rate limits are 100 requests per minute for Pro and 1000 requests per minute for Enterprise. Keep the plan and the time unit together when explaining this limit. A request budget expressed per minute is not a concurrent-connection count or a daily quota. The Pro and Enterprise numbers must not be swapped merely because both appear in the same paragraph.

When investigating request volume, first identify the account's plan and the time interval being measured. This is a way of interpreting the documented limits, not a statement about an undocumented limit algorithm. The rate-limit description is separate from webhook delivery retries, which concern outgoing event notifications rather than incoming REST API requests.

## Configure event delivery

Create a webhook endpoint from Settings > Developer > Webhooks. Webhooks send real-time HTTP POST notifications when events occur in a workspace. Supported events include task.created, task.updated, project.created, and member.joined. An event name identifies the change being reported; it is not the name of a REST API endpoint to call.

Each webhook delivery includes a signature header for verification. Failed deliveries are retried up to 3 times with exponential backoff. Verification and retries address different parts of receiving notifications: the header supports verification of a delivery, while the retry policy describes what happens after delivery failure. The seed guide provides these high-level behaviors, not a complete receiver implementation.

## Connect external tools

Available integrations include Slack, Microsoft Teams, Jira, GitHub, Google Drive, and Zapier. Open Settings > Integrations, find the tool to connect, and follow its authorization flow. Each integration has specific permissions that can be configured. Review the intended connection and permissions as part of setup rather than assuming every integration uses the same authorization details.

Use Zapier for custom workflows connecting to more than 5000 apps. This option belongs to the integrations overview and should not be described as additional native webhook event types. Similarly, the existence of a Google Drive integration does not specify a new REST endpoint or a data-retention policy. Keep claims limited to the mechanism actually described.

For a useful troubleshooting report, state the mechanism, the relevant event or tool, and the observed failure. Avoid including API keys or other authorization material. A report about a failed task.created delivery should identify the webhook context, while an issue authorizing Slack should identify the integration context. This separation helps keep the follow-up focused on the correct documented workflow.
