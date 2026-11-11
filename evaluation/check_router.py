"""Cek offline (tanpa API) aturan router system/app/router.py.

    .venv/bin/python evaluation/check_router.py     # exit 0 = semua sesuai
"""
import asyncio
import os
import sys
from pathlib import Path

os.chdir(Path(__file__).resolve().parent.parent / "system")
sys.path.insert(0, ".")

from app.router import detect_intent  # noqa: E402

T, F = "ticket_status", "faq"
CASES = [
    # skenario resmi
    ("apa status TICKET-0005?", T),
    ("apa status TICKET-9999?", T),
    ("tiket saya gimana ya?", T),  # EVAL-08 (ISU-A)
    ("kenapa laptop saya lambat dan gimana cara cek tiket yang saya buat soal itu?", T),  # EVAL-09
    ("berapa jatah cuti tahunan saya?", F),
    ("halo", F),
    # rujukan ke tiket milik sendiri tanpa kata aksi (ISU-A)
    ("tiketku gimana ya?", T),
    ("kapan tiket saya selesai?", T),
    ("ticket saya sudah sampai mana", T),
    # tidak boleh jadi ticket_status: pertanyaan cara / kebijakan yang menyebut tiket
    ("bagaimana cara membuat tiket baru?", F),
    ("gimana cara bikin tiket IT?", F),
    ("bagaimana cara menutup tiket saya sendiri?", F),
    ("apakah tiket IT bisa dibuat lewat email?", F),
    ("laptop saya rusak, harus bikin tiket apa?", F),
]

gagal = []
for q, want in CASES:
    got = asyncio.run(detect_intent(q))
    print(f"{'OK  ' if got == want else 'GAGAL'} {got:13} (harapan {want:13}) {q!r}")
    if got != want:
        gagal.append(q)
print(f"\n{len(CASES) - len(gagal)}/{len(CASES)} sesuai")

import csv  # noqa: E402

ev = Path("..") / "evaluation"
berubah, total = [], 0
for nama in ("evaluation_results.csv", "safety_results.csv"):
    for r in csv.DictReader(open(ev / nama, encoding="utf-8")):
        if r["http_status"] != "200":
            continue
        total += 1
        sekarang = asyncio.run(detect_intent(r["query"]))
        if sekarang != r["intent"]:
            berubah.append((r["scenario_id"], r["intent"], sekarang, r["query"][:60]))
print(f"\nIntent berubah dibanding run before: {len(berubah)} dari {total} query")
for b in berubah:
    print("  ", b)
sys.exit(1 if gagal else 0)
