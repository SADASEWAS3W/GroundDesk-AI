# Account Preferences Performance and Security Handbook

## Locate personal preferences

Open account settings with the gear icon in the top right corner. Available personal settings include display name, profile picture, timezone, language preference, and notification settings. Start by identifying which preference needs to change. A timezone question concerns how the account is configured, whereas a slow-loading workspace calls for the performance checks later in this handbook.

To change the email address, go to Account > Security and follow the verification process. The email-change flow is distinct from editing a display name or choosing a language preference. An authenticator app can also be used to enable two-factor authentication for added account security. Describing where a setting is located does not require sharing account credentials in a support message.

## Configure notification channels and events

Control notifications from Settings > Notifications. Choose email, in-app notifications, or both. Preferences can be set separately for task assignments, mentions, project updates, and due date reminders. The channel choice and the event choice answer different questions: where a notice is delivered and what activity should produce it.

Quiet hours define a period during which no notifications are sent. Team admins can configure default notification settings for new team members. Personal preferences, quiet hours, and team defaults should be distinguished when explaining a notification issue. A request about a newly invited member's default settings is not necessarily the same as a request to change an existing user's individual choices.

## Investigate slow loading step by step

When the platform feels slow, check the internet connection first. Try a different browser or disable browser extensions that may interfere, and clear the browser cache. These checks help describe the local environment in which the issue appears. They do not establish that every delay is caused by a browser, so keep the observed behavior separate from the suspected cause.

If the issue persists, check status.example.com for ongoing incidents. A service-status check is different from changing personal notification settings. For a useful support description, note the operation that feels slow and the checks already attempted. This is a reporting habit, not a new platform monitoring feature or a guarantee about incident duration.

## Handle a large workspace

For large workspaces with 1000 or more items, enabling pagination in Settings > Performance can improve load times. The item-count context and the settings path belong together. Pagination is described as a possible performance improvement for this situation, not as a guarantee that any particular page will load within a fixed number of milliseconds.

If a workspace is large and the basic checks have not resolved the issue, explain that context when requesting help. Distinguish the size of the workspace from a particular task's content or an individual user's display settings. The documented troubleshooting sequence includes local checks, checking the status page, and considering pagination for large workspaces.

## Understand the documented security controls

The security overview states that data is encrypted at rest using AES-256 and in transit using TLS 1.3. These names apply to different contexts: stored data and data moving over a connection. Keep the association intact rather than treating the two mechanisms as interchangeable answers to every encryption question.

The fictional platform's seed security overview states SOC 2 Type II certification and GDPR compliance, and describes regular penetration testing and security audits. Its security whitepaper is referenced at example.com/security. These statements reproduce the scope of the seed example; this evaluation handbook is not independent proof of a real service's certification or compliance.

Two-factor authentication is available for all accounts and mandatory for Enterprise plans. Account configuration and service-level security controls are complementary topics, but they answer different questions. A user asking where to change an email address needs the account verification flow, while a user asking about encryption at rest needs the stored-data control described in the security overview.
