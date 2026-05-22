# Kagenti Use Cases 
Kagenti supports deploying and orchestrating multiple categories of AI‑driven use cases. Each category reflects a distinct operational model and security posture, and Kagenti’s system design aims to support all of them.

1. Knowledge & Analysis Insight Service​
2. User-Authorized Synchronous Task Assistant ​
3. User-Authorized Asynchronous Task Assistant​
4. Continuous Monitoring & Automated Response Service ​
5. Event‑Driven Automation Workflow​

Kagenti’s system and security architecture is designed to accommodate the requirements and constraints of each use‑case type.

For platform-wide scenarios organized by persona (deployment, governance,
observability, identity, developer experience, etc.), see
[Use Cases](./user-stories.md).

## 1. Knowledge & Analysis Insight Service​

A read‑only system that retrieves, synthesizes, and analyzes organizational content to deliver evidence‑backed, cited insights without taking external actions. ​

Examples of use cases:
- A compliance assistant that summarizes relevant policy sections and cites authoritative documents.
- A technical support knowledge explorer that retrieves past resolutions and highlights the most likely fix.
- A financial analysis assistant that reviews quarterly reports and produces a cited summary of trends.

## 2. User-Authorized Synchronous Task Assistant ​

A real‑time, session‑bound assistant that performs actions on the user’s behalf using their permissions, without retaining state after the session ends. ​

Examples of use cases:
- Creating a pull request in GitHub when the user asks for it.
- Scheduling a meeting in Outlook based on a user’s natural‑language request.
- Updating a Jira ticket’s status or assignee during an active chat session.

## 3. User-Authorized Asynchronous Task Assistant​

A long‑running, stateful assistant that executes multi‑step workflows on the user’s behalf, continuing independently after the user session concludes. ​

Examples of use cases:
- Analyzing all 2025 pull requests, generating metrics, and notifying the user when the full analysis is complete.
- Running a multi‑day procurement workflow that gathers approvals from multiple stakeholders.
- Periodically scanning a large dataset, applying transformations, and producing a consolidated weekly report for the user.

## 4. Continuous Monitoring & Automated Response Service ​

A persistent system that observes telemetry or data streams and triggers alerts, remediation steps, or automated workflows when predefined conditions are met. ​

Examples of use cases:
- Document topic detection — Watches a datastore where documents are added or updated, uses an AI model to identify the document’s topic, tags, sensitivity, etc. and synchronize the document metadata or move it to the correct subfolder.
- Chat moderation assistant — Monitors company chat channels, uses an AI model to detect when someone asks a repeated question across channels, or posts a known issue, and automatically replies with the relevant knowledge‑base article.

## 5. Event‑Driven Automation Workflow​

An asynchronous process triggered by external events—such as webhooks, schedules, or alerts. ​

Examples of use cases:
- A GitHub webhook that triggers automated issue triage when a new issue is created.
- A nightly scheduled job that validates data quality and posts a summary to a team channel.
- A CRM webhook that launches a lead‑enrichment workflow when a new lead is added.

