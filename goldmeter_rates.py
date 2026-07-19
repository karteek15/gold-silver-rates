#!/usr/bin/env python3
"""
goldmeter_rates.py
Fetches city-wise GOLD and SILVER rates from goldmeter.in and writes JSON.

NOTE: GoldMeter publishes no public API - no docs, no endpoint, no key.
This reads their public pages instead.
  Strategy 1: internal Next.js JSON endpoint (cleanest, when available)
  Strategy 2: parse the rendered HTML

Setup:
    pip install requests beautifulsoup4

Usage:
    python goldmeter_rates.py
    python goldmeter_rates.py --cities chennai mumbai delhi
    python goldmeter_rates.py --out rates.json --delay 2
    python goldmeter_rates.py --csv rates.csv

Works in Google Colab too - just call main() directly.

Please keep the delay and cache results. Check https://goldmeter.in/terms
before using in production. GoldMeter aggregates IBJA data; for anything
business-critical, source from IBJA directly.
"""

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

BASE = "https://goldmeter.in"

CITIES = [
    "ahmedabad", "ayodhya", "bangalore", "bhubaneswar", "chandigarh",
    "chennai", "coimbatore", "delhi", "hyderabad", "jaipur", "kerala",
    "kolkata", "lucknow", "madurai", "mangalore", "moodbidri", "mumbai",
    "mysore", "nagpur", "nashik", "patna", "pune", "rajkot", "salem",
    "surat", "trichy", "vadodara", "vijayawada", "visakhapatnam",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}

# A real per-gram gold rate is 5 figures. Anything smaller on these pages is
# a making charge, not a rate - this floor is what stops the two being confused.
GOLD_FLOOR = 5000
SILVER_FLOOR = 50
SILVER_CEIL = 5000

PURITY = {"22": 22 / 24, "18": 18 / 24}   # relative to 24K


def to_num(text):
    """'1,31,350' -> 131350.0 (handles Indian lakh grouping)"""
    if text is None:
        return None
    m = re.search(r"([\d,]+(?:\.\d+)?)", str(text))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def get_build_id(session):
    """Next.js buildId - changes on every deploy, so read it live."""
    try:
        r = session.get(BASE, headers=HEADERS, timeout=20)
        r.raise_for_status()
        m = re.search(r'"buildId"\s*:\s*"([^"]+)"', r.text)
        if m:
            return m.group(1)
        tag = BeautifulSoup(r.text, "html.parser").find("script", id="__NEXT_DATA__")
        if tag and tag.string:
            return json.loads(tag.string).get("buildId")
    except Exception as e:
        print(f"  buildId lookup failed: {e}", file=sys.stderr)
    return None


def try_json_endpoint(session, build_id, path):
    if not build_id:
        return None
    try:
        r = session.get(f"{BASE}/_next/data/{build_id}/{path}.json",
                        headers=HEADERS, timeout=20)
        if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
            return r.json()
    except Exception:
        pass
    return None


def parse_page(session, url):
    r = session.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    txt = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
    out = {}

    for karat, key in (("24", "gold_24k_per_gram"),
                       ("22", "gold_22k_per_gram"),
                       ("18", "gold_18k_per_gram")):
        # Preferred phrasing: "Rs 14,329 per gram for 24K"
        m = re.search(
            rf"(?:\u20b9|Rs\.?\s?)([\d,]+)\s*(?:per gram|/gram)\s*for\s*{karat}",
            txt, re.I)
        # Fallback: "24K Rs 14,329"  -- {5,} is critical: it requires 5+ digits
        # so 3-digit making charges can never match here.
        if not m:
            m = re.search(
                rf"{karat}\s*K[^\d\u20b9]{{0,20}}(?:\u20b9|Rs\.?\s?)([\d,]{{5,}})",
                txt, re.I)
        val = to_num(m.group(1)) if m else None
        if val is not None and val >= GOLD_FLOOR:
            out[key] = val

    m = re.search(
        r"[Ss]ilver[^.\u20b9]{0,40}(?:\u20b9|Rs\.?\s?)([\d,]+)\s*(?:per gram|/gram)",
        txt)
    if m:
        v = to_num(m.group(1))
        if v and SILVER_FLOOR <= v <= SILVER_CEIL:
            out["silver_per_gram"] = v

    m = re.search(r"(?:\u20b9|Rs\.?\s?)([\d,]+)\s*(?:per kg|/kg)", txt, re.I)
    if m:
        v = to_num(m.group(1))
        if v and v >= SILVER_FLOOR * 1000:
            out["silver_per_kg"] = v

    return out


