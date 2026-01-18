#!/usr/bin/env python3
"""
Sunnah.com Scraper - Flask API + Telegram WebApp UI

Run:
  pip install flask requests beautifulsoup4 flask-cors
  python app.py

Use:
  http://127.0.0.1:5000/
"""

import re
import time
from typing import List, Dict, Tuple, Optional

import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# ==========

class SunnahScraper:

    def __init__(self, delay_seconds: float = 1.2):
        self.base_url = "https://sunnah.com"
        self.delay_seconds = delay_seconds
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })

    def extract_pagination_info(self, soup) -> Dict:
        pagination_info = {
            "total_results": 0,
            "current_page": 1,
            "total_pages": 1,
            "has_next": False,
            "has_previous": False,
            "results_on_page": 0,
        }

        showing_text = soup.find(string=re.compile(r"Showing\s+\d+-\d+\s+of\s+\d+"))
        if showing_text:
            match = re.search(r"Showing\s+(\d+)-(\d+)\s+of\s+(\d+)", showing_text)
            if match:
                start = int(match.group(1))
                end = int(match.group(2))
                total = int(match.group(3))
                pagination_info["total_results"] = total
                pagination_info["results_on_page"] = end - start + 1
                pagination_info["total_pages"] = (total + 99) // 100

        pager = soup.find("ul", class_="yiiPager")
        if pager:
            current = pager.find("li", class_="page selected")
            if current:
                page_link = current.find("a")
                if page_link:
                    try:
                        pagination_info["current_page"] = int(page_link.get_text(strip=True))
                    except Exception:
                        pass

            next_link = pager.find("li", class_="next")
            if next_link and "hidden" not in (next_link.get("class") or []):
                pagination_info["has_next"] = True

            prev_link = pager.find("li", class_="previous")
            if prev_link and "hidden" not in (prev_link.get("class") or []):
                pagination_info["has_previous"] = True

        return pagination_info

    def extract_complete_hadith(self, hadith_container) -> Dict:
        hadith = {
            "urn": None,
            "collection": None,
            "collection_url": None,
            "book": None,
            "book_url": None,
            "reference": None,
            "hadith_url": None,
            "anchor_name": None,
            "narrator": None,
            "english_text": None,
            "arabic_sanad": None,
            "arabic_text": None,
            "grade_english": None,
            "grade_arabic": None,
            "in_book_reference": None,
            "english_translation_reference": None,
            "usc_msa_reference": None,
            "is_deprecated_numbering": False,
            "page_scraped": None,
        }

        urn_comment = hadith_container.find(string=re.compile(r"URN \[en\] \d+"))
        if urn_comment:
            urn_match = re.search(r"URN \[en\] (\d+)", urn_comment)
            if urn_match:
                hadith["urn"] = urn_match.group(1)

        bc_search = hadith_container.find("div", class_="bc_search")
        if bc_search:
            links = bc_search.find_all("a", class_="nounderline")
            if len(links) >= 1:
                hadith["collection"] = links[0].get_text(strip=True)
                hadith["collection_url"] = self.base_url + (links[0].get("href", "") or "")
            if len(links) >= 2:
                book_text = links[1].get_text(strip=True)
                if " - " in book_text:
                    hadith["book"] = book_text.split(" - ")[0].strip()
                else:
                    hadith["book"] = book_text
                hadith["book_url"] = self.base_url + (links[1].get("href", "") or "")

        ref_sticky = hadith_container.find("div", class_="hadith_reference_sticky")
        if ref_sticky:
            hadith["reference"] = ref_sticky.get_text(strip=True)

        main_link = hadith_container.find("a", href=re.compile(r"/[a-z]+:\d+"))
        if main_link:
            hadith["hadith_url"] = self.base_url + (main_link.get("href", "") or "")

        anchor = hadith_container.find("a", attrs={"name": True})
        if anchor:
            hadith["anchor_name"] = anchor.get("name")

        narrator_div = hadith_container.find("div", class_="hadith_narrated")
        if narrator_div:
            narrator_text = narrator_div.get_text(strip=True)
            narrator_text = re.sub(r"^Narrated\s+", "", narrator_text)
            narrator_text = re.sub(r":$", "", narrator_text)
            hadith["narrator"] = narrator_text

        text_details = hadith_container.find("div", class_="text_details")
        if text_details:
            parts = []
            for elem in text_details.find_all(["p", "div"], recursive=False):
                if "hadith_narrated" not in (elem.get("class") or []):
                    t = elem.get_text(strip=True)
                    if t:
                        parts.append(t)
            hadith["english_text"] = " ".join(parts)

        arabic_div = hadith_container.find("div", class_="arabic_hadith_full")
        if arabic_div:
            arabic_sanad = arabic_div.find("span", class_="arabic_sanad")
            if arabic_sanad:
                hadith["arabic_sanad"] = arabic_sanad.get_text(strip=True)

            arabic_text_details = arabic_div.find("span", class_="arabic_text_details")
            if arabic_text_details:
                hadith["arabic_text"] = arabic_text_details.get_text(strip=True)

        grade_table = hadith_container.find("table", class_="gradetable")
        if grade_table:
            tds = grade_table.find_all("td")
            for td in tds:
                classes = td.get("class") or []
                if "english_grade" in classes:
                    text = td.get_text(strip=True)
                    if text and text != "Grade:":
                        hadith["grade_english"] = text
                elif "arabic_grade" in classes:
                    text = td.get_text(strip=True)
                    if text and "حكم" not in text:
                        hadith["grade_arabic"] = text

        ref_table = hadith_container.find("table", class_="hadith_reference")
        if ref_table:
            rows = ref_table.find_all("tr")
            for row in rows:
                tds = row.find_all("td")
                if len(tds) >= 2:
                    label = tds[0].get_text(strip=True).lower()
                    value = re.sub(r"^\s*:\s*", "", tds[1].get_text(strip=True))

                    if "in-book" in label:
                        hadith["in_book_reference"] = value
                    elif "english translation" in label:
                        hadith["english_translation_reference"] = value
                    elif "usc-msa" in label:
                        hadith["usc_msa_reference"] = value
                        if "deprecated" in row.get_text().lower():
                            hadith["is_deprecated_numbering"] = True

        return hadith

    def scrape_page(self, query: str, page: int = 1) -> Tuple[List[Dict], Dict]:
        url = f"{self.base_url}/search"
        params = {"q": query, "page": page}

        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        pagination_info = self.extract_pagination_info(soup)

        hadiths: List[Dict] = []
        hadith_containers = soup.find_all("div", class_="boh")

        for container in hadith_containers:
            hadith = self.extract_complete_hadith(container)
            if hadith and hadith.get("reference"):
                hadith["pages"] = page
                hadiths.append(hadith)

        return hadiths, pagination_info

    def scrape_all_pages(
        self,
        query: str,
        start_page: int = 1,
        max_pages: Optional[int] = None,
    ) -> List[Dict]:
        all_hadiths: List[Dict] = []
        seen_refs = set()
        current_page = start_page

        while True:
            hadiths, pagination_info = self.scrape_page(query, current_page)
            if not hadiths:
                break

            for h in hadiths:
                ref = h.get("reference")
                if ref and ref not in seen_refs:
                    seen_refs.add(ref)
                    all_hadiths.append(h)

            if max_pages and current_page >= start_page + max_pages - 1:
                break

            if not pagination_info.get("has_next"):
                break

            current_page += 1
            if self.delay_seconds:
                time.sleep(self.delay_seconds)

        return all_hadiths

