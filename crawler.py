"""
BUKA Crawler — Danish Business Registry (CVR) + Website Scraper
Pulls companies from the official CVR API (virk.dk) and scrapes their
websites for contact emails, descriptions, and qualification signals.

Run: python crawler.py [--limit 1000] [--resume]
"""
import os, re, time, json, sqlite3, argparse, logging
from datetime import datetime
import urllib.request, urllib.parse, urllib.error
from html.parser import HTMLParser

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('buka-crawler')

DB_PATH = os.path.join(os.path.dirname(__file__), 'buka.db')

# CVR API — official Danish business registry, completely free
CVR_URL  = 'https://cvrapi.dk/api'
CVR_USER = 'buka-leadgen'  # required User-Agent identifier

# Industries we care about — SMEs that need marketing/web help
TARGET_INDUSTRIES = [
    '6201',  # Software
    '6202',  # IT consulting
    '4719',  # Retail
    '4711',  # Supermarkets
    '5610',  # Restaurants
    '5630',  # Bars
    '5510',  # Hotels
    '4120',  # Construction
    '4110',  # Development
    '6810',  # Real estate
    '7810',  # Employment
    '8299',  # Business support
    '7420',  # Photography
    '7430',  # Translation
    '8211',  # Office admin
    '5811',  # Book publishing
    '5819',  # Other publishing
    '6312',  # Web portals
    '7311',  # Advertising agencies
    '7312',  # Media sales
    '7320',  # Market research
    '9311',  # Sport
    '9602',  # Hairdressers
    '8621',  # GP/doctors
    '8623',  # Dentists
    '7021',  # PR
    '7022',  # Business consulting
    '4321',  # Electrical
    '4322',  # Plumbing
    '4331',  # Flooring
    '4332',  # Carpentry
    '4333',  # Painting
]

EMAIL_PATTERN = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
    re.IGNORECASE
)

SKIP_EMAIL_DOMAINS = {
    'example.com', 'test.com', 'sentry.io', 'wixpress.com',
    'example.org', 'domain.com', 'email.com',
}


class EmailScraper(HTMLParser):
    """Extract emails and description from an HTML page."""
    def __init__(self):
        super().__init__()
        self.emails = set()
        self.text_chunks = []
        self._in_body = False
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self._skip = True
        attrs_dict = dict(attrs)
        # Extract mailto: links
        href = attrs_dict.get('href', '')
        if href.startswith('mailto:'):
            email = href[7:].split('?')[0].strip()
            if self._valid_email(email):
                self.emails.add(email.lower())

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self._skip = False

    def handle_data(self, data):
        if self._skip:
            return
        # Extract emails from text
        for m in EMAIL_PATTERN.finditer(data):
            e = m.group(0).lower()
            if self._valid_email(e):
                self.emails.add(e)
        if data.strip():
            self.text_chunks.append(data.strip())

    def _valid_email(self, e):
        if not e or '@' not in e:
            return False
        domain = e.split('@')[-1].lower()
        if domain in SKIP_EMAIL_DOMAINS:
            return False
        if domain.endswith('.png') or domain.endswith('.jpg'):
            return False
        return True

    def get_description(self):
        text = ' '.join(self.text_chunks)
        # Return first ~300 chars of meaningful text
        sentences = re.split(r'[.!?]\s+', text)
        desc = '. '.join(s.strip() for s in sentences[:3] if len(s.strip()) > 20)
        return desc[:400] if desc else None


