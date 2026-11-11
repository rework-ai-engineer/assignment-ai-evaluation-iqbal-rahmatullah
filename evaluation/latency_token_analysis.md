# Analisis Latency, Bottleneck, dan Token

Analisis waktu respons dan pemakaian token sistem (`system/`, tanpa perubahan kode). Semua angka dihitung ulang oleh `analyze.py` (bagian B dan C) dari `evaluation_results.csv`, `raw_results.json`, `repeat_results.csv`, dan `repeat_raw.json`.

**Cara mengukur** (`run_scenarios.py`, instrumentasi hanya di proses runner):

- `response_time_s`: end-to-end dari sisi client (HTTP ke `/ask`).
- `retrieval_s`: seluruh `semantic_search` (satu panggilan embedding ke API + pencarian FAISS).
- `llm_call_s`: `generate_content` ke Gemini, termasuk retry otomatis klien bila terjadi.
- `other_s`: sisanya (HTTP lokal, validasi, router, penyusunan prompt, baca CSV tiket).
- Token: `usage_metadata` dari API Gemini (angka dari penyedia, bukan estimasi).
- Cold start (build index 31 FAQ) diukur terpisah: 1,93 dtk, supaya 12 skenario diukur dalam keadaan "warm".

## 1. Latency 12 skenario (run resmi, detik)

| Skenario | Jalur | Total | Retrieval | LLM call | Lainnya |
|---|---|---|---|---|---|
| EVAL-01 | faq + LLM | 1,71 | 0,43 | 1,26 | 0,01 |
| EVAL-02 | faq + LLM | 4,48 | 0,40 | 4,08 | 0,00 |
| EVAL-03 | faq + LLM | 1,48 | 0,42 | 1,06 | 0,01 |
| EVAL-04 | faq + LLM (penolakan) | 4,35 | 0,44 | 3,91 | 0,00 |
| EVAL-05 | faq + LLM (penolakan) | **11,49** | 0,41 | 11,07 | 0,00 |
| EVAL-06 | tiket | 0,01 | – | – | 0,01 |
| EVAL-07 | tiket | 0,00 | – | – | 0,00 |
| EVAL-08 | faq + LLM (penolakan) | 3,55 | 0,50 | 3,05 | 0,00 |
| EVAL-09 | tiket (minta ID) | 0,00 | – | – | 0,00 |
| EVAL-10 | faq + LLM | 4,61 | 0,43 | 4,18 | 0,00 |
| EVAL-11 | faq + LLM (penolakan) | 1,38 | 0,46 | 0,91 | 0,00 |
| EVAL-12 | faq, berhenti di ambang (tanpa LLM) | 0,42 | 0,42 | – | 0,00 |

Tiga jalur dengan waktu sangat berbeda: tiket (≈ 0,01 dtk), berhenti di ambang (≈ 0,42 dtk), dan jalur dengan LLM (1,4 sampai 11,5 dtk).

## 2. EVAL-12 (sederhana) vs EVAL-11 (kompleks)

Enam pengukuran per skenario (1 resmi + 5 pengulangan):

| Skenario | Min | Median | Maks | LLM dipanggil | Token LLM |
|---|---|---|---|---|---|
| EVAL-12 ("halo") | 0,41 | 0,42 | 0,52 | tidak | 0 |
| EVAL-11 (4 topik sekaligus) | 1,21 | 1,64 | 5,50 | ya | 297 |

**Selisih ≈ ada atau tidaknya panggilan LLM, bukan kompleksitas query.** "halo" berhenti di ambang retrieval (skor 0,5834 < 0,65), sehingga hanya membayar satu panggilan embedding. Di antara skenario yang sama-sama memanggil LLM, EVAL-11 tidak lebih lambat: median `llm_call_s` 1,12 dtk (n=5) berbanding 3,02 sampai 4,07 dtk pada EVAL-01, 04, 05, 08, 10. Rentangnya terlalu lebar untuk membedakan secara statistik (lihat bagian 4), sehingga yang bisa disimpulkan hanya: **tidak ada bukti bahwa query panjang membuat sistem lebih lambat.** Alasan desainnya: konteks selalu tepat top-3 FAQ dan jawaban dibatasi 3 kalimat, sehingga ukuran prompt dan output nyaris tidak bergantung pada panjang query (bagian 5).

