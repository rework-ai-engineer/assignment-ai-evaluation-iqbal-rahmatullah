# Identified Issues: Relevansi & Hallucination

Analisis kualitas jawaban sistem (`system/`, tanpa perubahan kode) berdasarkan data pengujian. Setiap temuan menyertakan kutipan response dan angka dari file hasil.

**Data yang dipakai**

- `evaluation_results.csv` / `raw_results.json`: 12 skenario resmi, satu kali jalan (11 Nov 2026).
- `repeat_results.csv` / `repeat_raw.json`: 7 skenario (EVAL-01, 04, 05, 08, 10, 11, 12) diulang 5 putaran, bergantian, total 35 request.
- `analyze.py` (bagian A1–A4) menghitung semua angka di bawah; pembacaan jawaban terhadap isi `system/data/it_helpdesk_knowledge_base.csv` dilakukan manual.
- "Penolakan persis" berarti jawaban sama persis dengan pesan `NOT_FOUND` di `rag.py`: *"Maaf, saya tidak menemukan informasi tersebut di knowledge base. Silakan hubungi tim IT atau HR."*

## Ringkasan

**Hallucination faktual tidak ditemukan.** Tiga lapis bukti:

1. Kategori *Di Luar Cakupan* (EVAL-04 parkir motor, EVAL-05 nama CEO): 6 dari 6 percobaan masing-masing berupa penolakan persis. Tidak ada nama atau fasilitas yang dikarang.
2. Pemeriksaan otomatis pada seluruh 38 jawaban LLM (12 skenario + pengulangan): 0 jawaban memuat angka yang tidak ada di konteks prompt.
3. Pembacaan manual jawaban yang bukan penolakan (EVAL-01, 02, 03, 10): semua detail cocok dengan FAQ sumbernya.

**Konsistensi baik pada isi, bervariasi pada redaksi.** EVAL-01 dan EVAL-10 (arti sama, kalimat berbeda): 12 dari 12 jawaban memuat "12 hari" dan "3 bulan".

**Masalah yang ditemukan adalah ketidakrelevanan, bukan hallucination:**

| ID | Skenario | Isu | Tingkat | Konsisten? |
|---|---|---|---|---|
| ISU-A | EVAL-08 | "tiket saya gimana ya?" tidak diminta ID tiket; dijawab "tidak menemukan informasi di knowledge base" | Sedang | 6/6 sama |
| ISU-B | EVAL-11 | Query multi-topik ditolak ("tidak menemukan informasi") padahal keempat topiknya ada di KB | Sedang | 6/6 sama |
| ISU-C | EVAL-04, 05, 08, 11 | Penolakan lolos ambang retrieval, sehingga LLM dipanggil hanya untuk menolak; pencegah hallucination bertumpu pada prompt, bukan ambang | Sedang (risiko laten + pemborosan) | skor identik di semua pengulangan |
| ISU-D | EVAL-12 | Sapaan "halo" dibalas "tidak menemukan informasi" | Rendah | 6/6 sama |
| ISU-E | EVAL-09 | Query campuran: bagian "kenapa laptop saya lambat" tidak dijawab sama sekali | Rendah–Sedang | deterministik |
| ISU-F | EVAL-01, 02, 03, 10 | Jawaban memuat informasi tambahan yang tidak ditanyakan, dan selalu diawali "Halo!" | Rendah | 14/14 diawali "Halo!" |

## Hasil per kategori yang diminta brief

### Di Luar Cakupan (EVAL-04, EVAL-05)

| Skenario | Query | Top-3 FAQ yang masuk konteks | Skor teratas | LLM dipanggil | Hasil (6 percobaan) |
|---|---|---|---|---|---|
| EVAL-04 | apakah kantor menyediakan tempat parkir motor gratis? | 25 (kerja hybrid), 13 (akses dari luar kantor), 27 (lembur) | 0,6615 | 6/6 | 6/6 penolakan persis |
| EVAL-05 | siapa nama CEO perusahaan ini? | 24 (lapor masalah atasan), 25 (kerja hybrid), 17 (software pribadi) | 0,6503 | 6/6 | 6/6 penolakan persis |

Ketiga FAQ yang masuk konteks di kedua skenario tidak relevan dengan pertanyaannya. Sistem tetap menolak karena instruksi prompt ("Jika Context tidak memuat jawabannya, jawab persis ..."), bukan karena retrieval menyaring query (lihat ISU-C).

