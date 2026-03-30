# Test Emails for Live Demo

Send these from your other email account to `kartikkashid222@gmail.com`.

---

## Email 1: German Sports Club (Email Body Only)

**Subject:** `Sponsoringanfrage - SV Adler Musterstadt Jugendabteilung`

**Body:**
```
Sehr geehrte Damen und Herren,

der SV Adler Musterstadt e.V. bittet Sie um Unterstuetzung fuer unsere
Jugendabteilung.

Unser Verein:
- Gegruendet: 1952
- 380 Mitglieder, davon 95 Jugendliche (8-18 Jahre)
- 5 Jugendmannschaften (Fussball)
- Vereinsregister: VR 45678

Wir benoetigen 4.200 EUR fuer:
- 50 Trikot-Sets (Heim + Auswaerts): 2.500 EUR
- 30 Trainingsbaelle: 600 EUR
- Erste-Hilfe-Ausruestung: 400 EUR
- Tornetze und Zubehoer: 700 EUR

Gegenleistung:
- Ihr Logo auf Trikots aller 5 Jugendmannschaften (Brust)
- Bandenwerbung (2 x 4 Meter) am Hauptplatz
- Social Media Posts (Instagram: 1.800 Follower, Facebook: 3.200)
- Namensnennung bei unserem Jugendturnier (300 Teilnehmer, Juni 2026)
- Eintrag als Partner auf www.sv-adler-musterstadt.de

Veranstaltung: Saisonstart am 15.08.2026
Rueckmeldung erbeten bis: 01.06.2026

Kontakt:
Thomas Weber
Jugendleiter
Email: jugend@sv-adler-musterstadt.de
Tel: 0171-5551234
Anschrift: Am Sportplatz 5, 63450 Hanau, Hessen

Mit sportlichen Gruessen,
Thomas Weber
SV Adler Musterstadt e.V.
```

---

## Email 2: Cultural Festival (Shorter Request)

**Subject:** `Foerderantrag - Stadtteilfest Neustadt 2026`

**Body:**
```
Guten Tag,

ich schreibe Ihnen im Namen des Buergervereins Neustadt e.V.

Wir planen unser jaehrliches Stadtteilfest am 20. September 2026
auf dem Marktplatz Neustadt. Erwartet werden ca. 1.200 Besucher.

Wir bitten um einen Sponsoring-Beitrag von 1.500 EUR fuer
Buehne und Musik.

Als Dank praesentieren wir Ihr Unternehmen als Hauptsponsor
auf allen Plakaten und im Programmheft (Auflage 2.000).

Ansprechpartnerin:
Lisa Meier
buero@bv-neustadt.de
0176-8889999

Vielen Dank!
Lisa Meier
```

---

## Email 3: Auto-Reply (Should Be Filtered)

**Subject:** `Automatische Antwort: Abwesenheitsnotiz`

**Body:**
```
Vielen Dank fuer Ihre Nachricht.

Ich bin vom 14.02. bis 28.02.2026 nicht im Buero erreichbar.
In dringenden Faellen wenden Sie sich bitte an meine Vertretung:
mueller@firma.de

Mit freundlichen Gruessen,
Dr. Schmidt
```

---

## Demo Flow

1. **Before the demo:** Send Email 1 and Email 3 to `kartikkashid222@gmail.com`
2. **During the demo:**
   - Open terminal: `python demo/live_demo.py` (fetches latest email, runs pipeline)
   - Open Streamlit: `streamlit run demo/dashboard.py` (visual dashboard)
   - Show Email 1 being processed (classified -> extracted -> quality HIGH)
   - Show Email 3 being filtered (classified as auto_reply -> SKIPPED)
   - Show the sample emails in Streamlit (no email sending needed)
3. **Key talking points:**
   - "The system detects new emails automatically via IMAP"
   - "Rule-based classifier filters junk in <1ms, no API cost"
   - "Claude Sonnet extracts all fields in ~12 seconds"
   - "Quality gate decides: proceed, flag for review, or reject"
   - "93% completeness on a typical German sponsorship request"
