# Journal RSS Sources

RSS feed sources for every tracked materials-science journal. This is the
human-maintained index the pipeline ingests from: each row's **RSS URL** feeds
`mat-trend ingest` (via [`config/journals.json`](config/journals.json), the
machine-readable mirror of this table). Extend it as new feeds appear, and
re-check existing links with `mat-trend check-feeds --check`.

Scope: the flagship materials-science journals — plus closely-related chemistry,
polymer, and general-science titles — across the major publishers (**Nature
Portfolio · Science · Cell Press · Wiley · ACS · RSC · Elsevier · Oxford · others**).

## Columns

- **Family** — publisher family: `Nature`, `Science`, `Cell Press`, `Wiley`, `ACS`, `RSC`, `Elsevier`, `Oxford`, `Other`.
- **Journal** — human-readable journal name.
- **Key** — stable id used for the data store (`data/<key>/<YYYY-MM>.csv`) and in `journals.json`.
- **Feed type** — `subject` (subject-filtered), `journal`/`etoc`/`current` (latest table of contents).
- **Frequency** — the journal's publication cadence; **Mater-trend polls each feed at this frequency** (see below).
- **RSS URL** — the feed `feedparser` fetches.
- **Focus** — `high` (mostly materials/polymer science) or `mixed` (multidisciplinary; materials is a subset).
- **Status** — `✓` verified live · `?` unverified (confirm with `check-feeds`) · `✗` dead.

## Polling cadence

Mater-trend tracks each journal at its declared **Frequency**. `mat-trend ingest`
polls a feed only when it is *due* — i.e. at least its cadence interval has elapsed
since the last poll (recorded in `data/.ingest_state.json`):

| Frequency | Polled at most every | Typical journals |
|-----------|----------------------|------------------|
| `continuous` | every run | online-first/ASAP titles (Nature Communications, Angewandte, Macromolecules, ACS letters) |
| `weekly` | 7 days | Nature, Science |
| `biweekly` | 14 days | Cell |
| `monthly` | 30 days | monthly Nature sister titles, Nature Chemistry, NSR, CCS Chemistry, Progress in Polymer Science |

Run `mat-trend ingest` (or `refresh`) on a frequent schedule — e.g. weekly — and
each journal is fetched no more often than its cadence; pass `--force` to poll every
feed regardless of when it was last seen.

> RSS feeds are a **rolling window** (latest issue / recent items only). Mater-trend
> accumulates entries into a deduplicated store (dedupe by DOI → link → title), so
> history builds up across polls.

## Nature Portfolio

Pattern: `https://www.nature.com/<code>.rss` (journal) and `https://www.nature.com/subjects/<slug>.rss` (subject). Served without bot challenge. Items carry title, link, description, **DOI**, authors, and ISO dates.

| Family | Journal | Key | Feed type | Frequency | RSS URL | Focus | Status |
|--------|---------|-----|-----------|-----------|---------|-------|--------|
| Nature | Nature Reviews Materials | nat-rev-mater | journal | monthly | https://www.nature.com/natrevmats.rss | high | ? |
| Nature | Nature | nature | subject | weekly | https://www.nature.com/subjects/materials-science.rss | high | ? |
| Nature | Nature | nature | journal | weekly | https://www.nature.com/nature.rss | mixed | ? |
| Nature | Nature Energy | nat-energy | journal | monthly | https://www.nature.com/nenergy.rss | high | ? |
| Nature | Nature Nanotechnology | nat-nano | journal | monthly | https://www.nature.com/nnano.rss | high | ? |
| Nature | Nature Catalysis | nat-catal | journal | monthly | https://www.nature.com/natcatal.rss | high | ? |
| Nature | Nature Materials | nat-materials | journal | monthly | https://www.nature.com/nmat.rss | high | ? |
| Nature | Nature Photonics | nat-photon | journal | monthly | https://www.nature.com/nphoton.rss | mixed | ? |
| Nature | Nature Chemistry | nat-chem | journal | monthly | https://www.nature.com/nchem.rss | mixed | ? |
| Nature | Nature Communications | nat-commun | journal | continuous | https://www.nature.com/ncomms.rss | mixed | ? |
| Nature | npj Computational Materials | npj-comp-mater | journal | continuous | https://www.nature.com/npjcompumats.rss | high | ? |
| Nature | Communications Materials | commun-mater | journal | continuous | https://www.nature.com/commsmat.rss | high | ? |

## Science (AAAS)