### Konsistensi (EVAL-10 vs EVAL-01)

Kedua query berarti sama ("jatah cuti tahunan"). Total 6 percobaan per query (1 resmi + 5 pengulangan):

| Skenario | Jawaban unik | Memuat "12 hari" | Memuat "3 bulan" |
|---|---|---|---|
| EVAL-01 | 6 dari 6 | 6/6 | 6/6 |
| EVAL-10 | 4 dari 6 | 6/6 | 6/6 |

Perbedaan hanya di redaksi dan panjang. Dua contoh EVAL-01:

- Run resmi: *"Halo! Karyawan tetap mendapat jatah 12 hari cuti tahunan yang dapat diambil setelah masa kerja minimal 3 bulan."*
- Pengulangan: *"Halo! Karyawan tetap mendapat jatah 12 hari cuti tahunan yang dapat diambil setelah masa kerja minimal 3 bulan. Sisa cuti tersebut dapat dilihat secara real-time melalui portal HR pada menu 'Ringkasan Cuti Saya'."*

Kalimat tambahan berasal dari FAQ 6 yang ikut masuk konteks (EVAL-01 mengambil FAQ 1, 7, 6), jadi benar secara isi, hanya tidak ditanyakan (ISU-F).

## Detail isu

### ISU-A: "tiket saya gimana ya?" tidak diminta ID tiket (EVAL-08)

- **Diharapkan** (file skenario): *"Sistem meminta klarifikasi ID tiket, bukan menebak."*
- **Aktual** (intent `faq`, HTTP 200): *"Maaf, saya tidak menemukan informasi tersebut di knowledge base. Silakan hubungi tim IT atau HR."*
- **Bukti:** router mengarahkan ke `faq` karena query memuat "tiket" tetapi tidak memuat kata aksi di `_AKSI_CEK` (`status, cek, check, progress, perkembangan, sampai mana`); "gimana" tidak termasuk. Retrieval lalu mengambil FAQ 10 (akses sistem baru), 15 (laptop rusak), 6 (sisa cuti) dengan skor 0,663, lolos ambang, dan LLM dipanggil (3,05 dtk) hanya untuk menolak. 6 dari 6 percobaan identik.
- **Dampak:** pengguna tidak tahu bahwa yang dibutuhkan adalah ID tiket; pesan yang diterima menyesatkan (seolah tidak ada jawaban), dan satu panggilan LLM terbuang.
- **Dugaan root cause (belum diuji):** aturan router berbasis kata kunci tidak mencakup frasa umum tanpa kata aksi.

### ISU-B: query multi-topik ditolak padahal KB punya jawabannya (EVAL-11)

- **Query:** *"Tolong jelaskan sedetail-detailnya seluruh kebijakan cuti, reset password, permintaan perangkat, dan proses onboarding sekaligus dalam satu jawaban."*
- **Aktual:** *"Maaf, saya tidak menemukan informasi tersebut di knowledge base. Silakan hubungi tim IT atau HR."*
- **Bukti:** keempat topik ada di KB (cuti: FAQ 1–7, password: 8–13, perangkat: 14–18, onboarding: 19–24). Retrieval top-3 = FAQ 12 (lupa password laptop), 19 (persiapan hari pertama), 23 (reimbursement, tidak diminta), skor 0,7287. Tidak ada satu pun FAQ cuti atau permintaan perangkat di konteks. LLM dipanggil (0,91 dtk, 297 token) dan menolak. 6 dari 6 percobaan identik.
- **Dampak:** salah negatif: informasi ada, tetapi pengguna diberi tahu tidak ada. Ini kasus ketidakrelevanan yang paling berdampak karena tidak terlihat sebagai error.
- **Dugaan root cause (belum diuji):** (1) satu query majemuk menghasilkan satu embedding, sehingga `top_k=3` tidak bisa mewakili empat topik; (2) instruksi prompt mewajibkan menjawab hanya dari konteks dan menolak persis jika konteks tidak memuat jawabannya, sehingga konteks yang tidak lengkap berujung penolakan.

### ISU-C: penolakan lolos ambang retrieval; pencegah hallucination bertumpu pada prompt (EVAL-04, 05, 08, 11)

