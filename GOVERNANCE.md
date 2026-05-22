# Kagenti Project Governance

The Kagenti project is dedicated to providing a secure, open source platform for
deploying and orchestrating autonomous AI agents on Kubernetes. This governance
explains how the project is run.

- [Values](#values)
- [Maintainers](#maintainers)
- [Becoming a Maintainer](#becoming-a-maintainer)
- [Meetings](#meetings)
- [Code of Conduct Enforcement](#code-of-conduct)
- [Security Response Team](#security-response-team)
- [Voting](#voting)
- [Modifications](#modifying-this-charter)

## Values

The Kagenti project and its leadership embrace the following values:

* Openness: Communication and decision-making happens in the open and is
  discoverable for future reference. As much as possible, all discussions and
  work take place in public forums and open repositories.

* Fairness: All stakeholders have the opportunity to provide feedback and
  submit contributions, which will be considered on their merits.

* Community over Product or Company: Sustaining and growing our community
  takes priority over shipping code or sponsors' organizational goals. Each
  contributor participates in the project as an individual.

* Inclusivity: We innovate through different perspectives and skill sets,
  which can only be accomplished in a welcoming and respectful environment.

* Participation: Responsibilities within the project are earned through
  participation, and there is a clear path up the contributor ladder into
  leadership positions.

## Maintainers

Kagenti Maintainers have write access to the
[project GitHub repository](https://github.com/kagenti/kagenti). They can merge their
own patches or patches from others. The current maintainers can be found in
[MAINTAINERS.md](./MAINTAINERS.md).  Maintainers collectively manage the
project's resources and contributors.

This privilege is granted with some expectation of responsibility: maintainers
are people who care about the Kagenti project and want to help it grow and
improve. A maintainer is not just someone who can make changes, but someone who
has demonstrated their ability to collaborate with the team, get the most
knowledgeable people to review code and docs, contribute high-quality code, and
follow through to fix issues (in code or tests).

A maintainer is a contributor to the project's success and a citizen helping
the project succeed.

The collective team of all Maintainers is known as the Maintainer Council, which
is the governing body for the project.

### Becoming a Maintainer

To become a Maintainer you need to demonstrate the following:

* commitment to the project:
  * participate in discussions, contributions, code and documentation reviews
    for 3 or more months,
  * perform reviews for at least 15 non-trivial pull requests,
  * contribute at least 10 non-trivial pull requests and have them merged,
* ability to write quality code and/or documentation,
* ability to collaborate with the team,
* understanding of how the team works (policies, processes for testing and code
  review, etc),
* understanding of the project's code base and coding and documentation style.

A new Maintainer must be proposed by an existing Maintainer by opening a PR
against the root of the [kagenti repository](https://github.com/kagenti/kagenti)
adding the nominee to MAINTAINERS.md.  The nominee will add a comment to the PR
testifying that they agree to all requirements of becoming a Maintainer.
A simple majority of existing Maintainers must approve the PR.
Maintainer nominations will be evaluated without prejudice
to employer or demographics.

Maintainers who are selected will be granted the necessary GitHub rights,
and invited to the
[private maintainer mailing list](mailto:kagenti-maintainers@googlegroups.com).

### Removing a Maintainer

Maintainers may resign at any time if they feel that they will not be able to
continue fulfilling their project duties.

Maintainers may also be removed after being inactive, failure to fulfill their
Maintainer responsibilities, violating the Code of Conduct, or other reasons.
Inactivity is defined as a period of very low or no activity in the project
for six months or more, with no definite schedule to return to full Maintainer
activity.

A Maintainer may be removed at any time by a 2/3 vote of the remaining
maintainers.

Depending on the reason for removal, a Maintainer may be converted to Emeritus
status. Emeritus Maintainers will still be consulted on some project matters,
and can be rapidly returned to Maintainer status if their availability changes.

## Meetings

Time zones permitting, Maintainers are expected to participate in the public
developer meeting, which occurs weekly.

Maintainers will also have closed meetings in order to discuss security reports
or Code of Conduct violations. Such meetings should be scheduled by any
Maintainer on receipt of a security issue or CoC report. All current Maintainers
must be invited to such closed meetings, except for any Maintainer who is
accused of a CoC violation.

## Code of Conduct

[Code of Conduct](./CODE_OF_CONDUCT.md) violations by community members will
be discussed and resolved on the
[private Maintainer mailing list](mailto:kagenti-maintainers@googlegroups.com).
If a Maintainer is directly involved in the report, the Maintainers will instead
designate two Maintainers to work with the Code of Conduct Committee in
resolving it.

## Security Response Team

The Maintainers will appoint a Security Response Team to handle security
reports. This committee may simply consist of the Maintainer Council themselves.
If this responsibility is delegated, the Maintainers will appoint a team of at
least two contributors to handle it. The Maintainers will review who is assigned
to this at least once a year.

The Security Response Team is responsible for handling all reports of security
holes and breaches according to the [security policy](SECURITY.md).

## Voting

While most business in Kagenti is conducted by
"[lazy consensus](https://community.apache.org/committers/lazyConsensus.html)",
periodically the Maintainers may need to vote on specific actions or changes.
A vote can be taken on
[the developer mailing list](mailto:kagenti-contributors@googlegroups.com) or
[the private Maintainer mailing list](mailto:kagenti-maintainers@googlegroups.com)
for security or conduct matters. Any Maintainer may demand a vote be taken.

Most votes require a simple majority of all Maintainers to succeed, except where
otherwise noted. Two-thirds majority votes mean at least two-thirds of all
existing maintainers.

## Modifying this Charter

Changes to this Governance and its supporting documents may be approved by
a 2/3 vote of the Maintainers.