Pattern: `https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=<code>`. **Cloudflare-protected** — the fetcher must send a realistic `User-Agent`.

| Family | Journal | Key | Feed type | Frequency | RSS URL | Focus | Status |
|--------|---------|-----|-----------|-----------|---------|-------|--------|
| Science | Science | science | etoc | weekly | https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science | mixed | ? |
| Science | Science Advances | sci-adv | etoc | continuous | https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciadv | mixed | ? |

## Cell Press

Pattern: `https://www.cell.com/<slug>/current.rss` (latest issue; `/inpress.rss` for articles-in-press). **Cloudflare-protected** — same `User-Agent` requirement. Serves RDF (RSS 1.0).

| Family | Journal | Key | Feed type | Frequency | RSS URL | Focus | Status |
|--------|---------|-----|-----------|-----------|---------|-------|--------|
| Cell Press | Cell | cell | current | biweekly | https://www.cell.com/cell/current.rss | mixed | ? |
| Cell Press | Joule | joule | current | monthly | https://www.cell.com/joule/current.rss | high | ? |
| Cell Press | Chem | chem-cell | current | monthly | https://www.cell.com/chem/current.rss | mixed | ? |
| Cell Press | Matter | matter | current | monthly | https://www.cell.com/matter/current.rss | high | ? |

## Wiley

Pattern: `https://onlinelibrary.wiley.com/feed/<eISSN>/most-recent`. The number in the path is the **electronic ISSN without hyphens** (distinct from the `issn` ISSN-L used for Crossref backfill). **Cloudflare-protected** — needs a browser `User-Agent`.

| Family | Journal | Key | Feed type | Frequency | RSS URL | Focus | Status |
|--------|---------|-----|-----------|-----------|---------|-------|--------|
| Wiley | Advanced Materials | adv-materials | journal | continuous | https://onlinelibrary.wiley.com/feed/15214095/most-recent | high | ? |
| Wiley | Advanced Energy Materials | adv-energy-mater | journal | continuous | https://onlinelibrary.wiley.com/feed/16146840/most-recent | high | ? |
| Wiley | Advanced Functional Materials | adv-funct-mater | journal | continuous | https://onlinelibrary.wiley.com/feed/16163028/most-recent | high | ? |
| Wiley | Angewandte Chemie International Edition | angew-chem | journal | continuous | https://onlinelibrary.wiley.com/feed/15213773/most-recent | mixed | ? |
| Wiley | Small | small | journal | continuous | https://onlinelibrary.wiley.com/feed/16136829/most-recent | high | ? |
| Wiley | Macromolecular Rapid Communications | macromol-rapid-commun | journal | continuous | https://onlinelibrary.wiley.com/feed/15213927/most-recent | high | ? |

## ACS

Pattern: `https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=<code>` (e.g. `nalefd`, `ancac3`, `mamobx`, `amlccd`, `bomaf6`, `orlef7`). **Cloudflare-protected** — needs a browser `User-Agent`. Serves RDF (RSS 1.0).

| Family | Journal | Key | Feed type | Frequency | RSS URL | Focus | Status |
|--------|---------|-----|-----------|-----------|---------|-------|--------|
| ACS | ACS Energy Letters | acs-energy-lett | etoc | continuous | https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=aelccp | high | ? |
| ACS | ACS Nano | acs-nano | etoc | continuous | https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=ancac3 | high | ? |
| ACS | Journal of the American Chemical Society | jacs | etoc | continuous | https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=jacsat | mixed | ? |
| ACS | Nano Letters | nano-letters | etoc | continuous | https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=nalefd | high | ? |
| ACS | Chemistry of Materials | chem-mater | etoc | continuous | https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=cmatex | high | ? |
| ACS | ACS Macro Letters | acs-macro-lett | etoc | continuous | https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=amlccd | high | ? |
| ACS | Biomacromolecules | biomacromolecules | etoc | continuous | https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=bomaf6 | high | ? |
| ACS | Macromolecules | macromolecules | etoc | continuous | https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=mamobx | high | ? |
| ACS | Organic Letters | org-lett | etoc | continuous | https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=orlef7 | mixed | ? |

## RSC

Pattern: `http://feeds.rsc.org/rss/<CODE>` (uppercase code: `EE`, `TA`, `TB`, `TC`, `MH`, `NR`, `PY`). **HTTP-only** — `https://feeds.rsc.org` does not respond, and the cert chain trips strict TLS validation, so do not force an HTTPS upgrade.

