"""Build the deterministic 300-case retrieval_v2 benchmark.

The corpus is intentionally versioned and generated from reviewed intent/fact
phrases. Synthetic cases carry explicit tags so they are not confused with
future, independently labelled production examples.
"""

from __future__ import annotations

import json
from pathlib import Path


DOCUMENT_FACTS = {
    "Getting Started with Our Platform": [
        "sign up with my work email and verify it",
        "create my first workspace and project",
        "invite colleagues during onboarding",
        "how long does initial setup usually take",
    ],
    "How to Reset Your Password": [
        "request a password reset email",
        "the forgot-password link has not arrived",
        "how long the password reset link remains valid",
        "password complexity required for a new password",
    ],
    "Managing Your Account Settings": [
        "change my display name and profile photo",
        "update the timezone and preferred language",
        "change the email address on my account",
        "where general account preferences are located",
    ],
    "Billing and Subscription Plans": [
        "compare the Free, Pro, and Enterprise plans",
        "price of the monthly Pro subscription",
        "which plan includes SSO and audit logs",
        "when an upgrade or downgrade takes effect",
    ],
    "Understanding Your Invoice": [
        "download an invoice from a previous month",
        "understand the tax and per-seat lines on my bill",
        "when monthly invoices are generated",
        "report an incorrect amount on an invoice",
    ],
    "Troubleshooting Login Issues": [
        "account locked after too many failed sign-ins",
        "authenticator code is correct but login still fails",
        "browser cache may be preventing me from signing in",
        "how long to wait after my account is locked",
    ],
    "Troubleshooting Slow Performance": [
        "workspace with more than one thousand items loads slowly",
        "check whether a service incident is causing slowness",
        "browser extensions make the application sluggish",
        "enable pagination to improve loading performance",
    ],
    "How to Create and Manage Projects": [
        "create a project from a template",
        "organize projects into folders",
        "archive a project after it is completed",
        "whether archived projects count toward plan limits",
    ],
    "Using the Task Management Feature": [
        "assign a task and give it a due date",
        "move a task between board columns",
        "add labels attachments and subtasks",
        "filter tasks in a large project",
    ],
    "Configuring Notification Settings": [
        "turn off email messages during quiet hours",
        "choose notifications for mentions only",
        "configure due-date reminder alerts",
        "set notification defaults for new team members",
    ],
    "Integrations Overview": [
        "connect the workspace to Slack",
        "integrate with Jira and Google Drive",
        "configure permissions during integration authorization",
        "use Zapier to connect another application",
    ],
    "API Documentation and Access": [
        "create an API key and use Bearer authentication",
        "Enterprise API requests allowed per minute",
        "find Python JavaScript and Go SDK documentation",
        "locate interactive REST API examples",
    ],
    "Security and Data Privacy": [
        "encryption used for stored and transmitted data",
        "whether the service has SOC 2 Type II certification",
        "GDPR compliance and regular security audits",
        "whether two-factor authentication is mandatory for Enterprise",
    ],
    "How to Export Your Data": [
        "export every project and task as JSON",
        "available CSV JSON and PDF export formats",
        "how a large background export is delivered",
        "how long an export download remains available",
    ],
    "Team Management and Roles": [
        "permissions available to the Viewer role",
        "difference between Member Admin and Owner",
        "change the role assigned to a teammate",
        "what happens to contributions when a member is removed",
    ],
    "Using Webhooks for Automation": [
        "verify the signature header on webhook deliveries",
        "number of retries for a failed webhook",
        "subscribe to task.created and task.updated events",
        "where to configure a webhook endpoint",
    ],
    "How to Enable Two-Factor Authentication (2FA)": [
        "enable two-factor authentication with an authenticator app",
        "use the QR code and six-digit code during 2FA setup",
        "recover access using backup codes",
        "disable 2FA from the security settings",
    ],
    "How to Delete Your Account": [
        "permanently delete my account and personal data",
        "transfer team ownership before deleting an owner account",
        "how long permanent account deletion takes",
        "export my data before closing the account",
    ],
}

STYLES = (
    ("direct", "How do I {fact}?"),
    ("support", "I need help to {fact}."),
    ("mixed-language", "请问如何 {fact}？"),
)

MULTI_DOCUMENT_CASES = [
    ("reset my password after repeated login failures", ["How to Reset Your Password", "Troubleshooting Login Issues"]),
    ("enable 2FA because Enterprise requires it", ["How to Enable Two-Factor Authentication (2FA)", "Security and Data Privacy"]),
    ("export everything before permanently deleting my account", ["How to Export Your Data", "How to Delete Your Account"]),
    ("transfer ownership and then remove my account", ["Team Management and Roles", "How to Delete Your Account"]),
    ("create a project and add assigned tasks with due dates", ["How to Create and Manage Projects", "Using the Task Management Feature"]),
    ("compare Enterprise security features and subscription options", ["Billing and Subscription Plans", "Security and Data Privacy"]),
    ("create an API integration that receives webhook events", ["API Documentation and Access", "Using Webhooks for Automation"]),
    ("invite a team and decide which roles they should have", ["Getting Started with Our Platform", "Team Management and Roles"]),
]

NO_ANSWER_TOPICS = [
    "refund eligibility", "legal advice", "quantum computing", "cryptocurrency payments",
    "telephone support number", "physical office address", "shipping a hardware device",
    "medical diagnosis", "payroll processing", "custom domain hosting", "video conferencing",
    "source code ownership", "employee background checks", "travel reservations",
    "food delivery", "stock trading", "insurance claims", "university accreditation",
    "weather forecasts", "social media advertising",
]


def _split(index: int) -> str:
    position = index % 5
    return "tuning" if position < 3 else "validation" if position == 3 else "test"


def build_cases() -> list[dict]:
    cases: list[dict] = []
    for title, facts in DOCUMENT_FACTS.items():
        for fact_index, fact in enumerate(facts):
            for style_name, template in STYLES:
                cases.append({
                    "query": template.format(fact=fact),
                    "relevant_document_titles": [title],
                    "tags": ["answerable", "paraphrase", style_name],
                })

    multi_prefixes = ("How can I", "I need to", "Please help me")
    for topic, titles in MULTI_DOCUMENT_CASES:
        for prefix in multi_prefixes:
            cases.append({
                "query": f"{prefix} {topic}?",
                "relevant_document_titles": titles,
                "tags": ["answerable", "multi-doc", "hard-negative"],
            })

    no_answer_prefixes = ("Do you support", "Where can I find information about", "Can your company help with")
    for topic in NO_ANSWER_TOPICS:
        for prefix in no_answer_prefixes:
            cases.append({
                "query": f"{prefix} {topic}?",
                "relevant_document_titles": [],
                "tags": ["no-answer", "hard-negative"],
            })

    assert len(cases) == 300
    for index, case in enumerate(cases, 1):
        case["id"] = f"v2-{index:03d}"
        case["split"] = _split(index - 1)
        case["notes"] = "deterministic synthetic benchmark; requires human review before production gating"
    return cases


def main() -> None:
    output = Path(__file__).parent / "datasets" / "retrieval_v2.jsonl"
    rendered = "\n".join(json.dumps(case, ensure_ascii=False) for case in build_cases())
    output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
