import requests
from flask import Flask, request

app = Flask(__name__)


@app.route("/fetch")
def fetch_url():
    # CVE 模式：CWE-918 SSRF——用户可控 URL 直接请求
    url = request.args.get("url", "")
    resp = requests.get(url)  # sink：line 10
    return resp.text
