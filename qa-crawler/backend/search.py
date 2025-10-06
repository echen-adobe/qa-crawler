# lambda_search.py
import os, json, re, pathlib, datetime, mimetypes
from typing import List, Dict

# --------- tiny index in memory (built at cold start) ----------
DOCS: List[Dict] = []

TEXT_EXTS = {".json"}
DATA_DIR = os.environ.get("DATA_DIR", "data")
CLOUDFRONT_DOMAIN = os.environ.get("CLOUDFRONT_DOMAIN", "assets.local.test")

def _read_text(p: pathlib.Path) -> str:
    try:
        raw = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        raw = ""
    # crude HTML strip for .html
    if p.suffix.lower() in {".html", ".htm"}:
        raw = re.sub(r"<script.*?</script>", "", raw, flags=re.S|re.I)
        raw = re.sub(r"<style.*?</style>", "", raw, flags=re.S|re.I)
        raw = re.sub(r"<[^>]+>", " ", raw)
    return raw

def _detect_content_type(p: pathlib.Path) -> str:
    return mimetypes.guess_type(p.name)[0] or "text/plain"

def _index_local_files():
    root = pathlib.Path(DATA_DIR)
    if not root.exists():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_EXTS:
            continue
        text = _read_text(path)
        rel_key = str(path.relative_to(root)).replace("\\", "/")
        DOCS.append({
            "key": rel_key,
            "title": path.name,
            "path": str(path.parent).replace("\\", "/"),
            "content": text,
            "size": path.stat().st_size,
            "contentType": _detect_content_type(path),
            "lastModified": datetime.datetime.fromtimestamp(path.stat().st_mtime, tz=datetime.timezone.utc).isoformat(),
            "tags": [],  # you can add tags by convention, e.g., folder names
        })

_index_local_files()

# --------- search helpers ----------
def _score(doc: Dict, q: str) -> float:
    """very naive scoring: title hit > path hit > content hits count"""
    ql = q.lower()
    score = 0.0
    if ql in (doc.get("title") or "").lower():
        score += 5.0
    if ql in (doc.get("path") or "").lower():
        score += 2.0
    # count occurrences in content (cap)
    cnt = (doc.get("content") or "").lower().count(ql)
    score += min(cnt, 5) * 1.0
    return score

def _passes_filters(doc: Dict, params: Dict) -> bool:
    ct = params.get("contentType")
    if ct and doc.get("contentType") != ct:
        return False
    prefix = params.get("prefix")
    if prefix and not (doc.get("path","").startswith(prefix) or doc.get("key","").startswith(prefix)):
        return False
    tag = params.get("tag")
    if tag and tag not in doc.get("tags", []):
        return False
    return True

def _highlight(content: str, q: str, max_len: int = 120) -> List[str]:
    if not content or not q:
        return []
    cl = content
    ql = q.lower()
    lower = cl.lower()
    out = []
    start = 0
    # find up to 2 snippets
    for _ in range(2):
        i = lower.find(ql, start)
        if i == -1:
            break
        left = max(0, i - max_len // 2)
        right = min(len(cl), i + len(q) + max_len // 2)
        snippet = cl[left:right]
        # basic emphasis; escape angle brackets to avoid any HTML execute
        snippet = snippet.replace("<", "&lt;").replace(">", "&gt;")
        # bold the exact match region (best-effort)
        pat = re.escape(q)
        snippet = re.sub(pat, lambda m: f"<em>{m.group(0)}</em>", snippet, flags=re.I)
        out.append(snippet)
        start = i + len(q)
    return out

def _cf_url(key: str) -> str:
    # just make it clickable; for prod you might sign it or swap to real domain
    return f"https://{CLOUDFRONT_DOMAIN}/{key}"

# --------- Lambda handler (API Gateway proxy) ----------
def handler(event, _context):
    # support both GET and POST test styles
    params = event.get("queryStringParameters") or {}
    if not params and event.get("body"):
        try:
            body = json.loads(event["body"])
            params = body if isinstance(body, dict) else {}
        except Exception:
            params = {}

    q = (params.get("q") or "").strip()
    try:
        frm = int(params.get("from", "0"))
        size = min(int(params.get("size", "10")), 50)
    except ValueError:
        frm, size = 0, 10

    # filter & score
    if q:
        candidates = [d for d in DOCS if _passes_filters(d, params)]
        scored = [(d, _score(d, q)) for d in candidates]
        scored = [x for x in scored if x[1] > 0.0]
        scored.sort(key=lambda t: t[1], reverse=True)
        hits = [d for d, _s in scored]
    else:
        hits = [d for d in DOCS if _passes_filters(d, params)]

    total = len(hits)
    page = hits[frm:frm+size]

    results = []
    for d in page:
        results.append({
            "score": _score(d, q) if q else None,
            "key": d["key"],
            "title": d["title"],
            "url": _cf_url(d["key"]),
            "size": d["size"],
            "contentType": d["contentType"],
            "lastModified": d["lastModified"],
            "highlight": _highlight(d.get("content",""), q)
        })

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps({"total": total, "results": results})
    }