| Family | Journal | Key | Feed type | Frequency | RSS URL | Focus | Status |
|--------|---------|-----|-----------|-----------|---------|-------|--------|
| RSC | Energy & Environmental Science | ees | journal | monthly | http://feeds.rsc.org/rss/EE | high | ? |
| RSC | Materials Horizons | mater-horizons | journal | monthly | http://feeds.rsc.org/rss/MH | high | ? |
| RSC | Journal of Materials Chemistry A | jmca | journal | continuous | http://feeds.rsc.org/rss/TA | high | ? |
| RSC | Journal of Materials Chemistry C | jmcc | journal | continuous | http://feeds.rsc.org/rss/TC | high | ? |
| RSC | Nanoscale | nanoscale | journal | continuous | http://feeds.rsc.org/rss/NR | high | ? |
| RSC | Journal of Materials Chemistry B | jmcb | journal | continuous | http://feeds.rsc.org/rss/TB | high | ? |
| RSC | Polymer Chemistry | polym-chem | journal | continuous | http://feeds.rsc.org/rss/PY | high | ? |

## Elsevier (ScienceDirect)

Pattern: `https://rss.sciencedirect.com/publication/science/<ISSN-no-hyphens>`. Use the **print ISSN** digits (the eISSN-keyed URL does not resolve). Returns RSS 2.0; the `<title>` element sits in a slightly different position, so the parser may need care.

| Family | Journal | Key | Feed type | Frequency | RSS URL | Focus | Status |
|--------|---------|-----|-----------|-----------|---------|-------|--------|
| Elsevier | Progress in Polymer Science | prog-polym-sci | journal | monthly | https://rss.sciencedirect.com/publication/science/00796700 | high | ? |
| Elsevier | Materials Today | mater-today | journal | monthly | https://rss.sciencedirect.com/publication/science/13697021 | high | ? |
| Elsevier | Nano Energy | nano-energy | journal | continuous | https://rss.sciencedirect.com/publication/science/22112855 | high | ? |
| Elsevier | Acta Materialia | acta-mater | journal | continuous | https://rss.sciencedirect.com/publication/science/13596454 | high | ? |
| Elsevier | Polymer | polymer | journal | continuous | https://rss.sciencedirect.com/publication/science/00323861 | high | ? |

## Oxford Academic

Pattern: `https://academic.oup.com/rss/site_<SITEID>/<NODEID>.xml`. The numeric site/node IDs come from the journal's RSS page. Advance-access and open-access variants also exist (`advanceAccess_<NODEID>.xml`, `OpenAccess.xml`).

| Family | Journal | Key | Feed type | Frequency | RSS URL | Focus | Status |
|--------|---------|-----|-----------|-----------|---------|-------|--------|
| Oxford | National Science Review | nsr | current | monthly | https://academic.oup.com/rss/site_5332/3198.xml | mixed | ? |

## Other

Society / domestic flagship journals on miscellaneous platforms. CCS Chemistry (Chinese Chemical Society) runs on Atypon, so the ACS-style `showFeed` action works on its domain; it needs a browser `User-Agent` and serves RDF (RSS 1.0). The older `/rss/*.xml` paths return HTTP 410.

| Family | Journal | Key | Feed type | Frequency | RSS URL | Focus | Status |
|--------|---------|-----|-----------|-----------|---------|-------|--------|
| Other | CCS Chemistry | ccs-chem | etoc | monthly | https://www.chinesechemsoc.org/action/showFeed?type=etoc&feed=rss&jc=ccschem | mixed | ? |

<!--
Maintenance:
  - Add a feed: add a row here AND a matching entry in config/journals.json
    (key/label/family/frequency/feeds[]). A journal may declare multiple feed rows.
  - Frequency drives polling cadence; keep it in sync between this table and
    journals.json. Allowed values: continuous | weekly | biweekly | monthly (daily).
  - Verify links: `mat-trend check-feeds --check` probes every feed and reports
    live/dead; `mat-trend check-feeds` (no flag) lists each feed's frequency.
  - Ingest: `mat-trend ingest` polls only journals that are due; `--force` polls all.
  - Cloudflare/Atypon (Science, Cell, Wiley, ACS, CCS Chem) need a browser User-Agent.
  - RSC feeds are HTTP-only (feeds.rsc.org). Elsevier feeds key on the PRINT ISSN.
  - journals.json is ordered by impact_factor (the site preserves that order).
-->
