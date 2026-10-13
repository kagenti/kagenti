---
title: Read the numbers
sidebar_label: Read the numbers
description: What Cortex shows for each session, what each number means, and how to act on it.
sidebar_position: 3
---

You installed Cortex and started `agentop observe`. Now you see traffic. This page explains what the
numbers mean and what to do with them.

Cortex shows you what your coding agent sent and what it cost. It shows the model calls, the tool
calls and the token counts for each session, on your own computer, as they happen. Your agent does
not report this. Your model provider reports a monthly total, not one session while you work. Cortex
is the view between the two.

:::note The data stays on your computer
Cortex captures this traffic on your computer and keeps it there. It does not collect the data and it
does not send the data to Rossoctl or to any other service. The data is for you to read and to inspect.
When you stop the service, the data goes with it. See [Manage the service](laptop.md#manage-the-service).
:::

<!-- VERIFY: verified against v0.8.1 — the capture is in-memory and local, and no telemetry is sent
     by default. Re-confirm the "data goes with it" sentence when persistence (#901, sqlite) lands,
     since an on-disk store outlives the service. Central reporting is a separate, opt-in feature
     (#898), not part of the laptop tool. -->


<!-- VERIFY: the token, cost and pruning figures below are verified against v0.8.1 (#950, #952).
     The latency section describes v0.8.1: mean ± 1σ caps from LatMeanMs / LatStdDevMs
     (cmd/agentop/tui/usage_whiskers.go). Time to first token, p50, p95 and a maximum are #951;
     p99 and the maximum are #1026. Both are flagged in the section. -->
<!-- VERIFY: column headings are v0.8.1's — the context column is CONTEXT(1M), and the money
     columns return at 97. cortex#1246 shortens the heading to CTX(1M) and moves the threshold to
     93, but it is in no release yet. -->
<!-- VERIFY v0.9.0: once the release carrying cortex#1246 is out, change CONTEXT(1M) to CTX(1M) in
     the mock, the column list and "Read the context gauge", change "a terminal of 97 columns or
     more" to 93 here, "narrower than 97 columns" and "In the `CONTEXT` column" in
     operate/troubleshooting.md, and repaste the mock's gauges at the narrower 7-column width. -->


## What the numbers tell you

The numbers support four decisions:

- **Find an expensive prompt.** One session that costs much more than the others shows you where the
  cost is.
- **See whether caching operates.** A high cache-read count means the model reuses your prompt. A low
  count means it does not, and you pay the full rate each turn.
- **Catch a session that does not end.** A token count that grows without a result is an agent in a
  loop. You stop it before it costs more.
- **Decide whether to prune tool definitions.** The pruning figure shows the tokens that Cortex
  removed, so you know if the feature is worth enabling. See [Cost control](../concepts/experiments/cost-control.md).
- **See the spend for a day, a week or a month.** The spend band holds one figure for each of four
  periods. See [Read the spend band](#read-the-spend-band).
- **See which rate tier holds the cost.** The spend breakdown divides the spend by tier and by model.
  A large cache-write figure and a small cache-read figure is a cache that does not hold.

You can read this page before you install Cortex. It describes what Cortex shows you that you cannot
otherwise see.

## Watch a session

`agentop observe` opens a terminal interface. You land on the Sessions view. The other views open with
a key, and they return to the view that you opened them from.

- **Sessions.** A list of the sessions, with the most recent one first. Each row shows the identifier,
  the title, the time of the last event, the event count, the token total, the cost, the saving and
  the context gauge.
- **Events.** The calls in one session. Each row shows the time, the direction, the protocol, the
  model or the method, the status, the duration and the host. Press `Enter` on a session to open it.
- **Detail.** The full content of one event, as formatted JSON. Press `Enter` on an event to open it.
- **Spend breakdown.** Where the money went, by rate tier, and who spent it. Press `$`.
- **Usage charts.** A metric over a time window, as a chart. Press `u`.

### Keys

| Key | Action |
| --- | --- |
| `↑` `↓` or `k` `j` | Move between rows |
| `Enter` | Open the selected row |
| `Esc` | Return to the previous view |
| `/` | Filter the events |
| `$` | Open the spend breakdown |
| `u` | Open the usage charts |
| `c` | Open the column picker, in the Events view. Inside the picker, `s` sorts by the column under the cursor |
| `p` | Pause and resume the stream |
| `y` | Write the event to a file in `~/.cortex/agentop-events/` |
| `g` `G` | Move to the top or the bottom |
| `?` | Open the key help |
| `q` or `Ctrl+C` | Quit |

The key help (`?`) is a map of the views. It shows each key and the view that the key acts on.

The `/` key filters the events by a **text match**. For example, `messages` shows only the events
that contain that text. The match covers many fields of an event, not the method alone — the host,
the method, the plugin name, the reason, the path, and the message content all count.

Two searches are special:

- `deny` shows only the events that a plugin denied.
- `plugin:<name>` shows only the events that the named plugin acted on. For example, `plugin:jwt-validation`.

It is a text match, not a query language. You cannot filter on a condition such as a duration.

## Read the tokens

A model call has a cost in tokens. Cortex prices the tokens in four categories, because each category
has a different rate.

| Category | What it is | Why it is separate |
| --- | --- | --- |
| **Input** | The prompt tokens that the model read for the first time | You pay the full rate for these. |
| **Cache write** | The prompt tokens that the model wrote to its cache | More than the input rate. This is the one-time cost to store the prompt. |
| **Cache read** | The prompt tokens that the model read from its cache | Much less than the input rate. This is caching that operates. |
| **Output** | The tokens that the model generated | |

Cortex also captures a **reasoning** count. These are the output tokens that the model used to reason,
on a model that reports them. They are a part of the output count, not a fifth priced category.

### Why cache read and cache write are two numbers

A model can cache a part of your prompt. The next call that sends the same part reads it from the
cache. This is useful for a coding agent, because the agent sends the same system prompt and the same
files on each turn.

The two cache numbers have different prices, so Cortex keeps them apart:

- **A cache write costs more than an input token.** You pay a premium once, to store the prompt.
- **A cache read costs a fraction of an input token.** You save on each later turn that reuses the
  prompt.

The split tells you whether caching earns its cost:

- A large **cache-read** count means the cache operates. You pay the low rate for most of the prompt.
- A **cache-write** count that repeats, with little cache-read, means the cache does not hold. You pay
  the premium again and again and get no saving. This happens when the prompt changes on each turn.

## Read the cost

Cortex applies a price to each token category and adds the results. The figure is the cost of the
session.

- **The cost is an estimate, unless the provider returns an exact figure.** Cortex computes the cost
  from published rates for each model. When the provider returns an exact cost (for example, the
  `x-litellm-response-cost` header from LiteLLM), Cortex uses that figure instead.
- **The rates come from a table for each model.** A model that Cortex does not recognize has no rate.
  Cortex then shows no cost for that call, rather than a misleading zero, even though the token counts
  are still correct. A blank cost with correct tokens means the model is unpriced, not free.

<!-- VERIFY: verified against v0.8.1 — the authoritative header is x-litellm-response-cost
     (core/cost/event), and the rates come from the bundled table in core/cost/pricing. -->

## Read the sessions table

<!-- VERIFY: the column set, the narrow-terminal drop of the money columns, the em-dash rule and the
     SAVED~ marker are verified against v0.8.1 (cmd/agentop/tui). The table below is still an
     illustration, not a capture from a live session. Tracked in rossoctl/cortex#1113. -->

The Sessions view is the table that you land on. This is one capture of it:

```text
agentop · http://localhost:9094
LAST 1H    TODAY   7 DAYS    MONTH
  $4.04   $18.80  $216.44  $703.18
────────────────────────────────────────────────────────────────────────────────────
 SESSION       TITLE        UPDATED     EVENTS   TOKENS     COST    SAVED~  CONTEXT(1M)
 ctx-abc-123…  …pend-spans  3s ago          42    48.2k    $0.12     $0.01  ▕███████▎ ▏
 ctx-def-567…  weather-ag…  18m ago         15     1.2k   <$0.01         —  ▕▏        ▏
 ctx-ghi-901…               42m ago          7     2.9k        —         —  ▕███▊     ▏
 default                    1h ago           8        —        —         —            —
```

Read the columns as follows.

| Column | What it shows |
| --- | --- |
| `SESSION` | The session identifier, truncated. |
| `TITLE` | The name of the session, from the transcript of Claude Code. It is empty for a session that nothing named. |
| `UPDATED` | The time since the last event. |
| `EVENTS` | The count of the calls in the session. |
| `TOKENS` | The token total for the session. |
| `COST` | The cost of the session. |
| `SAVED~` | The cost that a reduction plugin avoided. |
| `CONTEXT(1M)` | How full the context of the conversation was on its last turn. |

An em dash (`—`) means that Cortex has no figure. It does not mean zero. A session with tokens and no
cost holds a model that the rate table does not name.

The two money columns need a terminal of 97 columns or more. On a narrower terminal Cortex removes
both columns. It does not show a rounded figure in their place.

### Read the context gauge

`CONTEXT(1M)` is a gauge, not a figure. It shows how full the context of your conversation was on its
last turn, against a window of one million tokens. The brackets are the scale, and Cortex draws them
on each row. An almost empty session therefore reads as empty, and not as a blank cell.

Claude Code sends three kinds of traffic under one session identifier: your conversation, the
subagents that it starts, and its own short internal calls. The gauge follows your conversation only.
It reads the last turn of that conversation, and it does not average a set of recent turns.

## Read the spend band

The four figures above the table are the spend band. Each cell covers one period, and the label names
the period.

| Cell | Period |
| --- | --- |
| `LAST 1H` | A rolling hour. |
| `TODAY` | From local midnight to now. |
| `7 DAYS` | A rolling seven days. |
| `MONTH` | From the first day of the local month to now. |

`TODAY` and `MONTH` are boundaries, and not lengths. Each one is narrow at the start of its period,
and it widens through the period. `7 DAYS` is a rolling window, so it is the one cell that no calendar
edge aligns to. Compare `7 DAYS` against `MONTH` with that difference in mind.

A cell that shows `—` is a period that your deployment cannot answer. Three of the four cells read
from a cost ledger. A local install holds that ledger, and Kubernetes does not hold it by default.
Cortex shows `—` in place of a figure that covers a shorter period than the label states.

A cell also carries its own age when its data stops arriving. `TODAY 7m` is a figure from seven
minutes ago. Each cell polls on its own schedule, so the age belongs to the cell and not to the band.

:::note The band and the table cover different periods
The `COST` column of the sessions table can add up to less than `TODAY`. The session store is in
memory, so the table reaches back only to the start of the current proxy process. `TODAY` reads from
the cost ledger on disk, and it survives a restart of the service. A table that adds up to less than
the band is therefore correct after a restart.
:::

### Read the spend breakdown

Press `$` to expand the band. The breakdown holds two columns:

```text
  WHERE IT WENT                    BY MODEL
output      ██████ $2.70           claude-opus-5   $4.55   35 req   5.6M tokens
cache-read  ███▌   $1.62
input       ▍      $0.22
cache-write —
   [a] [model] · endpoint · agent   [w] 1h   esc closes
```

The left column is the four rate tiers. They are the same four token categories that
[Read the tokens](#read-the-tokens) describes, priced. The right column is who spent the money. Press
`a` to change it between the model, the endpoint and the agent. Press `w` to change the period.

Cortex models the tier figures from the rate table. It does not measure them. A gateway reports one
figure for a call, and it never divides that figure by tier. Cortex apportions the tiers, so the column
adds up to the total of the period. A tier that the rate table does not name reads `—`, and not
`$0.00`, because `$0.00` claims that the tier is free.

## What a marker on a figure means

A figure carries a marker when Cortex cannot state it exactly. A figure with no marker is exact.

| Marker | Meaning |
| --- | --- |
| `~` | The figure is an estimate, so it is a lower bound and not an exact total. |
| `+` | The figure is a floor. Cortex could not price some traffic, or the period reaches past what the ledger holds. |
| `!` | The figure is short by an amount that Cortex cannot state. |

The `~` on `SAVED~` sits in the heading, and not on each value. Cortex estimates each saving, so a
marker on each row distinguishes nothing.

## How precise a money figure is

Cortex shows money in one of two forms, and which form depends on the surface.

- **Cents.** The four cells of the spend band, the `COST` and `SAVED~` columns of the sessions table,
  the `COST` of the usage charts, and both columns of the spend breakdown. You read these figures down
  a column, and you compare them against each other. Two more digits add noise.
- **Four decimals.** The `COST` column of the events table. One request costs $0.000038, so cents
  render a whole column as the same value.

Cortex never prints a figure above zero as `$0.00`. A cents figure below one cent reads `<$0.01`, and a
four-decimal figure reads `<$0.0001`. A figure of zero is a claim about the traffic, and never the
result of rounding.

## Read the cost of a longer period

`agentop cost` prints the spend for one period, without the terminal interface.

```bash
agentop cost                  # today, from local midnight
agentop cost --window month   # this month, from the first day
agentop cost --window 7d      # the last seven days
agentop cost --window 1h      # a rolling hour
agentop cost --json           # the totals as JSON, for a script
```

The command prints the period that the proxy answered, and not the period that you asked for. A
deployment with no cost ledger answers with the longest period that it holds. A figure of six hours
under the label of a month understates the month, so Cortex names the period it served.

## Read the usage charts

Press `u` to open the usage charts. The charts show one metric over one time window. Four keys change
what you see.

| Key | Action |
| --- | --- |
| `m` | Change the metric: tokens, requests, errors, latency or cost. |
| `w` | Change the window: 10 minutes, 1 hour or 6 hours. |
| `b` | Change the breakdown: none, status, method or plugin. |
| `s` | Change between this session and all of the sessions. |

The latency metric has no breakdown. Cortex records latency for a call, and not for a label.

`agentop` writes your choice of metric, window and breakdown to `~/.cortex/agentop-config.yaml`. The charts
open with the same choice the next time. `agentop` also writes the column selection and the filter of the
events table to that file.

## Read the latency

Cortex records the response time of each response that carries one: the time from the request to the
last part of the reply. It depends on the length of the reply, so a long answer is a slow one. This
is every non-tunnel response, not model calls alone. Fast non-model requests pull the mean down and
widen the spread.

The usage charts group these responses into buckets over the window you choose. For each bucket the
chart draws the **mean** as a crossbar (`┼`), with caps (`┬` and `┴`) at one standard deviation
either side of it, taken over the individual calls in that bucket. A bucket with no measured call
draws no mark, and its value reads `0`; the legend reads `0 = no measured responses`. A window with
no measured call says `no latency samples in this window`.

Read the mean for the average call, and the spread between the caps for how consistent the calls
were: wide caps mean the bucket mixed fast and slow calls. A crossbar with no caps is one call, or
calls too alike to separate at the chart's scale. The lower cap stops at zero, because a response
time cannot be negative. A lower cap on the bottom row means that the mean minus one standard
deviation falls in the bottom tenth of the chart. It does not mean that a call answered instantly.

:::warning The upper cap is not the slowest call
The caps are mean ± 1σ, a measure of spread, and not the fastest and the slowest call. The usage
charts keep no maximum, so **the slowest call in a window can sit above the top of the chart, and
the chart does not show it.** Do not read the upper cap as a worst case. To find the slowest call,
open the session and sort the events by `DURATION`: press `c` to open the column picker, move to
`DURATION`, and press `s` to sort by it, descending first. Opened from the Sessions view, the
chart covers every session, so the slow call may belong to a session other than the one you are
reading. Tracked in [cortex#1026](https://github.com/rossoctl/cortex/issues/1026).
:::

:::note Planned
Three figures are not in this release: time to first token (the time until the first word of the
reply appears), percentiles (p50, p95, p99) and a maximum. Cortex reports the mean response time
with its ±1σ caps. Tracked in [cortex#951](https://github.com/rossoctl/cortex/issues/951) and
[cortex#1026](https://github.com/rossoctl/cortex/issues/1026).
:::

## Read the pruning savings

If you enable tool pruning, Cortex removes the tool definitions that the agent does not use, before
the request goes to the model. The savings figure is the tokens and the cost that the pruning
removed. See [Cost control](../concepts/experiments/cost-control.md).

- **A figure above zero** is the saving for that session. You paid less because Cortex sent a smaller
  request.
- **A figure of zero** means that Cortex removed nothing. The usual cause is an agent with no tools.
  An agent that sends no tool definitions has nothing to prune, so zero is the correct figure and not
  a failure.

This figure is the answer to one question: what does pruning do for me? You enable pruning, you read
the figure, and you decide if the saving is worth the feature.

## A worked example

:::note
These are representative figures for the data that Cortex captures. They show the shape of a real
session. Replace them with a session that you capture before you rely on the exact values.
:::

<!-- VERIFY: the field set matches v0.8.1, except the mean response time, which no session field
     carries: it is the usage pane's LATENCY footer, request-weighted, at most the last 6 h, and
     scoped to this session when the pane is opened from the session's events. The values are an
     illustration, not a capture. -->

One session of a coding agent, with tool pruning enabled:

| Field | Value |
| --- | --- |
| Model | `claude-sonnet-4` |
| Events | 34 |
| Input tokens | 12,400 |
| Cache read | 486,000 |
| Cache write | 61,200 |
| Output tokens | 8,900 |
| Reasoning tokens | 3,100 |
| Cost | 2.14 USD |
| Mean response time | 11 s (the `LATENCY` figure under the usage charts, opened from this session) |
| Tokens pruned | 41,000 |
| Cost saved by pruning | 0.12 USD |

How to read it:

- **Caching operates.** The cache-read count (486,000) is much larger than the input count (12,400).
  The agent sends the same context on each turn, and the model reads almost all of it from the cache.
  Without the cache, the input cost is many times higher.
- **The cache-write count is a one-time cost.** The 61,200 cache-write tokens are the first turn that
  stored the context. Later turns read it, and do not write it again.
- **The mean hides the slow calls.** On average a call answers in 11 s, but a mean says nothing
  about the slowest one. To find it, open the session and sort its events by `DURATION`: press `c`
  for the column picker, move to `DURATION`, and press `s`. The sort covers the newest 2000 events;
  the footer offers `o` to load the older ones. The usage chart cannot show the slowest call: its
  caps are ±1σ, and it keeps no maximum
  ([cortex#1026](https://github.com/rossoctl/cortex/issues/1026)).
- **Pruning earns a small amount here.** It saved 0.12 USD, because it removed 41,000 tokens of unused
  tool definitions across the session. On an agent with many tools, this figure is larger.

## Why leave Cortex running

One session is useful. A week of sessions is more useful. The value is in the change over time:

- A prompt that grows more expensive each day.
- A cache-read count that falls, because a change to the agent broke the cache.
- A session that costs ten times the others.

You see these only if Cortex runs while you work. It runs as a background service and adds no step to
your day. See [Manage the service](laptop.md#manage-the-service).

## Give feedback

Did the numbers tell you what you needed, or not? Was a figure confusing? Tell us. Open the **Laptop
feedback** form on [rossoctl/cortex](https://github.com/rossoctl/cortex/issues/new/choose), or write a
message in [Slack](https://ibm.biz/rossoctl-slack). Feedback on the local tool is what makes the next
release clearer.

## Related pages

- [Quickstart on a laptop](laptop.md) installs Cortex and starts `agentop observe`.
- [Cost control](../concepts/experiments/cost-control.md) reduces the token cost.
- [Context compaction](../concepts/experiments/context-compaction.md) makes large tool output smaller.
- [Troubleshooting](../operate/troubleshooting.md) covers the case of no events or wrong numbers.
- [RossoCortex](../concepts/core/cortex.md) explains the program that captures this data.
