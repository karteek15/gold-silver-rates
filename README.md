# Live gold & silver rates — city-wise (India)

An always-current JSON file of gold and silver rates across 29 Indian cities,
sourced from [goldmeter.in](https://goldmeter.in).

GoldMeter publishes **no public API** — no docs, no endpoint, no key. This repo
extracts the data from their pages and republishes it as a stable JSON file
that refreshes automatically.

---

## The live URL

Once set up, this URL always holds the latest rates:

```
https://raw.githubusercontent.com/<YOUR-USERNAME>/<YOUR-REPO>/main/rates.json
```

Replace `<YOUR-USERNAME>` and `<YOUR-REPO>` with your own. A CSV is also
published at `rates.csv`.

Updates run twice daily — **06:30 and 14:30 IST**.

---

## Setup (about 5 minutes)

1. Create a new GitHub repository.
2. Upload these files, keeping the folder structure:
   ```
   goldmeter_rates.py
   README.md
   .github/workflows/update-rates.yml
   ```
3. In the repo: **Settings → Actions → General → Workflow permissions** →
   select **Read and write permissions** → Save.
   *(Without this the job cannot commit the updated file.)*
4. Go to the **Actions** tab → *Update gold & silver rates* → **Run workflow**.
5. After ~2 minutes, `rates.json` appears in the repo. That's your live URL.

From then on it updates itself. No server, no cost.

---

## Using it

**JavaScript**
```js
const URL = "https://raw.githubusercontent.com/USER/REPO/main/rates.json";

const res  = await fetch(URL);
const data = await res.json();

const chennai = data.cities.find(c => c.slug === "chennai");
console.log(chennai.gold_22k_per_10g);   // 22K, per 10 grams
console.log(chennai.silver_per_kg);      // silver, per kg
```

**Python**
```python
import requests

data = requests.get("https://raw.githubusercontent.com/USER/REPO/main/rates.json").json()
rates = {c["slug"]: c for c in data["cities"]}

print(rates["mumbai"]["gold_24k_per_gram"])
print(data["scraped_at"])   # always check freshness
```

---

## Data shape

```jsonc
{
  "source": "https://goldmeter.in",
  "scraped_at": "2026-07-19T09:00:00+00:00",   // UTC — check this for freshness
  "currency": "INR",
  "count": 29,
  "cities": [
    {
      "city": "Chennai",
      "slug": "chennai",
      "gold_24k_per_gram": 14329,
      "gold_22k_per_gram": 13135,
      "gold_18k_per_gram": 10747,
      "gold_24k_per_10g": 143290,
      "gold_22k_per_10g": 131350,
      "gold_18k_per_10g": 107470,
      "silver_per_gram": 235,
      "silver_per_kg": 235000,
      "gold_24k_source": "scraped",
      "gold_22k_source": "scraped",          // or "derived_from_24k"
      "status": "ok"
    }
  ]
}
```

### The `_source` fields matter

- `scraped` — read directly from GoldMeter.
- `derived_from_24k` — GoldMeter didn't publish that karat clearly on that
  city's page, so it was computed as `24K × purity ratio`. Accurate to within a
  few rupees of their own figure.

18K is almost always derived. 22K is derived for most cities.

---

## Cities covered

Ahmedabad · Ayodhya · Bangalore · Bhubaneswar · Chandigarh · Chennai ·
Coimbatore · Delhi · Hyderabad · Jaipur · Kerala · Kolkata · Lucknow ·
Madurai · Mangalore · Moodbidri · Mumbai · Mysore · Nagpur · Nashik ·
Patna · Pune · Rajkot · Salem · Surat · Trichy · Vadodara · Vijayawada ·
Visakhapatnam

---

## Running it manually

```bash
pip install requests beautifulsoup4

python goldmeter_rates.py                        # all cities → goldmeter_rates.json
python goldmeter_rates.py --cities chennai pune  # selected cities only
python goldmeter_rates.py --csv rates.csv        # also write CSV
python goldmeter_rates.py --delay 3              # slower, gentler on the site
```

---

## Things to know before depending on this

- **It reads HTML.** If GoldMeter redesigns their site, parsing may break. The
  workflow runs sanity checks and fails loudly rather than publishing bad data —
  so watch for failed Actions runs.
- **It's second-hand data.** GoldMeter aggregates IBJA and MCX. For anything
  where money moves, source from IBJA directly.
- **Rates are indicative.** They exclude making charges and GST. GoldMeter says
  the same on their own site.
- **Check the terms.** Review <https://goldmeter.in/terms> before commercial use.
- **Always read `scraped_at`.** If it's stale, the updater has stopped —
  don't silently serve old prices.