Catatan kualitas: EVAL-11 cepat karena sistem menolak menjawab (salah negatif, ISU-B di `identified_issues.md`), bukan karena menyelesaikan tugasnya.

## 3. Bottleneck: tahap LLM

Seluruh 38 panggilan LLM (12 skenario + pengulangan):

| Tahap | Rata-rata | Median | P90 | Maks | Porsi waktu total |
|---|---|---|---|---|---|
| LLM call | 3,35 dtk | 3,74 | 5,28 | 11,07 | **87,6%** |
| Retrieval (embedding + FAISS) | 0,47 dtk | 0,47 | 0,53 | 0,59 | 12,3% |
| Lainnya | – | – | – | – | 0,1% |

Retrieval stabil (simpangan baku 0,05 dtk); semua variansi ada di LLM call (simpangan baku 2,21 dtk). Satu panggilan embedding per request ≈ 0,47 dtk dan tidak dipakai ulang walau query sama.

## 4. Sumber variansi LLM call

Pada pengulangan, prompt untuk satu skenario **identik di semua putaran** (`prompt_unik = 1` untuk keenam skenario yang memanggil LLM), tetapi waktu LLM call berbeda jauh:

| Skenario | n | Min | Median | Maks | Maks/Min |
|---|---|---|---|---|---|
| EVAL-01 | 5 | 1,00 | 3,18 | 6,20 | 6,2× |
| EVAL-04 | 5 | 0,76 | 3,58 | 5,43 | 7,1× |
| EVAL-05 | 5 | 1,01 | 3,90 | 4,35 | 4,3× |
| EVAL-08 | 5 | 0,99 | 3,02 | 7,62 | 7,7× |
| EVAL-10 | 5 | 0,92 | 4,07 | 5,22 | 5,7× |
| EVAL-11 | 5 | 0,78 | 1,12 | 4,95 | 6,3× |

Tiga penjelasan yang diuji dan **tidak didukung** data:

1. **Panjang input/output:** korelasi Spearman `llm_call_s` dengan `output_tokens` = 0,06 dan dengan `prompt_tokens` = −0,09 (n=38). Contoh ekstrem: EVAL-05 menghasilkan 21 token dalam 11,07 dtk, sedangkan EVAL-01 menghasilkan 28 token dalam 1,26 dtk.
2. **Retry tersembunyi di klien:** hanya 1 dari 47 request yang memakai lebih dari satu percobaan HTTP (EVAL-10 putaran 5, 2 percobaan, `llm_call_s` 5,22 dtk, bukan outlier). Lonjakan 11,07 dtk di EVAL-05 hanya satu percobaan.
3. **Kerumitan prompt:** prompt-nya identik per skenario (di atas).

**Kesimpulan yang boleh ditarik:** variansi berasal dari luar kode sistem, yaitu layanan Gemini atau jaringan; dari luar tidak bisa dibedakan keduanya. Yang bisa dikontrol sistem hanyalah **berapa kali** LLM dipanggil dan bagaimana kegagalannya ditangani, bukan lama satu panggilan.

## 5. Penggunaan token

Panggilan LLM pada 12 skenario resmi (8 panggilan; tiket dan EVAL-12 = 0 token LLM):

| Skenario | Karakter prompt | Token prompt | Token output | Total | Hasil |
|---|---|---|---|---|---|
| EVAL-01 | 906 | 257 | 28 | 285 | jawaban |
| EVAL-02 | 985 | 244 | 34 | 278 | jawaban |
| EVAL-03 | 1.049 | 262 | 31 | 293 | jawaban |
| EVAL-04 | 1.018 | 263 | 21 | 284 | penolakan |
| EVAL-05 | 1.035 | 263 | 21 | 284 | penolakan |
| EVAL-08 | 1.005 | 259 | 21 | 280 | penolakan |
| EVAL-10 | 956 | 262 | 29 | 291 | jawaban |
| EVAL-11 | 1.144 | 276 | 21 | 297 | penolakan |

Rata-rata seluruh 38 panggilan: **263 token prompt + 28 token output**. `thinking_tokens` tidak pernah dilaporkan (0 dari 38 panggilan).