def fetch_url(url, timeout=8):
    """Fetch a URL, return (content_str, final_url) or (None, None)."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'BukaBot/1.0 (lead generation research; contact@buka.dk)',
                'Accept': 'text/html,application/xhtml+xml',
                'Accept-Language': 'da,en;q=0.8',
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get('Content-Type', '')
            if 'text/html' not in content_type and 'text/' not in content_type:
                return None, None
            charset = 'utf-8'
            if 'charset=' in content_type:
                charset = content_type.split('charset=')[-1].strip().split(';')[0]
            try:
                return resp.read(50000).decode(charset, errors='replace'), resp.url
            except:
                return None, None
    except Exception as e:
        return None, None


def scrape_website(url):
    """Visit a company website, extract emails and description."""
    if not url:
        return None, None

    # Normalise URL
    if not url.startswith('http'):
        url = 'https://' + url

    html, final_url = fetch_url(url, timeout=10)
    if not html:
        # Try www variant
        if '//www.' not in url:
            url2 = url.replace('://', '://www.')
            html, final_url = fetch_url(url2, timeout=8)
    if not html:
        return None, None

    parser = EmailScraper()
    try:
        parser.feed(html)
    except:
        pass

    # Pick best email: prefer info@, kontakt@, hej@, hello@
    preferred = None
    for e in parser.emails:
        local = e.split('@')[0].lower()
        if local in ('info', 'kontakt', 'hej', 'hello', 'mail', 'post', 'contact'):
            preferred = e
            break
    email = preferred or (list(parser.emails)[0] if parser.emails else None)
    desc  = parser.get_description()
    return email, desc


def fetch_cvr_batch(offset=0, limit=100, industry=None):
    """Fetch companies from cvrapi.dk."""
    # cvrapi.dk doesn't support bulk search easily
    # Use the official CVR elasticsearch via virk.dk
    # That requires registration — use cvrapi.dk search instead

    # Simpler approach: search by industry code
    if industry:
        url = f"{CVR_URL}?search={industry}&country=dk&type=company"
    else:
        url = f"{CVR_URL}?country=dk&type=company&start={offset}&limit={limit}"

    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': CVR_USER}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return [data] if isinstance(data, dict) and 'vat' in data else []
    except Exception as e:
        log.warning(f'CVR fetch error: {e}')
        return []


def search_cvr_by_name(query):
    """Search CVR by company name."""
    url = f"{CVR_URL}?search={urllib.parse.quote(query)}&country=dk"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': CVR_USER})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except:
        return None


def fetch_cvr_virk(industry_code, size=100, from_=0):
    """
    Query the official virk.dk Elasticsearch API.
    No auth required for basic queries.
    """
    url = 'https://data.virk.dk/datahenter/cvr-permanent/virksomhed/_search'
    query = {
        "from": from_,
        "size": size,
        "_source": ["Vrvirksomhed.cvrNummer", "Vrvirksomhed.navne",
                    "Vrvirksomhed.beliggenhedsadresse",
                    "Vrvirksomhed.telefonNummer",
                    "Vrvirksomhed.elektroniskPost",
                    "Vrvirksomhed.hjemmeside",
                    "Vrvirksomhed.branche",
                    "Vrvirksomhed.virksomhedsstatus",
                    "Vrvirksomhed.stiftelsesDato",
                    "Vrvirksomhed.reklamebeskyttet"],
        "query": {
            "bool": {
                "must": [
                    {"term": {"Vrvirksomhed.virksomhedsstatus": "NORMAL"}},
                ],
                "filter": [
                    {"term": {"Vrvirksomhed.branche.branchekode": industry_code}}
                ]
            }
        }
    }

    body = json.dumps(query).encode()
    try:
        req = urllib.request.Request(
            url, data=body,
            headers={
                'Content-Type': 'application/json',
                'User-Agent': 'BukaBot/1.0',
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.warning(f'virk.dk error for {industry_code}: {e}')
        return None


def parse_virk_hit(hit):
    """Extract company data from a virk.dk elasticsearch hit."""
    v = hit.get('_source', {}).get('Vrvirksomhed', {})

    # Name
    names = v.get('navne', [])
    name = names[0].get('navn', '') if names else ''
    if not name:
        return None

    # Skip ad-protected or closed
    if v.get('reklamebeskyttet'):
        return None

    # CVR
    cvr = str(v.get('cvrNummer', ''))

    # Address
    addr = v.get('beliggenhedsadresse', [{}])
    addr = addr[0] if addr else {}
    city    = addr.get('postdistrikt', '') or addr.get('bynavn', '')
    address = f"{addr.get('vejnavn','')} {addr.get('husnummerFra','')}, {addr.get('postnummer','')} {city}".strip()

    # Phone
    phones = v.get('telefonNummer', [])
    phone  = phones[0].get('kontaktoplysning', '') if phones else ''

    # Email (from CVR, often missing)
    emails = v.get('elektroniskPost', [])
    email  = emails[0].get('kontaktoplysning', '') if emails else ''

    # Website
    sites   = v.get('hjemmeside', [])
    website = sites[0].get('kontaktoplysning', '') if sites else ''

    # Industry
    branches = v.get('branche', [])
    industry = branches[0].get('branchetekst', '') if branches else ''

    # Founded
    founded_str = v.get('stiftelsesDato', '')
    founded = int(founded_str[:4]) if founded_str and len(founded_str) >= 4 else None

    return {
        'cvr': cvr, 'name': name, 'industry': industry,
        'city': city, 'address': address, 'phone': phone,
        'email': email, 'website': website, 'founded': founded,
    }


def save_company(db, data, scraped_email=None, scraped_desc=None):
    """Insert or update a company in the DB."""
    email = data.get('email') or scraped_email or ''
    website = data.get('website') or ''

    # Score: higher = better lead
    score = 0
    if email:      score += 40
    if website:    score += 20
    if data.get('phone'): score += 15
    if data.get('founded') and data['founded'] >= 2015: score += 10  # younger = growing
    if data.get('city') in ('København', 'Aarhus', 'Odense', 'Aalborg'): score += 15

    try:
        db.execute('''
            INSERT OR IGNORE INTO companies
              (cvr, name, industry, city, address, phone, email, website,
               founded, description, score, email_verified, scraped_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            data.get('cvr'), data['name'], data.get('industry'),
            data.get('city'), data.get('address'), data.get('phone'),
            email, website, data.get('founded'),
            scraped_desc, score,
            1 if email else 0,
            datetime.utcnow().isoformat(),
        ))
        # Update if already exists but we got better data
        if email:
            db.execute('''
                UPDATE companies SET email=?, score=?, scraped_at=?, description=COALESCE(description,?)
                WHERE cvr=? AND (email IS NULL OR email="")
            ''', (email, score, datetime.utcnow().isoformat(), scraped_desc, data.get('cvr')))
        return True
    except Exception as e:
        log.warning(f'DB error for {data.get("name")}: {e}')
        return False


def run_crawler(limit=500, scrape_websites=True, industry_codes=None):
    """Main crawler loop."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    codes = industry_codes or TARGET_INDUSTRIES
    total_saved = 0

    for code in codes:
        if total_saved >= limit:
            break

        log.info(f'Fetching industry {code}...')
        from_ = 0
        batch_size = 50

        while total_saved < limit:
            result = fetch_cvr_virk(code, size=batch_size, from_=from_)
            if not result:
                break

            hits = result.get('hits', {}).get('hits', [])
            if not hits:
                break

            for hit in hits:
                company = parse_virk_hit(hit)
                if not company:
                    continue

                # Scrape website for email if missing
                scraped_email, scraped_desc = None, None
                if scrape_websites and company.get('website') and not company.get('email'):
                    scraped_email, scraped_desc = scrape_website(company['website'])
                    if scraped_email:
                        log.info(f'  ✓ {company["name"]} → {scraped_email}')
                    time.sleep(0.5)  # polite delay

                if save_company(db, company, scraped_email, scraped_desc):
                    total_saved += 1

            db.commit()
            log.info(f'  Saved {total_saved} companies so far (industry {code}, offset {from_})')
            from_ += batch_size

            if len(hits) < batch_size:
                break  # exhausted this industry

            time.sleep(1)  # rate limit

    db.close()
    log.info(f'Crawler done. Total saved: {total_saved}')
    return total_saved


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=500)
    parser.add_argument('--no-scrape', action='store_true')
    parser.add_argument('--industries', nargs='+')
    args = parser.parse_args()

    from app import init_db
    init_db()

    run_crawler(
        limit=args.limit,
        scrape_websites=not args.no_scrape,
        industry_codes=args.industries,
    )
