"""
Download and import adult-content blocklists into the database.
Sources:
  - OISD NSFW  (nsfw.oisd.nl)  — ~1 M adult domains
  - StevenBlack porn alternate  — additional coverage
Run daily via cron or GitHub Actions.
"""
import os, time, logging, requests
import db
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("updater")

PH = "%s" if os.getenv("DATABASE_URL") else "?"

SOURCES = [
    {
        "name":     "oisd-nsfw",
        "url":      "https://nsfw.oisd.nl/domainswild",
        "category": "adult",
        "format":   "wildcard",  # *.domain.com  or  domain.com
    },
    {
        "name":     "stevenblack-porn",
        "url":      "https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/porn/hosts",
        "category": "adult",
        "format":   "hosts",     # 0.0.0.0 domain.com
    },
]


def parse_domains(text: str, fmt: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if fmt == "hosts":
            parts = line.split()
            if len(parts) >= 2 and parts[0] in ("0.0.0.0", "127.0.0.1"):
                d = parts[1].lower().strip(".")
                if d and d not in ("localhost", "localhost.localdomain", "local", "broadcasthost"):
                    out.append(d)
        elif fmt == "wildcard":
            d = line.lstrip("*.").lower().strip(".")
            if d:
                out.append(d)
    return out


def update_source(source: dict) -> int:
    log.info(f"Downloading {source['name']}…")
    try:
        r = requests.get(source["url"], timeout=60)
        r.raise_for_status()
    except Exception as e:
        log.error(f"Download failed for {source['name']}: {e}")
        return 0

    domains = parse_domains(r.text, source["format"])
    log.info(f"{source['name']}: {len(domains):,} domains parsed")

    if os.getenv("DATABASE_URL"):
        sql = (
            f"INSERT INTO blocklist (domain, category, source) "
            f"VALUES ({PH},{PH},{PH}) ON CONFLICT (domain) DO NOTHING"
        )
    else:
        sql = f"INSERT OR IGNORE INTO blocklist (domain, category, source) VALUES ({PH},{PH},{PH})"

    data = [(d, source["category"], source["name"]) for d in domains]
    BATCH = 1000
    for i in range(0, len(data), BATCH):
        db.executemany(sql, data[i:i + BATCH])

    log.info(f"{source['name']}: done")
    return len(domains)


if __name__ == "__main__":
    db.init_db()
    total = 0
    for source in SOURCES:
        total += update_source(source)
        time.sleep(2)
    log.info(f"Update complete — {total:,} entries processed")
