# Questions for Laura / Conoscope -- Next Q&A Session

**Company:** Conoscope (Leipzig, Germany)
**Context:** We are building an AI-powered sponsorship evaluation system. These questions address gaps we discovered during implementation and testing.

---

## Critical Questions

### Q1: How do we verify an organization is legitimate and not fraudulent?

**Context:** Our Research Agent currently does basic checks:
- Freemail detection (gmail.com vs org domain)
- Website existence (HTTP HEAD check)
- Registered association pattern (e.V., gGmbH in name)

**But we cannot verify:**
- Is the organization actually registered? (Vereinsregister)
- Is the contact person real and authorized to request sponsorship?
- Is the event described actually happening?
- Has this organization been involved in fraud before?

**What we need from Conoscope:**
- Do your clients (regional companies) have access to the German Vereinsregister or Handelsregister for automated lookup?
- Is there a blacklist of known fraudulent organizations in the sponsorship space?
- What level of verification do your clients currently perform manually?
- At what sponsorship amount threshold does deeper verification become necessary? (e.g., >5,000 EUR requires ID check?)

---

### Q2: How do we verify an organization is not political?

**Context:** Our Eligibility Agent checks for political organizations using:
- Keyword blacklist: "Partei", "Wahlkampf", "Bundestagswahl", "Landtagswahl", "Fraktion", "politische Kampagne"
- Blocked org type: `political_org`
- LLM edge-case check (Haiku): triggered when warnings accumulate, checks for "political disguise"

**But real-world political disguise is subtle:**
- A "Buergerinitiative fuer saubere Energie" could be a legitimate environmental group OR a political lobby group
- A "Verein fuer demokratische Bildung" sounds educational but could be party-affiliated
- A cultural association organizing events could have hidden political affiliations

**What we need from Conoscope:**
- How do your clients currently distinguish between legitimate civic engagement and political organizations?
- Is there a public database of party-affiliated organizations in Germany?
- Should "Buergerinitiative" be automatically excluded (as per Bewertungskriterien) or case-by-case?
- What about organizations that are not political parties but advocate for specific political positions? (e.g., environmental advocacy, labor unions)

---

### Q3: How do we verify an organization is within the company's regional coverage area?

**Context:** Our system currently does simple string matching:
```
Extracted region: "Meersburg, Baden-Wuerttemberg"
Config: primary_regions = ["Baden-Wuerttemberg", "BW"]
Match: "baden-wuerttemberg" found in region string -> PASS
```

**Problems we identified:**
- If the applicant only writes "Musterort" without the state name, we cannot match
- Postal codes (e.g., "88709") are not checked against a geographic database
- "Regional" could mean the organization is headquartered locally but the event is national
- Some companies have specific service areas that don't follow state boundaries (e.g., a Stadtwerke serves 15 municipalities, not an entire Bundesland)

**What we need from Conoscope:**
- Do your clients define their coverage area by Bundesland, by postal code ranges, by city list, or by geographic radius?
- Is there a standard geographic database your clients use for region matching?
- Should we check the organization's headquarters location, the event location, or both?
- How granular should the geographic check be? (Bundesland level? City level? District level?)

---

## Additional Questions (Lower Priority)

### Q4: Sponsorship vs Donation classification

Our system detects whether a request is a sponsorship (quid pro quo with visibility return) or a donation (purely charitable). How do your clients currently handle this distinction? Are there different approval paths for donations vs sponsorships?

### Q5: Double funding detection

The Bewertungskriterien mentions "keine Doppelfoerderung mit einem anderen Foerderformat" (no double funding). How do your clients detect if an organization is receiving sponsorship from multiple programs simultaneously? Is there a central registry?

### Q6: Employee conflict of interest

The Bewertungskriterien mentions "keine Beziehung zu Mitarbeitenden / kein Interessenkonflikt." How is this currently checked? Do employees self-declare, or is there an automated check?

---

## What We Will Show Laura

During the Q&A, we plan to demonstrate:
1. The completeness loop (email with missing fields -> follow-up -> reply -> pipeline resumes)
2. The Live Demo page with real-time pipeline progress
3. The configurable criteria system (YAML-backed, admin can change without code)
4. How the evaluation agent scores against company-specific values
5. The Research Agent's verification capabilities (and explain what we need to enhance it)
