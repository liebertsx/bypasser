import os
import random
import re
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request

targetHost = "https://app.khaddavi.net"
userAgent = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36"
)

app = Flask(__name__)


def getXsrf(session, domain):
    for cookie in session.cookies:
        if cookie.name == "XSRF-TOKEN" and domain in cookie.domain:
            return unquote(cookie.value)
    return ""


def extractDestination(html):
    match = re.search(r'window\.location\.href\s*=\s*["\']([^"\']+)["\']', html)
    if not match:
        match = re.search(
            r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+url=([^"\'>\s]+)',
            html,
            re.I,
        )
    if not match:
        return None
    return match.group(1).replace("\\/", "/")


def resolve(slug):
    session = requests.Session()
    session.headers.update({
        "User-Agent": userAgent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })

    page = session.get(f"https://sfl.gl/{slug}", timeout=30)
    form = BeautifulSoup(page.text, "html.parser").find("form")
    if not form:
        raise ValueError("no form on short-link page")

    action = urljoin(page.url, form.get("action") or page.url)
    formData = {
        field.get("name"): field.get("value", "")
        for field in form.find_all("input")
        if field.get("name")
    }
    landed = session.get(action, params=formData, timeout=30, allow_redirects=True)

    referer = landed.url
    if "khaddavi" not in referer:
        raise ValueError(f"did not land on {targetHost}, got {referer}")

    xsrf = getXsrf(session, "khaddavi")
    if not xsrf:
        raise ValueError("no XSRF-TOKEN for app.khaddavi.net")

    apiHeaders = {
        "Content-Type": "application/json",
        "X-XSRF-TOKEN": xsrf,
        "Origin": targetHost,
        "Referer": referer,
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
    }

    session.post(
        f"{targetHost}/api/verify",
        headers=apiHeaders,
        json={"_a": 0, "captcha": "", "passcode": ""},
        timeout=30,
    )

    key = random.randint(0, 999)
    size = f"{3840 + key * 2}.{2160 + key * 2}"
    go = session.post(
        f"{targetHost}/api/go",
        headers=apiHeaders,
        json={"key": key, "size": size},
        timeout=30,
    ).json()

    goUrl = go.get("url")
    if not goUrl:
        raise ValueError("no url in /api/go response")

    ready = session.get(goUrl, timeout=30, allow_redirects=True)
    final = extractDestination(ready.text)
    if not final:
        raise ValueError("destination not found")

    return final


@app.get("/bypass")
def resolveEndpoint():
    slug = request.args.get("slug")
    if not slug:
        url = request.args.get("url", "")
        slug = url.rstrip("/").split("/")[-1]
    if not slug:
        return jsonify(error="missing slug"), 400

    try:
        return jsonify(slug=slug, url=resolve(slug))
    except Exception as err:
        return jsonify(error=str(err)), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
