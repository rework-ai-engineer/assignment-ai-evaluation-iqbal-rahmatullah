"""Eksperimen root cause ISU-B (EVAL-11: query 4 topik ditolak padahal KB punya jawabannya).

Memisahkan dua dugaan:
  H1: retrieval top-3 dari SATU query majemuk tidak mencakup keempat topik (butuh embedding: opsi --retrieval).
  H2: LLM tetap menolak walau konteks sudah mencakup semua topik, karena aturan prompt (hanya panggilan LLM).

Dijalankan terhadap kode "before" lewat --system (snapshot dari git), supaya tidak terpengaruh perbaikan lain.

    .venv/bin/python evaluation/rca_isu_b.py --system PATH_KE_system            # H2, tanpa embedding
    .venv/bin/python evaluation/rca_isu_b.py --system PATH_KE_system --retrieval  # + H1 (memakai kuota embedding)
"""
import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--system", default=str(HERE.parent / "system"))
ap.add_argument("--retrieval", action="store_true", help="jalankan juga bagian yang memakai embedding")
ap.add_argument("--skip-llm-only", action="store_true", help="lewati E2 (konteks pilihan manual), mis. bila sudah pernah dijalankan")
args = ap.parse_args()
os.chdir(Path(args.system).resolve())
sys.path.insert(0, ".")

import pandas as pd  # noqa: E402
from google.genai import types  # noqa: E402
from app import rag  # noqa: E402

QUERY = {r[0]: r for r in csv.reader(open(HERE / "evaluation_test_scenarios.csv", encoding="utf-8"))}["EVAL-11"][2]
TOPICS = {  # kategori KB -> sub-query satu topik
    "Cuti & Absensi": "kebijakan cuti",
    "Akses & Password": "reset password",
    "Perangkat & Equipment": "permintaan perangkat",
    "Onboarding & HR": "proses onboarding",
}
kb = pd.read_csv("data/it_helpdesk_knowledge_base.csv").set_index("faq_id")


def by_ids(ids):
    return [{"faq_id": i, "category": kb.loc[i, "category"], "question": kb.loc[i, "question"], "answer": kb.loc[i, "answer"]} for i in ids]


def covered(hits):
    return sorted({h["category"] for h in hits})


async def ask(hits):
    r = await rag._client.aio.models.generate_content(
        model=rag.GEN_MODEL, contents=rag._build_prompt(QUERY, hits),
        config=types.GenerateContentConfig(system_instruction=rag.PERSONA, temperature=0.2),
    )
    return (r.text or "").strip(), r.usage_metadata.prompt_token_count


async def run_conditions(conds):
    for name, hits, n in conds:
        print(f"\n[{name}] FAQ={[h['faq_id'] for h in hits]} topik tercakup={len(covered(hits))}/4")
        for i in range(n):
            text, ptok = await ask(hits)
            print(f"  run {i + 1}: prompt_tokens={ptok} ditolak={text == rag.NOT_FOUND} | {text[:260]!r}")
            await asyncio.sleep(2)


def merged(per_sub):  # gabung hasil tiap sub-query, buang duplikat, urutan terjaga
    seen, out = set(), []
    for hits in per_sub:
        for h in hits:
            if h["faq_id"] not in seen:
                seen.add(h["faq_id"])
                out.append(h)
    return out


async def main():
    print(f"system: {os.getcwd()}\npersona: {rag.PERSONA[:90]!r}...\nQUERY EVAL-11: {QUERY}")
    if not args.skip_llm_only:
        print("\n=== E2. LLM dengan konteks yang dipilih (tanpa embedding)")
        # FAQ 12, 19, 23 = top-3 retrieval EVAL-11 yang terekam di evaluation_results.csv (kondisi sistem sekarang)
        await run_conditions([
            ("C0 top-3 terekam dari retrieval EVAL-11 (kontrol: harus menolak seperti sistem)", by_ids([12, 19, 23]), 2),
            ("C1 konteks 'oracle' minimal: 1 FAQ per topik", by_ids([1, 12, 14, 19]), 3),
            ("C2 konteks 'oracle' 8 FAQ: 2 per topik", by_ids([1, 2, 8, 12, 14, 15, 19, 31]), 3),
        ])
    if not args.retrieval:
        return
    print("\n=== E1. Retrieval: query majemuk (satu embedding), top-8")
    comp = rag.semantic_search(QUERY, top_k=8)
    for i, h in enumerate(comp, 1):
        print(f"  #{i} FAQ {h['faq_id']:>2} skor={h['score']:.4f} [{h['category']}] {h['question'][:55]}")
    for k in (3, 5, 8):
        print(f"  top-{k}: {len(covered(comp[:k]))}/4 topik tercakup: {covered(comp[:k])}")
    print("\n=== E1b. Retrieval: tiap topik dicari sendiri (top-3)")
    sub = {}
    for cat, sq in TOPICS.items():
        sub[cat] = rag.semantic_search(sq, top_k=3)
        h = sub[cat]
        print(f"  '{sq}': FAQ {[x['faq_id'] for x in h]} skor={[round(x['score'], 3) for x in h]} | peringkat 1 kategori benar: {h[0]['category'] == cat}")
    await run_conditions([
        ("C4 top-6 query majemuk", comp[:6], 3),
        ("C5 top-8 query majemuk", comp[:8], 3),
        ("C6 multi-query: top-2 per topik, digabung", merged([sub[c][:2] for c in TOPICS]), 3),
        ("C7 top-3 query majemuk + top-1 per topik, digabung", merged([comp[:3]] + [sub[c][:1] for c in TOPICS]), 3),
    ])


asyncio.run(main())
