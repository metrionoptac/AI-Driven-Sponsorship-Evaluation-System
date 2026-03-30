# 05: Research Agent -- Verification & Credibility

**Model:** HTTP checks ($0) + Claude Haiku for deep analysis (~$0.001) | **Time:** ~1s (quick), ~5s (deep)

## Purpose

Verify organization legitimacy and credibility. Runs in PARALLEL with Evaluation Agent. Results feed into evaluation and are displayed on the Live Demo page.

## Laura's Q&A Answers

**Q1:** "When there are larger amounts or unknown applicants, companies will do additional checks -- website, local news, social media. But most sponsoring managers already know the applicants."

**Kartik's follow-up on databases:** Laura says no automated government database lookup. Instead: **self-declaration via form** ("checkbox: I am a legal organization") + local knowledge.

**Key insight:** Our Research Agent already EXCEEDS what Laura expects. She expects local knowledge + optional web check. We do automated credibility scoring.

## 3-Tier Research Depth (auto-selected by amount)

| Tier | When | What It Does | Cost | Time |
|---|---|---|---|---|
| **QUICK** | Amount < 1,000 EUR | Freemail detection, org name pattern check (e.V., gGmbH), basic web presence | $0 | <1s |
| **STANDARD** | 1,000 - 5,000 EUR | QUICK + website active check (HTTP HEAD), news search, social media presence | $0 | ~2s |
| **DEEP** | Amount > 5,000 EUR or flagged suspicious | STANDARD + LLM credibility analysis (Haiku) | ~$0.001 | ~5s |

## Current Checks

| Check | Method | Output |
|---|---|---|
| Freemail detection | Domain list (gmail, gmx, web.de, yahoo, hotmail, outlook, t-online) | `is_freemail: true/false` |
| Registered association pattern | Regex: e.V., gGmbH, GmbH in org name | `registered_association: true/false` |
| Website active | HTTP HEAD request to org domain | `website_active: true/false` |
| Credibility score | Weighted combination of all checks | `credibility_score: 0.0-1.0` |
| Web presence score | Based on website + domain quality | `web_presence_score: 0.0-1.0` |
| Red flags | Accumulated warnings | `red_flags: []` |

## How Research Feeds Into Pipeline

| Consumer | What It Uses | How |
|---|---|---|
| Live Demo page | Credibility score, web presence, red flags | Displayed in Research Agent section |
| Evaluation Agent | Credibility score influences confidence | Context in evaluation prompt |
| Decision Agent | Red flags trigger human review | If red_flags > 0, route to HUMAN_REVIEW |

## Changes Needed

| Change | Priority | Notes |
|---|---|---|
| Make Research Agent ON/OFF configurable | DONE | Config tab: Agent Controls with toggle |
| Depth override in config | DONE | auto/quick/standard/deep selector |
| Add self-declaration checkbox to web form | MEDIUM | Laura's suggestion: "they should check yes, I am a legal organization" |
| Consider real Vereinsregister API integration | LOW (roadmap) | Laura didn't expect it. Mention in pitch as future enhancement. |
| Wire credibility_score to evaluation scoring | MEDIUM | Currently displayed but doesn't affect evaluation score directly |
