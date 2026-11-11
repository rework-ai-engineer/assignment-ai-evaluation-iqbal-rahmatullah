import argparse
import csv
import json
import os
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYSTEM = HERE.parent / "system"
PORT = 8000

ap = argparse.ArgumentParser()
ap.add_argument("--scenarios", default=str(HERE / "evaluation_test_scenarios.csv"))
ap.add_argument("--out", default=str(HERE / "evaluation_results.csv"))
ap.add_argument("--raw", default=str(HERE / "raw_results.json"))
ap.add_argument("--force", action="store_true", help="timpa output yang sudah ada")
ap.add_argument("--only", help="id skenario dipisah koma, mis. EVAL-01,EVAL-10")
ap.add_argument("--repeat", type=int, default=1, help="ulang seluruh skenario N kali (bergantian, bukan berturut-turut)")
ap.add_argument("--pause", type=float, default=0.0, help="jeda detik antar request (menghindari rate limit)")
ap.add_argument("--skip-index", action="store_true", help="jangan bangun index di awal (31 request embedding); untuk skenario tiket saja")
args = ap.parse_args()

args.scenarios, args.out, args.raw = (str(Path(p).resolve()) for p in (args.scenarios, args.out, args.raw))
for p in (args.out, args.raw):
    if not Path(p).parent.is_dir():
        sys.exit(f"folder output tidak ada: {Path(p).parent}")
for p in (args.out, args.raw):
    if Path(p).exists() and not args.force:
        sys.exit(f"{p} sudah ada; pakai --out/--raw lain atau --force (jangan timpa bukti 'before').")
with socket.socket() as s:
    if s.connect_ex(("127.0.0.1", PORT)) == 0:
        sys.exit(f"port {PORT} sudah dipakai")

os.chdir(SYSTEM)
sys.path.insert(0, str(SYSTEM))

# Import di bawah sengaja setelah chdir/sys.path (app/ ada di system/).
import requests  # noqa: E402
import uvicorn  # noqa: E402
from google.genai import _api_client as ac  # noqa: E402
from google.genai import models as gm  # noqa: E402
from app import rag  # noqa: E402
from app.main import app  # noqa: E402

REC: dict = {}


def new_rec():
    REC.clear()
    REC.update(embed_s=[], embed_attempts=0, llm_attempts=0, llm_called=False)


_embed0, _gen0 = gm.Models.embed_content, gm.AsyncModels.generate_content
_once0, _aonce0 = ac.BaseApiClient._request_once, ac.BaseApiClient._async_request_once
_search0 = rag.semantic_search


def _embed(self, *a, **kw):
    t = time.perf_counter()
    try:
        return _embed0(self, *a, **kw)
    finally:
        REC["embed_s"].append(time.perf_counter() - t)


async def _gen(self, *a, **kw):
    t = time.perf_counter()
    try:
        resp = await _gen0(self, *a, **kw)
    except Exception as e:
        REC["llm_error"] = f"{type(e).__name__}: {e}"[:300]
        raise
    finally:
        REC["llm_s"] = REC.get("llm_s", 0.0) + time.perf_counter() - t
    u = resp.usage_metadata
    c = kw.get("contents")
    REC.update(
        llm_called=True, prompt=c if isinstance(c, str) else None,
        prompt_tokens=u.prompt_token_count, output_tokens=u.candidates_token_count,
        thinking_tokens=u.thoughts_token_count, total_tokens=u.total_token_count,
    )
    return resp


def _once(self, *a, **kw):
    REC["embed_attempts"] += 1
    return _once0(self, *a, **kw)


async def _aonce(self, *a, **kw):
    REC["llm_attempts"] += 1
    return await _aonce0(self, *a, **kw)


def _search(query, top_k=3):
    t = time.perf_counter()
    try:
        res = _search0(query, top_k)
    finally:
        REC["retrieval_s"] = time.perf_counter() - t
    REC["hits"] = [{"faq_id": h["faq_id"], "score": round(h["score"], 4)} for h in res]
    return res