# ==========

def build_stats(data: List[Dict]) -> Dict:
    collections: Dict[str, int] = {}
    grades: Dict[str, int] = {}

    for h in data:
        coll = h.get("collection") or "Unknown"
        collections[coll] = collections.get(coll, 0) + 1

        grade = h.get("grade_english") or "Not graded"
        grades[grade] = grades.get(grade, 0) + 1

    return {
        "total_hadiths": len(data),
        "by_collection": dict(sorted(collections.items(), key=lambda x: x[1], reverse=True)),
        "by_grade": dict(sorted(grades.items(), key=lambda x: x[1], reverse=True)),
    }

# ==========

app = Flask(__name__, static_folder='static')
CORS(app)
scraper = SunnahScraper(delay_seconds=1.2)

@app.get("/")
def index():
    return send_from_directory('static', 'index.html')

@app.get("/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Missing required query parameter: q"}), 400

    max_pages = request.args.get("max_pages", "").strip()
    max_pages_i: Optional[int] = None
    if max_pages:
        try:
            max_pages_i = max(1, int(max_pages))
        except Exception:
            max_pages_i = None

    try:
        data = scraper.scrape_all_pages(query=q, start_page=1, max_pages=max_pages_i)
    except requests.RequestException as e:
        return jsonify({"error": "Upstream request failed", "details": str(e)}), 502
    except Exception as e:
        return jsonify({"error": "Internal error while scraping", "details": str(e)}), 500

    stats = build_stats(data)
    return jsonify({
        "stats": stats,
        "data": data
    })

# ==========

if __name__ == "__main__":
    import os
    os.makedirs('static', exist_ok=True)
    app.run(host="0.0.0.0", port=5000, debug=True)