**Komposisi prompt** (rata-rata karakter, 38 panggilan): instruksi template + persona 489 (45%), konteks 3 FAQ 543 (50%), query 53 (5%). Rasio 0,243 token per karakter (`prompt_tokens` / karakter). Dari rasio itu, perkiraan kasar: satu FAQ di konteks ≈ 181 karakter ≈ 44 token, dan instruksi tetap ≈ 119 token per panggilan (perkiraan, bukan pengukuran per bagian).

### Pola yang memicu token berlebih

1. **Konteks selalu top-3, tanpa menilai relevansi.** Pada penolakan (EVAL-04, 05, 08, 11) tiga FAQ yang tidak relevan tetap dikirim ke LLM: sekitar 284 token untuk satu kalimat penolakan. Pada skenario resmi, 4 dari 8 panggilan LLM (50%) berakhir penolakan: 1.145 dari 2.292 token (50%) dan 18,95 dari 29,53 dtk waktu LLM (64%).
2. **Query panjang tidak membengkakkan token** (EVAL-11: 276 token prompt vs 244–263 pada skenario lain, sekitar +5 sampai +13%), karena `top_k=3` dan batas 3 kalimat. Risiko ke depan: jika `top_k` dinaikkan untuk memperbaiki EVAL-11, tiap FAQ tambahan ≈ 44 token (perkiraan).
3. **Instruksi tetap ≈ 45% karakter prompt** dikirim ulang di setiap panggilan.

Token embedding tidak terukur (respons embedding Gemini tidak mengembalikan jumlah token); diperkirakan sangat kecil dibanding generate, tetapi tidak dihitung di sini.

## 6. Implikasi biaya

Harga resmi Google (halaman pricing, dibaca 11 Nov 2026 di https://aistudio.google.com/docs/pricing, tujuan redirect dari ai.google.dev/gemini-api/docs/pricing), paid tier standard, per 1 juta token: `gemini-3.5-flash-lite` input **$0,30**, output (termasuk thinking) **$2,50**; free tier tertulis "Free of charge". Embedding `gemini-embedding-001`: $0,15 per 1 juta token input. Halaman dibaca lewat WebFetch (diringkas model kecil) dan angkanya sama dengan beberapa situs pihak ketiga.

| | Per panggilan | Per 100.000 panggilan |
|---|---|---|
| Rata-rata (263 token input + 28 output) | $0,000148 | $14,78 |
| Rincian | input $0,000079 + output $0,000069 | |
| Panggilan penolakan (skenario resmi) | $0,000132 | |

- **Output hanya 10% token tetapi 47% biaya**, karena harga output 8,3× input. Output sudah pendek (28 token), jadi penghematan terbesar ada pada **mengurangi jumlah panggilan**, bukan memendekkan jawaban.
- Angka ini adalah **biaya per panggilan**, bukan proyeksi trafik: proporsi skenario di data ini bukan proporsi produksi (skenario sengaja condong ke kasus tepi), sehingga tidak ada dasar untuk menghitung total bulanan.
- Pada tier gratis biayanya nol, tetapi kuota menjadi batas: sekali teramati `429 RESOURCE_EXHAUSTED` saat build index berulang kali dalam satu menit pada uji runner (setiap start proses membangun index = 31 request embedding; batas sekitar 100 request/menit berasal dari catatan Assignment 4, tidak diverifikasi ulang).

## 7. Batas analisis

- Sampel kecil (47 request, satu jendela waktu, request berurutan, tanpa beban paralel): median dan P90 menggambarkan data ini, bukan distribusi produksi.
- Latency Gemini pada tier gratis bisa berbeda dari tier berbayar; tier kunci API yang dipakai tidak diverifikasi.
- Variansi dinyatakan berasal dari luar kode sistem, tetapi apakah dari beban server Google atau jaringan tidak dapat dibedakan dari sisi client.
- Perkiraan token per bagian prompt (44 token/FAQ, 119 token instruksi) memakai rasio rata-rata, bukan hitungan tokenizer per bagian.
- Satu eksperimen pengulangan identik sebelumnya gagal tersimpan karena bug path di runner (sudah diperbaiki); laporan ini hanya memakai eksperimen yang tersimpan.