gm.Models.embed_content, gm.AsyncModels.generate_content = _embed, _gen
ac.BaseApiClient._request_once, ac.BaseApiClient._async_request_once = _once, _aonce
rag.semantic_search = _search  # answer_from_knowledge_base memanggilnya lewat nama global modul

cold = None  # --skip-index: hanya untuk skenario jalur tiket (tanpa embedding)
if not args.skip_index:
    new_rec()
    t = time.perf_counter()
    rag.build_index()
    cold = {"build_index_s": round(time.perf_counter() - t, 3), "embed_attempts": REC["embed_attempts"]}
    print(f"cold start (build index 31 FAQ): {cold['build_index_s']} dtk, percobaan HTTP: {cold['embed_attempts']}")

srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
srv_thread = threading.Thread(target=srv.run, daemon=True)
srv_thread.start()
while not srv.started:
    time.sleep(0.05)

rows = list(csv.reader(open(args.scenarios, encoding="utf-8")))[1:]
if args.only:
    rows = [r for r in rows if r[0] in set(args.only.split(","))]
if not rows:
    sys.exit("tidak ada skenario terpilih")
rows = rows * args.repeat
results = []
try:
    for r in rows:
        sid, cat, query, focus, note = r[:5]
        if len(r) > 5 and r[5]:  # catatan terpotong tumpah ke kolom ke-6 (koma tanpa kutip di file sumber)
            note += "," + r[5]
        new_rec()
        t = time.perf_counter()
        try:
            resp = requests.post(f"http://127.0.0.1:{PORT}/ask", json={"query": query}, timeout=120)
            http_status, body = resp.status_code, resp.json()
            err = None
        except Exception as e:  # timeout / koneksi / JSON rusak
            http_status, body, err = None, {}, f"{type(e).__name__}: {e}"[:300]
        dt = time.perf_counter() - t
        ret, llm = REC.get("retrieval_s") or 0.0, REC.get("llm_s") or 0.0
        hits = REC.get("hits") or []
        results.append({
            "scenario_id": sid, "category": cat, "query": query, "expected_behavior_note": note,
            "http_status": http_status, "intent": body.get("intent"), "status": body.get("status"),
            "response": body.get("data") if err is None else err,
            "response_time_s": round(dt, 3),
            "retrieval_s": round(ret, 3) if "retrieval_s" in REC else None,
            "llm_call_s": round(llm, 3) if REC["llm_called"] or "llm_error" in REC else None,
            "other_s": round(dt - ret - llm, 3),
            "llm_called": REC["llm_called"], "embed_attempts": REC["embed_attempts"], "llm_attempts": REC["llm_attempts"],
            "top_faq_ids": ";".join(str(h["faq_id"]) for h in hits) or None,
            "top_score": hits[0]["score"] if hits else None,
            "prompt_chars": len(REC["prompt"]) if REC.get("prompt") else None,
            "prompt_tokens": REC.get("prompt_tokens"), "output_tokens": REC.get("output_tokens"),
            "thinking_tokens": REC.get("thinking_tokens"), "total_tokens": REC.get("total_tokens"),
            "observasi_awal": "",  # diisi manual setelah hasil dibaca
            "_raw": {"hits": hits, "embed_s": [round(x, 3) for x in REC["embed_s"]],
                     "prompt": REC.get("prompt"), "llm_error": REC.get("llm_error")},
        })
        print(f"{sid} HTTP {http_status} {dt:6.2f}s retr={ret:5.2f} llm={llm:5.2f} "
              f"att(e/l)={REC['embed_attempts']}/{REC['llm_attempts']} tok={REC.get('total_tokens')}  {query[:45]!r}")
        time.sleep(args.pause)
finally:
    srv.should_exit = True
    srv_thread.join(timeout=10)

cols = [k for k in results[0] if not k.startswith("_")]
with open(args.out, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(results)
meta = {
    "run_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "gen_model": rag.GEN_MODEL, "embed_model": rag.EMBED_MODEL, "min_score": rag.MIN_SCORE,
    "python": sys.version.split()[0], "cold_start": cold,
}
Path(args.raw).write_text(json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nTersimpan: {args.out}\n           {args.raw}")
