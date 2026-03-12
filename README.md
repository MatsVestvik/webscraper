# Python Web Scraper (Same Layout, Multiple URLs)

This scraper is built for your case:
- multiple links as input
- every page uses the same structure/layout

## 1) Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) Set your selectors

Open `scraper.py` and edit the `SELECTORS` dictionary:

```python
SELECTORS = {
    "title": "h1",
    "price": ".price",
    "description": ".description",
}
```

Use CSS selectors that match your site layout.

## 3) Provide URLs

Option A: pass URLs directly:

```bash
python scraper.py --url "https://example.com/page1" --url "https://example.com/page2"
```

Option B: use a file (recommended):

Create `urls.txt` with one URL per line:

```txt
https://example.com/page1
https://example.com/page2
```

Run:

```bash
python scraper.py --urls-file urls.txt
```

## 3b) Enrich an API JSON (your use case)

If you have an API endpoint that returns a JSON array with a `url` field per object, you can enrich it with `description`:

```bash
python scraper.py --api-url "https://app.innsamlingskontrollen.no/api/public/v1/all" --out-json enriched_orgs.json
```

This writes a similar JSON array where each object includes:
- `description`
- `description_error` (only when scraping failed)

## 4) Output

By default:
- `results.csv`
- `results.json`

Custom output paths:

```bash
python scraper.py --urls-file urls.txt --out-csv out.csv --out-json out.json
```

## Notes

- Failed URLs are included with an `error` value.
- You can tune parallelism with `--workers 4` (or higher).
- Always make sure scraping is allowed by the site terms and robots policy.