def finalise(rec):
    """Fill gaps by deriving from 24K, and add per-10g figures."""
    k24 = rec.get("gold_24k_per_gram")
    if k24 is None:
        rec["status"] = "no 24K rate found - unusable"
        return rec

    for karat, key in (("22", "gold_22k_per_gram"), ("18", "gold_18k_per_gram")):
        if rec.get(key) is None:
            rec[key] = round(k24 * PURITY[karat])
            rec[f"gold_{karat}k_source"] = "derived_from_24k"
        else:
            rec[key] = round(rec[key])
            rec[f"gold_{karat}k_source"] = "scraped"

    rec["gold_24k_per_gram"] = round(k24)
    rec["gold_24k_source"] = "scraped"

    for karat in ("24", "22", "18"):
        rec[f"gold_{karat}k_per_10g"] = rec[f"gold_{karat}k_per_gram"] * 10

    if rec.get("silver_per_gram") and not rec.get("silver_per_kg"):
        rec["silver_per_kg"] = rec["silver_per_gram"] * 1000

    rec["status"] = "ok"
    return rec


def scrape_city(session, build_id, slug, delay):
    rec = {"city": slug.title(), "slug": slug}
    for kind, path in (("gold", f"gold-rate/{slug}"),
                       ("silver", f"silver-rate/{slug}")):
        data = try_json_endpoint(session, build_id, path)
        if data:
            rec.setdefault("_raw", {})[kind] = data.get("pageProps", data)
        else:
            try:
                rec.update(parse_page(session, f"{BASE}/{path}"))
            except Exception as e:
                rec.setdefault("errors", []).append(f"{kind}: {e}")
        time.sleep(delay)
    return finalise(rec)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", nargs="*", default=CITIES)
    ap.add_argument("--out", default="goldmeter_rates.json")
    ap.add_argument("--csv", default=None, help="also write a CSV here")
    ap.add_argument("--delay", type=float, default=1.5,
                    help="seconds between requests - please be polite")
    args = ap.parse_args(argv if argv is not None else [])

    session = requests.Session()
    build_id = get_build_id(session)
    print(f"buildId: {build_id or 'not found - using HTML fallback'}\n")

    rows = []
    for i, slug in enumerate(args.cities, 1):
        rec = scrape_city(session, build_id, slug, args.delay)
        if rec.get("status") == "ok":
            print(f"[{i}/{len(args.cities)}] {slug:<15} "
                  f"24K {rec['gold_24k_per_gram']:>7,}  "
                  f"22K {rec['gold_22k_per_gram']:>7,} ({rec['gold_22k_source']})")
        else:
            print(f"[{i}/{len(args.cities)}] {slug:<15} FAILED - {rec.get('status')}")
        rows.append(rec)

    payload = {
        "source": BASE,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "currency": "INR",
        "count": len(rows),
        "notes": [
            "GoldMeter has no public API; this data is extracted from their pages.",
            "gold_XXk_source='scraped' = read directly from the site.",
            "gold_XXk_source='derived_from_24k' = computed as 24K x purity ratio.",
            "Derived values may differ from the site by a few rupees (rounding).",
            "GoldMeter aggregates IBJA data. Rates are indicative; confirm with a jeweller.",
        ],
        "cities": rows,
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {args.out}")

    if args.csv:
        cols = ["city", "slug", "gold_24k_per_gram", "gold_22k_per_gram",
                "gold_18k_per_gram", "gold_24k_per_10g", "gold_22k_per_10g",
                "gold_18k_per_10g", "silver_per_gram", "silver_per_kg",
                "gold_22k_source", "status"]
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {args.csv}")

    ok = sum(1 for r in rows if r.get("status") == "ok")
    scraped = sum(1 for r in rows if r.get("gold_22k_source") == "scraped")
    print(f"\n{ok}/{len(rows)} cities OK | 22K scraped directly: {scraped}, derived: {ok - scraped}")
    return payload


if __name__ == "__main__":
    main(sys.argv[1:])