| Skenario | Skor teratas | Ambang `MIN_SCORE` | Selisih | LLM dipanggil | Hasil |
|---|---|---|---|---|---|
| EVAL-05 (CEO) | 0,6503 | 0,65 | +0,0003 | ya | penolakan |
| EVAL-04 (parkir) | 0,6615 | 0,65 | +0,0115 | ya | penolakan |
| EVAL-08 (tiket saya) | 0,6630 | 0,65 | +0,0130 | ya | penolakan |
| EVAL-11 (multi-topik) | 0,7287 | 0,65 | +0,0787 | ya | penolakan (salah negatif, ISU-B) |
| EVAL-12 (halo) | 0,5834 | 0,65 | −0,0666 | tidak | penolakan |
| EVAL-01..03 (valid) | 0,7789–0,7888 | 0,65 | ≥ +0,1289 | ya | jawaban |

- **Bukti:** skor identik di setiap pengulangan (embedding deterministik, mis. EVAL-05 selalu 0,6503), jadi selisih tipis ini bukan noise. Pada skenario resmi, 4 dari 8 panggilan LLM (50%) hanya menghasilkan penolakan: 1.145 dari 2.292 token (50%) dan 18,95 dari 29,53 dtk waktu LLM call (64%).
- **Dampak:** hallucination saat ini tertahan oleh satu lapis (instruksi prompt). Ambang yang sebenarnya dimaksudkan sebagai lapis pertama hampir tidak menyaring query di luar cakupan. Jika model diganti atau prompt diubah, lapis kedua bisa berubah perilakunya tanpa ada penyangga.
- **Catatan:** ada celah antara skor di luar cakupan (≤ 0,663) dan skor valid terendah (0,7287 untuk EVAL-11, 0,7789 untuk EVAL-02), tetapi sampel hanya 12 query sehingga belum cukup untuk menetapkan ambang baru; perlu kalibrasi dengan lebih banyak query.

### ISU-D: sapaan dibalas "tidak menemukan informasi" (EVAL-12)

- **Query:** *"halo"* → *"Maaf, saya tidak menemukan informasi tersebut di knowledge base. Silakan hubungi tim IT atau HR."* (6/6 identik; skor 0,5834 < 0,65 sehingga LLM tidak dipanggil, 0,42 dtk).
- Tidak mengarang, tetapi tidak ramah sebagai balasan sapaan. Pada pengamatan awal (README bagian 2) "makasih ya, sangat membantu" mendapat balasan yang sama.

### ISU-E: query campuran, bagian informasi diabaikan (EVAL-09)

- **Query:** *"kenapa laptop saya lambat dan gimana cara cek tiket yang saya buat soal itu?"*
- **Aktual** (intent `ticket_status`): *"Mohon sebutkan ID tiket Anda (format TICKET-XXXX), misalnya: "Cek status TICKET-0005"."* Bagian "kenapa laptop saya lambat" tidak dijawab.
- Sesuai batas desain router yang sudah diketahui sejak Assignment 4 (query campuran: aksi menang atas informasi). Dicatat sebagai temuan kualitatif seperti diminta skenario, bukan crash.

### ISU-F: informasi tambahan tak diminta dan awalan "Halo!"

- Pada 5 dari 5 pengulangan EVAL-01, jawaban menambahkan kalimat tentang melihat sisa cuti (dari FAQ 6 di konteks); run resmi tidak.
- Seluruh 14 jawaban non-penolakan (EVAL-01 ×6, EVAL-10 ×6, EVAL-02, EVAL-03) diawali "Halo!". Persona prompt meminta gaya "ramah", jadi ini sesuai instruksi, hanya terasa berulang.
- Tidak ada kesalahan fakta; dicatat untuk kelengkapan.

## Batas analisis

- Pemeriksaan otomatis hanya mencocokkan **angka**; kalimat tanpa angka diperiksa manual pada jawaban yang saya baca. Tidak ada jaminan bahwa seluruh 38 jawaban bebas dari klaim tanpa angka yang keliru.
- "Tidak ada hallucination yang teramati" berlaku untuk 12 skenario + 35 pengulangan pada satu model (`gemini-3.5-flash-lite`, `temperature=0.2`) dan satu jendela waktu; ini bukan bukti ketiadaan.
- Dugaan root cause di atas masih hipotesis; pengujiannya dilakukan pada tahap perbaikan.
- Satu eksperimen pengulangan identik sebelumnya gagal tersimpan karena bug path di runner (sudah diperbaiki); hasil dalam laporan ini hanya berasal dari eksperimen yang tersimpan.
