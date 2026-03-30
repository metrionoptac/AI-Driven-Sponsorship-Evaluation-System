# FINAL Evaluation Criteria -- 20 Criteria for Stadtwerke Bodensee GmbH

**Source:** Laura Q&A ("~20 criteria per company, same for all requests"), evaluation_criteria.yaml, Bewertungskriterien (cherry-picked), Dr. Ansari coaching

**Key rule from Laura:** "It's always the SAME criteria. It does not matter if it's sports or culture. The criteria depends on the STRATEGY OF THE COMPANY."

---

## 6 Scoring Dimensions with 20 Sub-Criteria

### Dimension 1: Strategic Fit (Weight: 28%)

| # | Sub-Criterion | What It Measures | Scoring |
|---|---|---|---|
| 1 | **Topic area match** | Does the event topic align with company focus areas? | LLM scores 0-1 against configured focus_categories |
| 2 | **Regional anchoring** | Is the event local/regional to company service area? | local=1.0, regional=0.8, national=0.4, international=0.2 |
| 3 | **Target audience overlap** | Does event audience match company customer base? | LLM estimates overlap 0-1 |
| 4 | **Brand visibility possible** | Can the company get visible brand presence? | Checked from visibility offer |

**Mapped to Laura's Bewertungskriterien:** #4 Regionality, #5 Target Audience, #23 Portfolio Strategy

### Dimension 2: Community Impact (Weight: 22%)

| # | Sub-Criterion | What It Measures | Scoring |
|---|---|---|---|
| 5 | **Beneficiary count** | How many people benefit? | Normalized against 100-10,000 range |
| 6 | **Social value** | What social good created? Youth, inclusion, education? | LLM assessment 0-1 |
| 7 | **Geographic reach** | Local neighborhood vs city-wide vs regional | neighborhood=0.4, city=0.7, regional=1.0 |

**Mapped to Laura's Bewertungskriterien:** #6 Community/Cohesion, #7 Social Responsibility, #15 City/District

### Dimension 3: Visibility Value (Weight: 19%)

| # | Sub-Criterion | What It Measures | Scoring |
|---|---|---|---|
| 8 | **Logo exposure** | Where logo appears (jersey, banner, program, website) | Count + quality of placements |
| 9 | **Media reach** | Print, online, social media coverage | Estimated reach from description |
| 10 | **Digital presence** | Website mention, social media posts, newsletter | Explicit digital offerings |
| 11 | **Audience size** | Total reachable audience (live + media) | Attendance + media multiplier |

**Mapped to Laura's Bewertungskriterien:** #19 Visibility/Reach, #20 Activation/Storytelling

### Dimension 4: Cost Effectiveness (Weight: 16%)

| # | Sub-Criterion | What It Measures | Scoring |
|---|---|---|---|
| 12 | **Cost per beneficiary** | EUR per person reached (amount / attendance) | Lower = better, benchmarked |
| 13 | **Amount vs impact** | Is amount proportional to project scope? | LLM assessment: small amount + high impact = great |

**Mapped to Laura's Bewertungskriterien:** #24 Budget/Feasibility (effort-benefit ratio)

### Dimension 5: Partnership Depth (Weight: 9%)

| # | Sub-Criterion | What It Measures | Scoring |
|---|---|---|---|
| 14 | **Collaboration level** | Beyond logo? Joint storytelling? Co-created content? | logo_only=0.2, event_mention=0.4, media=0.6, content=0.8, deep=1.0 |
| 15 | **Communication potential** | Storytelling, campaign capability, dialogue | LLM assessment from visibility + additional_context |

**Mapped to Laura's Bewertungskriterien:** #20 Activation/Communication, #21 Relationship/Network, Laura Hint L3 "Joint Storytelling"

### Dimension 6: Portfolio Balance (Weight: 6%)

| # | Sub-Criterion | What It Measures | Scoring |
|---|---|---|---|
| 16 | **Category saturation** | Is this category over-invested? (e.g., sports >40%) | Penalty when category > max_portfolio_share |
| 17 | **Portfolio complement** | Does this request fill a gap in the portfolio? | Bonus for underrepresented categories |

**Mapped to Laura's Bewertungskriterien:** #23 Portfolio/Strategy (avoiding redundancies, balance)

### Context Signals (Not Scored, But Influence LLM Reasoning)

| # | Signal | Source | How Used |
|---|---|---|---|
| 18 | **Prior relationship** | `organization_profiles` DB table | LLM sees "NEW org, 0 prior approvals" or "REGULAR, 3 approvals, 4,500 EUR given" |
| 19 | **Organization credibility** | Research Agent `credibility_score` | Displayed. Feeds into LLM context. |
| 20 | **Amount plausibility** | Quality Gate LLM assessment | "750 EUR for 4-day festival = plausible" |

---

## Benchmarking (Historical Comparison)

Lives INSIDE the Evaluation Agent. Before scoring, the agent receives:

```
SIMILAR PAST SPONSORSHIPS:
  - Kulturverein Bodensee: cultural event (2025), approved 8,500 EUR, rating 4/5
  - Freiwillige Feuerwehr Meersburg: community event (2025), approved 3,500 EUR, rating 5/5
```

The LLM uses these as reference points: "Compared to similar past sponsorships, this request is below average in amount but above average in visibility package quality."

### Three Sources of Historical Data

| Source | Description | Status |
|---|---|---|
| Seed data | 65 records (2023-2025), realistic Bodensee-region orgs | DONE |
| Client upload | Company uploads existing sponsorship CSV/Excel | TODO (GUI upload feature) |
| Pipeline output | Every approved request auto-added to historical table | DONE (executor.py) |

---

## Company Values (Stadtwerke Bodensee GmbH)

These 6 values feed into Strategic Fit scoring:

| # | Value (German) | English | Weight |
|---|---|---|---|
| 1 | Verantwortung fuer die Gesellschaft | Responsibility for society | 20% |
| 2 | Umwelt bewahren und Klima schuetzen | Preserve environment, protect climate | 18% |
| 3 | Lebensqualitaet verbessern | Improve quality of life | 17% |
| 4 | Nah am Menschen | Close to people | 17% |
| 5 | Das Miteinander foerdern | Promote togetherness | 15% |
| 6 | Zukunft gestalten | Shape the future | 13% |

---

## Decision Thresholds

| Action | Score Range |
|---|---|
| APPROVE | > 0.65 |
| PARTIAL | 0.35 - 0.65 |
| REJECT | < 0.35 |

## Portfolio Category Caps

| Category | Max Share of Total Budget |
|---|---|
| Youth sports | 40% |
| Culture | 30% |
| Social | 30% |
| Education | 25% |
| Environment | 25% |
| Community events | 20% |

## Total: 6 dimensions x 20 sub-criteria + 6 company values + benchmarking = Laura's "~20 criteria"
