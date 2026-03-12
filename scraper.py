#!/usr/bin/env python3
import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Shared layout selectors for the pages you showed.
# If a field has multiple selectors, the first one with text is used.
SELECTORS: Dict[str, str] = {
    "description": "#contents section.infomation p, section.infomation p, #contents p",
    "logo_url": "#contents aside .logo img::attr(src), aside .logo img::attr(src)",
}


@dataclass
class ScrapeResult:
    url: str
    data: Dict[str, Optional[str]]
    error: Optional[str] = None


def fetch_html(url: str, timeout: int = 20) -> str:
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def fetch_json(url: str, timeout: int = 30) -> Any:
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def parse_selector(selector: str) -> tuple[str, Optional[str]]:
    marker = "::attr("
    if marker not in selector:
        return selector, None

    css_selector, attr_part = selector.rsplit(marker, 1)
    if not attr_part.endswith(")"):
        return selector, None

    attr_name = attr_part[:-1].strip()
    return css_selector.strip(), (attr_name or None)


def extract_fields(
    html: str, selectors: Dict[str, str], page_url: Optional[str] = None
) -> Dict[str, Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")
    out: Dict[str, Optional[str]] = {}

    for field_name, selector in selectors.items():
        css_selector, attr_name = parse_selector(selector)
        text_value: Optional[str] = None

        for node in soup.select(css_selector):
            if attr_name:
                raw_value = node.get(attr_name)
                value = str(raw_value).strip() if raw_value is not None else ""
                if value and page_url and attr_name in {"src", "href"}:
                    value = urljoin(page_url, value)
            else:
                value = node.get_text(" ", strip=True)
            if value:
                text_value = value
                break

        out[field_name] = text_value

    return out


def scrape_one(url: str, selectors: Dict[str, str]) -> ScrapeResult:
    try:
        html = fetch_html(url)
        data = extract_fields(html, selectors, page_url=url)
        return ScrapeResult(url=url, data=data)
    except Exception as exc:
        return ScrapeResult(url=url, data={}, error=str(exc))


def write_csv(path: str, rows: List[ScrapeResult], field_names: List[str]) -> None:
    columns = ["url", *field_names, "error"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            record = {"url": row.url, "error": row.error}
            for field in field_names:
                record[field] = row.data.get(field)
            writer.writerow(record)


def write_json(path: str, rows: List[ScrapeResult]) -> None:
    payload = [
        {
            "url": row.url,
            "data": row.data,
            "error": row.error,
        }
        for row in rows
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def load_urls(url_args: List[str], url_file: Optional[str]) -> List[str]:
    urls: List[str] = []

    for item in url_args:
        if item.strip():
            urls.append(item.strip())

    if url_file:
        with open(url_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)

    deduped = []
    seen = set()
    for url in urls:
        if url not in seen:
            deduped.append(url)
            seen.add(url)

    return deduped


def set_key_before(
    item: Dict[str, Any], key: str, value: Any, before_key: str
) -> Dict[str, Any]:
    ordered: Dict[str, Any] = {}
    inserted = False

    for current_key, current_value in item.items():
        if current_key == before_key and not inserted:
            ordered[key] = value
            inserted = True
        ordered[current_key] = current_value

    if not inserted:
        ordered[key] = value

    return ordered


def enrich_api_records(
    records: List[Dict[str, Any]], selectors: Dict[str, str], workers: int
) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = [dict(item) for item in records]

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {}

        for index, item in enumerate(enriched):
            org_url = item.get("url")
            if not isinstance(org_url, str) or not org_url.strip():
                item = set_key_before(item, "description", None, "is_pre_approved")
                item = set_key_before(item, "logo_url", None, "is_pre_approved")
                item = set_key_before(
                    item,
                    "description_error",
                    "Missing url field",
                    "is_pre_approved",
                )
                enriched[index] = item
                continue

            future = executor.submit(scrape_one, org_url.strip(), selectors)
            future_map[future] = index

        for future in as_completed(future_map):
            index = future_map[future]
            result = future.result()
            item = set_key_before(
                enriched[index],
                "description",
                result.data.get("description"),
                "is_pre_approved",
            )
            item = set_key_before(
                item,
                "logo_url",
                result.data.get("logo_url"),
                "is_pre_approved",
            )
            if result.error:
                item = set_key_before(
                    item,
                    "description_error",
                    result.error,
                    "is_pre_approved",
                )
            enriched[index] = item

    return enriched


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape multiple pages that share the same layout"
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Single URL to scrape (can be used multiple times)",
    )
    parser.add_argument(
        "--urls-file",
        help="Path to a text file with one URL per line",
    )
    parser.add_argument(
        "--api-url",
        help="API endpoint that returns a JSON array with organization records containing a 'url' field",
    )
    parser.add_argument(
        "--out-csv",
        default="results.csv",
        help="Output CSV path (default: results.csv)",
    )
    parser.add_argument(
        "--out-json",
        default="results.json",
        help="Output JSON path (default: results.json)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of parallel workers (default: 8)",
    )

    args = parser.parse_args()

    if args.api_url:
        payload = fetch_json(args.api_url)

        if not isinstance(payload, list):
            parser.error("--api-url must return a JSON array of objects")

        records = [item for item in payload if isinstance(item, dict)]
        if not records:
            parser.error("--api-url returned no object records to enrich")

        enriched = enrich_api_records(records, SELECTORS, args.workers)
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump(enriched, f, indent=2, ensure_ascii=False)

        with_description = sum(1 for item in enriched if item.get("description"))
        print(f"Enriched {with_description}/{len(enriched)} records with descriptions")
        print(f"JSON: {args.out_json}")
        return

    urls = load_urls(args.url, args.urls_file)

    if not urls:
        parser.error("Provide at least one URL via --url or --urls-file")

    field_names = list(SELECTORS.keys())
    results: List[ScrapeResult] = []

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {
            executor.submit(scrape_one, url, SELECTORS): url
            for url in urls
        }
        for future in as_completed(future_map):
            results.append(future.result())

    results.sort(key=lambda x: x.url)

    write_csv(args.out_csv, results, field_names)
    write_json(args.out_json, results)

    success_count = sum(1 for r in results if not r.error)
    print(f"Scraped {success_count}/{len(results)} pages successfully")
    print(f"CSV:  {args.out_csv}")
    print(f"JSON: {args.out_json}")


if __name__ == "__main__":
    main()
