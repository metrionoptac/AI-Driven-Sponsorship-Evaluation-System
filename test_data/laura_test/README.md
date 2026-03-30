# Live Test: Musikverein Musterort — 120yr Jubilee (Amount Omitted)

**Based on:** Laura's Request #3 (Musikverein, highest quality sample)
**Modified:** Amount deliberately omitted from BOTH email and PDF to trigger completeness loop

---

## STEP 1: Send the Email

**From:** kartikkashid222@gmail.com
**To:** Kartikkashid1234567890@gmail.com
**Subject:** Sponsoring-Anfrage: 120-jaehriges Jubilaeumsfest Musikverein Musterort
**Attachment:** Sponsorenpaket_Musikverein_Musterort.pdf (in this folder)

### Email Body (copy-paste this exactly):

```
Sehr geehrte Damen und Herren,

der Musikverein Musterort 1906 e.V. feiert in diesem Jahr sein
120-jaehriges Bestehen mit einem grossen Jubilaeumsfest vom 24.-27.07.
auf der Festwiese in Musterort, Baden-Wuerttemberg.

Wir wuerden uns sehr freuen, wenn Sie unsere Vereinsarbeit und unser
Jubilaeumsfest finanziell unterstuetzen wuerden.

Im Anhang finden Sie unser Sponsorenpaket mit allen Details.

Fuer Rueckfragen stehe ich gerne zur Verfuegung.

Mit freundlichen Gruessen
Hans Mueller
1. Vorsitzender, Musikverein Musterort 1906 e.V.
Tel: 07532/12345
h.mueller@musikverein-musterort.de
Hauptstrasse 12, 88709 Meersburg
```

---

## STEP 2: Watch the System

### What should happen in the terminal:

```
[EmailWatcher] Poll #N starting...
[EmailWatcher] Found 1 unseen emails
Processing email: from=kartikkashid222@gmail.com, subject=Sponsoring-Anfrage..., attachments=1
Deduplication DISABLED -- processing all documents
Stored document: channel=email, file=Sponsorenpaket_Musikverein_Musterort.pdf
Created request: id=XXXXXXXX
Acknowledgment email queued for kartikkashid222@gmail.com

[XXXXXXXX] Step 1/7: EMAIL CLASSIFICATION -> SPONSORSHIP_REQUEST (confidence=0.9+)
[XXXXXXXX] Step 2/7: FORMAT DETECTION -> pdf
[XXXXXXXX] Step 3/7: TEXT EXTRACTION -> PDF extracted, ~1500 chars
[XXXXXXXX] Step 5/7: TEXT COMBINATION -> email body + PDF merged
[XXXXXXXX] Step 6/7: LLM EXTRACTION (Sonnet) -> org=Musikverein Musterort, amount=None
[XXXXXXXX] Step 7/7: QUALITY GATE (Haiku) -> LOW (amount MISSING = Tier 1 blocker)
[XXXXXXXX]   Field requested_amount      Tier 1: MISSING -- No amount in email or attachment
[XXXXXXXX] === INTAKE COMPLETE === success=False, quality=low

State -> awaiting_info
Completeness request email queued for kartikkashid222@gmail.com
  Missing: requested_amount, (+ any Tier 2 fields Haiku flags)
```

### What should happen in the dashboard:

- Pipeline page: new request appears with blinking stage on "Completeness"
- Detail page: structured data shows with red MISSING badge on amount
- kartikkashid222@gmail.com inbox: receives acknowledgment + follow-up email

---

## STEP 3: Reply with Missing Info

**Wait for the follow-up email** from Kartikkashid1234567890@gmail.com, then **REPLY to it**:

```
Sehr geehrte Damen und Herren,

vielen Dank fuer die Rueckmeldung.

Fuer das beschriebene Sponsorenpaket wuenschen wir uns eine
finanzielle Unterstuetzung ab 750 EUR.

Mit freundlichen Gruessen
Hans Mueller
Musikverein Musterort 1906 e.V.
```

### What should happen:

```
[EmailWatcher] Found 1 unseen emails
Email looks like a reply, routing to FollowupHandler: from=kartikkashid222@gmail.com
Follow-up reply matched to request XXXXXXXX
Merging 1 new fields into request XXXXXXXX: ['requested_amount']
Quality re-assessment: HIGH -- all Tier 1 present
Request XXXXXXXX quality improved to high, resuming pipeline

[XXXXXXXX] ====== PIPELINE EXECUTOR START ======
[XXXXXXXX] >> Stage 1/5: ELIGIBILITY CHECK
[XXXXXXXX]   required_fields:  PASS  All required fields present
[XXXXXXXX]   amount_range:     PASS  750.00 EUR within range 100-10000
[XXXXXXXX]   org_type_block:   PASS  Type 'cultural_association' is allowed
[XXXXXXXX]   keyword_blacklist: PASS  No blocked keywords found
[XXXXXXXX]   region_match:     PASS  Region 'Baden-Wuerttemberg' is primary
[XXXXXXXX]   budget_remaining: PASS  750 EUR << 102,500 EUR remaining
[XXXXXXXX] === ELIGIBILITY COMPLETE === ELIGIBLE=True, 10/10 rules passed
[XXXXXXXX] >> Stage 2/5: RESEARCH + EVALUATION (parallel)
... (continues through full pipeline)
```

---

## What's in the PDF (NO amount anywhere):

- Sponsor package (5 items with details)
- Event details (date, location, attendance, audience, program)
- Contact information
- NO pricing, NO EUR amount, NO financial request

## What's in the Email Body (NO amount):

- Organization name
- Event name + date
- Region
- "Im Anhang" reference to PDF
- Contact details
- NO amount

## Fields the System Should Extract (from both sources merged):

| Field | Source | Value |
|---|---|---|
| organization_name | Email + PDF | Musikverein Musterort 1906 e.V. |
| requested_amount | NOWHERE | null -> TIER 1 BLOCKER |
| purpose | Email + PDF | 120-jaehriges Jubilaeumsfest |
| event_date | Email + PDF | 2026-07-24 |
| region | Email + PDF | Musterort, Baden-Wuerttemberg |
| contact | Email + PDF | Hans Mueller, email, phone, address |
| visibility | PDF | 5-item package (Festbuch, Plakate, Banner, Logo, Nennung) |
| expected_attendance | PDF | 2000 |
| target_audience | PDF | Familien, Musikbegeisterte, Buerger |
| additional_context | Both | "120 Jahren kulturelles Leben", "individuelle Pakete" |
