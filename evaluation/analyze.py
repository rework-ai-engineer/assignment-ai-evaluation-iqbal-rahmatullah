import argparse
import json
import re
from pathlib import Path

import pandas as pd

EV = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--results", default=str(EV / "evaluation_results.csv"))
ap.add_argument("--raw", default=str(EV / "raw_results.json"))
ap.add_argument("--repeat-results", default=str(EV / "repeat_results.csv"))
ap.add_argument("--repeat-raw", default=str(EV / "repeat_raw.json"))
args = ap.parse_args()

# Harga resmi Google (halaman pricing, 11 Nov 2026), USD per 1 juta token, paid tier standard.
PRICE_IN, PRICE_OUT = 0.30, 2.50
NOT_FOUND = "Maaf, saya tidak menemukan informasi tersebut di knowledge base. Silakan hubungi tim IT atau HR."
PERSONA = "Kamu adalah asisten IT Helpdesk internal perusahaan. Gaya bicaramu ramah, ringkas, dan akurat."


def load(csv_path, raw_path, source):
    df = pd.read_csv(csv_path)
    raw = json.loads(Path(raw_path).read_text(encoding="utf-8"))["results"]
    df["prompt"] = [r["_raw"]["prompt"] for r in raw]
    df["source"] = source
    df["run"] = df.groupby("scenario_id").cumcount() + 1
    return df


one = load(args.results, args.raw, "12 skenario")
rep = load(args.repeat_results, args.repeat_raw, "pengulangan")
allr = pd.concat([one, rep], ignore_index=True)
llm = allr[allr.llm_called]


def h(t):
    print(f"\n{'=' * 8} {t}")


# relevansi / konsistensi
h("A1. Pengulangan per skenario (n, HTTP 200, jawaban berbeda, penolakan persis, LLM dipanggil, rentang skor)")
g = rep.groupby("scenario_id")
print(pd.DataFrame({
    "n": g.size(),
    "http200": g.http_status.apply(lambda s: (s == 200).sum()),
    "jawaban_unik": g.response.nunique(),
    "persis_NOT_FOUND": g.response.apply(lambda s: (s == NOT_FOUND).sum()),
    "llm_dipanggil": g.llm_called.sum(),
    "skor_min": g.top_score.min(), "skor_maks": g.top_score.max(),
}).to_string())

h("A2. Fakta kunci EVAL-01 vs EVAL-10 (arti query sama): jawaban berisi '12 hari' dan '3 bulan'")
for sid in ("EVAL-01", "EVAL-10"):
    d = pd.concat([one[one.scenario_id == sid], rep[rep.scenario_id == sid]])
    print(f"{sid}: n={len(d)} | '12 hari': {d.response.str.contains('12 hari').sum()} | "
          f"'3 bulan': {d.response.str.contains('3 bulan').sum()} | jawaban unik: {d.response.nunique()}")
    for t in d.response.unique():
        print("   -", t)

h("A3. Cek grounding: angka di jawaban harus ada di konteks prompt (semua jawaban dari LLM, 12 skenario + pengulangan)")
bad = []
for r in llm.itertuples():
    extra = set(re.findall(r"\d+", r.response)) - set(re.findall(r"\d+", r.prompt))
    if extra:
        bad.append((r.scenario_id, r.run, sorted(extra), r.response))
print(f"jawaban LLM diperiksa: {len(llm)} | berisi angka yang TIDAK ada di konteks: {len(bad)}")
for b in bad:
    print("  ", b)

h("A4. Jawaban LLM yang bukan penolakan persis, per skenario (untuk dibaca manual)")
for sid, d in llm[llm.response != NOT_FOUND].groupby("scenario_id"):
    print(f"{sid}: {len(d)} jawaban, {d.response.nunique()} unik")

# latency
h("B1. 12 skenario (run resmi): waktu per tahap, detik")
print(one[["scenario_id", "response_time_s", "retrieval_s", "llm_call_s", "other_s", "llm_called"]].to_string(index=False))

h("B2. EVAL-11 (kompleks) vs EVAL-12 (sapaan): response_time_s")
for sid in ("EVAL-11", "EVAL-12"):
    d = pd.concat([one[one.scenario_id == sid], rep[rep.scenario_id == sid]]).response_time_s
    print(f"{sid}: n={len(d)} | min={d.min():.2f} median={d.median():.2f} maks={d.max():.2f} | semua={sorted(d.round(2))}")

h("B3. Jalur FAQ dengan LLM: kontribusi tahap terhadap total (seluruh data)")
tot = llm.response_time_s.sum()
print(f"n panggilan LLM={len(llm)} | LLM {llm.llm_call_s.sum() / tot:.1%} | retrieval {llm.retrieval_s.sum() / tot:.1%} "
      f"| lainnya {llm.other_s.sum() / tot:.1%}")
print("llm_call_s: " + " ".join(f"{k}={v:.2f}" for k, v in llm.llm_call_s.describe(percentiles=[.5, .9]).items()))
print("retrieval_s: " + " ".join(f"{k}={v:.2f}" for k, v in llm.retrieval_s.describe(percentiles=[.5, .9]).items()))

