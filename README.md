# AI System Evaluation, Safety & Optimization — IT Helpdesk Assistant

Evaluasi menyeluruh terhadap prototype **IT Helpdesk Assistant** (hasil Assignment 4) sebelum sistem dipertimbangkan masuk tahap produksi: menjalankan skenario uji, menganalisis relevansi, hallucination, latency, token, dan keamanan dasar, memperbaiki minimal 2 isu paling signifikan, lalu membandingkan kondisi sebelum dan sesudah.

Alur kerja mengikuti **Observe → Test → Diagnose → Optimize → Compare & Recommend**.

## 1. Problem Statement

### Objective evaluasi

Sebelum sistem dipakai karyawan sungguhan, evaluasi ini ingin memastikan empat hal:

1. **Relevan dan jujur**: jawaban sesuai knowledge base, dan sistem mengakui keterbatasan alih-alih mengarang saat informasinya tidak ada.
2. **Cukup cepat**: waktu respons wajar, dan tahap yang paling memperlambat (retrieval, LLM call, atau lainnya) diketahui.
3. **Terkendali biayanya**: pemakaian token per request dipahami, termasuk pola yang membuatnya membengkak.
4. **Tahan input tidak wajar**: sistem tetap pada perannya dan tetap stabil saat menerima instruksi atau input yang tidak lazim.

Temuan kemudian diubah menjadi perbaikan nyata pada kode (minimal 2 isu) dengan bukti before/after dan rekomendasi lanjutan.

### Sistem yang dievaluasi

**Sistem hasil Assignment 4 milik sendiri** (folder `system/`, disalin tanpa perubahan dari project Assignment 4).

Gambaran sistem (dari kode di `system/app/`):

```
POST /ask {query}
  └─ router.py: detect_intent (regex + keyword, tanpa LLM)
       ├─ "ticket_status" → tools.py: baca data/mock_tickets.csv
       └─ "faq"           → rag.py: embed query → FAISS top-3
                                  ├─ skor tertinggi < 0.65 → "tidak ditemukan" (tanpa LLM)
                                  └─ selain itu → prompt + Gemini → jawaban
```

| Komponen       | Nilai                                                                                            |
| -------------- | ------------------------------------------------------------------------------------------------ |
| Framework      | FastAPI (`/ask`, `/health`); `query` wajib 1–500 karakter                                        |
| Embedding      | `gemini-embedding-001`, 768 dimensi, index FAISS `IndexFlatIP` (dibangun saat pencarian pertama) |
| Model generate | `gemini-3.5-flash-lite`, `temperature=0.2`, retry bawaan klien 3 percobaan                       |
| Retrieval      | top-k = 3, ambang `MIN_SCORE = 0.65`                                                             |
| Data           | 31 FAQ (6 kategori), 15 tiket mock                                                               |

### Batasan dan asumsi

- **Pengujian black-box dari luar**: skenario dikirim lewat HTTP ke `/ask`; kode sistem tidak diubah sampai tahap perbaikan, supaya kondisi "before" bersih.
- **Satu run per skenario**: output LLM tidak sepenuhnya deterministik (`temperature=0.2`). Untuk skenario konsistensi, query diulang. Angka latency adalah pengamatan, bukan rata-rata statistik.
- **Latency dipengaruhi faktor eksternal**: sistem memakai Gemini API tier gratis lewat internet, sehingga waktu respons ikut dipengaruhi jaringan, kondisi server Google, dan retry otomatis klien (yang tidak terlihat dari luar). Kegagalan API (`429`/`503`) dicatat apa adanya, tidak dibuang.
- **Skala kecil**: knowledge base hanya 31 FAQ dan request dikirim berurutan, bukan beban paralel. Hasil tidak mewakili performa di bawah traffic produksi.
- **Token berupa pengukuran/estimasi**: sumber dan metode angka dijelaskan pada bagian analisis token.
- **Safety testing berbasis kriteria**: memakai kerangka `evaluation/safety_guardrail_testing_framework.md`; pertanyaan uji ditulis sendiri untuk mewakili pola perilaku, bukan teknik serangan baru.
- **Waktu dan model**: evaluasi dilakukan pada November 2026 dengan model yang tertulis di atas; hasil dapat berbeda bila model atau kuota API berubah.
- Sistem tidak punya autentikasi; pertanyaan "tiket saya" tidak bisa dikaitkan ke pengguna tertentu. Ini dicatat sebagai batasan desain, bukan dinilai sebagai bug.

## 2. Pengamatan Awal (tahap Observe)

Sebelum pengujian terstruktur, sistem dijalankan dari kondisi segar (11 November 2026) dan diberi 6 query pemakaian wajar yang bukan bagian dari 12 skenario. Ini kesan awal informal, satu kali jalan, bukan hasil evaluasi.

| #   | Query                                  | Intent        | Waktu    | Catatan                                                   |
| --- | -------------------------------------- | ------------- | -------- | --------------------------------------------------------- |
| 1   | bagaimana cara mengajukan cuti?        | faq           | 3,48 dtk | Sesuai FAQ 2. Request pertama, sudah termasuk build index |
| 2   | laptop kerja saya rusak, harus gimana? | faq           | 3,82 dtk | Sesuai FAQ 15                                             |
| 3   | berapa jam kerja per hari?             | faq           | 1,41 dtk | Sesuai FAQ 26                                             |
| 4   | status TICKET-0010 gimana?             | ticket_status | 0,01 dtk | Cocok dengan data tiket                                   |
| 5   | bisa kerja dari rumah nggak?           | faq           | 1,40 dtk | Sesuai FAQ 25 (parafrase dikenali)                        |
| 6   | makasih ya, sangat membantu            | faq           | 0,42 dtk | Dijawab "tidak menemukan informasi di knowledge base"     |

Kesan awal, yang akan diuji lebih serius pada langkah berikutnya:

- **Isi jawaban**: pada keempat query FAQ yang dijawab (nomor 1, 2, 3, 5), semua detail (hari, jam, kategori tiket) cocok dengan FAQ sumbernya; tidak ada klaim di luar knowledge base.
- **Latency bervariasi** untuk alur yang sama: 1,4 sampai 3,8 dtk pada query FAQ di percobaan ini. Pada percobaan awal terpisah (10 November 2026, tidak didokumentasikan lengkap), query yang sama ("berapa jam kerja per hari?") pernah memakan 10,8 dtk, sedangkan sekarang 1,4 dtk. Artinya selisih tampak bergantung pada kondisi saat itu, bukan pada isi query; penyebab pastinya belum diketahui dan akan diukur per tahap.
- **Basa-basi diperlakukan sebagai pertanyaan tak terjawab**: "makasih ya" tidak mengarang, tetapi mendapat pesan "tidak menemukan informasi" yang kurang pas sebagai balasan. Pesan itu diduga keluar dari ambang `MIN_SCORE` sebelum LLM dipanggil (dugaan dari kode dan waktu 0,42 dtk; belum diverifikasi).
- Beberapa jawaban diawali "Halo!" yang ditambahkan model; ini gaya, bukan isi.
