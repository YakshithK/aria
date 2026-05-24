# Launch Demo

## Primary: Discord Activity Report

**Task:** "Read the last 10 messages from #announcements in three Discord servers.
Summarize each server's announcements. Paste the summary into a Notion page."

**Why this demo works:**
- Real workflow knowledge workers understand immediately
- Crosses four windows (3 Discord servers + Notion)
- No code visible — just the agent working
- Speed differential is obvious: CUA ~30s, Operator 4-7 minutes
- The contrast IS the marketing

**Recording setup:**
- Split-screen video: CUA on left, Operator on right, same task, same hardware
- Show both clocks from start to finish
- Publish with the benchmark table (see below)

**Fallback if Discord debug port is rejected:**
Replace Discord with a Slack workspace (same CDP path) or use a browser-based
Discord (Discordapp.com in Chrome) instead of the Electron app.

**Fallback if Notion CDP tree is sparse:**
Replace Notion with Google Docs or Notion in the browser (Chrome CDP instead of
Electron CDP) — same architecture, slightly different target.

## Backup: Spreadsheet Research Fill

**Task:** "Open each of these 20 startup names in Chrome. Find the founding year and
HQ location for each. Fill the spreadsheet."

**Why this works for technical audiences:**
- Classic computer-use scenario everyone has seen before
- The cross-app data pipeline (Chrome → spreadsheet) is the demo
- Token cost per lookup is visibly lower than vision agents

## Benchmark Table (Include in Launch Writeup)

| Task                        | CUA Time | Operator Time | CUA Cost | Operator Cost |
|-----------------------------|----------|---------------|----------|---------------|
| Discord 3-server summary    | ~30s     | 4-7 min       | $X       | $Y            |
| Spreadsheet fill (20 rows)  | ~2 min   | 15-20 min     | $X       | $Y            |
| (add more during build)     |          |               |          |               |

Measure actual numbers during demo prep. Publish the exact numbers, not estimates.

## Technical Writeup Outline

1. The problem: why screenshot agents are slow
2. The architecture: UIA + CDP as machine-readable interfaces
3. The benchmark: exact numbers, same hardware, side-by-side video
4. The limitations: what doesn't work and why (see LIMITATIONS.md)
5. The roadmap: UIA module post-launch, vision as v2 after real user data

## Pre-Demo Checklist

- [ ] Discord launches with debug port on test machine
- [ ] Notion CDP semantic map is rich enough (AX or DOM fallback; test: can you see page content?)
- [ ] Discord channel messages visible in CDP semantic map (AX or DOM fallback)
- [ ] gemma4:31b-cloud (Ollama) can navigate from channel list to messages in one task
- [ ] Token count per full demo run measured and noted
- [ ] Operator version of the demo recorded on same hardware
- [ ] Repository is public with setup instructions
- [ ] Launch writeup drafted