h("B4. Variansi llm_call_s per skenario pada pengulangan (prompt identik untuk skenario yang sama)")
b4 = rep[rep.llm_called].groupby("scenario_id").llm_call_s.agg(["count", "min", "median", "max"]).round(2)
b4["prompt_unik"] = rep[rep.llm_called].groupby("scenario_id").prompt.nunique()
print(b4.to_string())

h("B5. Apakah llm_call_s ikut panjang? korelasi Spearman (semua panggilan LLM)")
def spearman(a, b):  # Pearson pada peringkat = Spearman (pandas meminta scipy untuk method='spearman')
    return a.rank().corr(b.rank())


print(f"n={len(llm)} | vs output_tokens: {spearman(llm.llm_call_s, llm.output_tokens):.2f} "
      f"| vs prompt_tokens: {spearman(llm.llm_call_s, llm.prompt_tokens):.2f}")

h("B6. Retry tersembunyi (percobaan HTTP > 1)")
print(f"baris dengan llm_attempts>1: {(allr.llm_attempts > 1).sum()} | embed_attempts>1: {(allr.embed_attempts > 1).sum()} "
      f"| dari {len(allr)} request")
retried = allr[(allr.llm_attempts > 1) | (allr.embed_attempts > 1)]
if len(retried):
    print(retried[["source", "scenario_id", "run", "response_time_s", "retrieval_s", "llm_call_s", "embed_attempts", "llm_attempts"]].to_string(index=False))
print(f"thinking_tokens terisi: {allr.thinking_tokens.notna().sum()} dari {len(llm)} panggilan LLM")

# token & biaya
h("C1. Token per panggilan LLM (run resmi)")
print(one[one.llm_called][["scenario_id", "prompt_chars", "prompt_tokens", "output_tokens", "total_tokens", "top_score"]].to_string(index=False))


def split(p):  # template | context | pertanyaan, dalam karakter
    pre, rest = p.split("# Context\n", 1)
    ctx, post = rest.split("\n\n# Format", 1)
    qry = post.split("# Pertanyaan\n", 1)[1]
    return len(pre) + len(post) - len(qry), len(ctx), len(qry)


h("C2. Komposisi prompt dalam karakter (+ persona sistem), semua panggilan LLM")
parts = pd.DataFrame([split(p) for p in llm.prompt], columns=["template", "context", "query"], index=llm.index)
parts["template"] += len(PERSONA)
tot_chars = parts.sum(axis=1)
print(f"rata-rata karakter: template+persona={parts.template.mean():.0f} ({(parts.template / tot_chars).mean():.0%}) "
      f"| context(3 FAQ)={parts.context.mean():.0f} ({(parts.context / tot_chars).mean():.0%}) "
      f"| query={parts['query'].mean():.0f} ({(parts['query'] / tot_chars).mean():.0%})")
print(f"token/karakter (prompt_tokens / karakter): {(llm.prompt_tokens / tot_chars).mean():.3f}")

h("C3. Panggilan LLM yang hanya menghasilkan penolakan persis (HANYA 12 skenario resmi; pengulangan sengaja condong ke skenario tepi)")
o = one[one.llm_called]
ref = o[o.response == NOT_FOUND]
print(f"panggilan LLM={len(o)} | penolakan={len(ref)} ({len(ref) / len(o):.0%}) | token penolakan={int(ref.total_tokens.sum())} "
      f"dari {int(o.total_tokens.sum())} ({ref.total_tokens.sum() / o.total_tokens.sum():.0%}) | skenario: {', '.join(ref.scenario_id)}")
print(f"waktu llm_call pada penolakan: {ref.llm_call_s.sum():.2f} dtk dari {o.llm_call_s.sum():.2f} dtk")

h("C4. Biaya per panggilan LLM (paid tier; free tier gratis). Bukan proyeksi trafik: proporsi skenario di sini bukan proporsi produksi")


def usd(tin, tout):
    return (tin * PRICE_IN + tout * PRICE_OUT) / 1e6


pin, pout = llm.prompt_tokens.mean(), llm.output_tokens.mean()
print(f"rata-rata (n={len(llm)}) prompt={pin:.0f} token, output={pout:.0f} token | ${usd(pin, pout):.6f}/panggilan "
      f"(input ${pin * PRICE_IN / 1e6:.6f} + output ${pout * PRICE_OUT / 1e6:.6f}; output = "
      f"{pout * PRICE_OUT / (pin * PRICE_IN + pout * PRICE_OUT):.0%} biaya tetapi {pout / (pin + pout):.0%} token) "
      f"| per 100.000 panggilan: ${usd(pin, pout) * 1e5:.2f}")
print(f"panggilan penolakan (12 skenario resmi, n={len(ref)}): ${usd(ref.prompt_tokens.mean(), ref.output_tokens.mean()):.6f}/panggilan")
