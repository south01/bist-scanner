# BIST Conviction Scanner

Borsa İstanbul hisselerini tarayan, kişisel kullanım için geliştirilmiş bir ön-piyasa tarama aracı.

## Kurulum

```bash
cd bist-scanner
pip install -r requirements.txt
```

## Çalıştırma

```bash
python app.py
```

Tarayıcınızda açın: **http://127.0.0.1:5050**

## İlk Çalıştırma

İlk açılışta uygulama BIST hisse listesini otomatik olarak internet üzerinden çeker ve `data/bist_tickers.json` dosyasına kaydeder. Bu liste her 7 günde bir otomatik olarak yenilenir. Manuel yenileme gerekmez.

## Kullanım

1. Sayfayı açın
2. **"Tara"** düğmesine basın
3. ~500 hisse taranır (birkaç dakika sürebilir)
4. Sonuçlar puana göre sıralı görüntülenir

## Puan Sistemi

| Sinyal | Ağırlık | Alan |
|--------|---------|------|
| Boşluk >%5 + RVOL >3x | 3.0 | Momentum |
| Boşluk >%3 | 1.5 | Momentum |
| RVOL >3x | 2.0 | Hacim |
| RVOL 2-3x | 1.0 | Hacim |
| RS vs XU100 >+%3 | 2.0 | Rel. Güç |
| RS vs XU100 +%1-3 | 1.0 | Rel. Güç |
| Fiyat > EMA20 | 1.0 | Yapı |
| Fiyat > EMA50 | 1.5 | Yapı |
| 52 Hafta Yüksek Yakını | 1.5 | Yapı |
| ADR% >%3 | 1.0 | Volatilite |

3+ farklı alandan sinyal varsa: **1.2x çarpan** uygulanır.

## Kademe Eşikleri

- **S Kademe**: ≥ 8.0 puan
- **A Kademe**: ≥ 5.0 puan
- **B Kademe**: ≥ 3.0 puan
- **C Kademe**: ≥ 1.0 puan

## Proje Yapısı

```
bist-scanner/
├── app.py          # Flask backend
├── scorer.py       # Sinyal hesaplama motoru
├── tickers.py      # Otomatik BIST hisse listesi
├── requirements.txt
├── data/
│   └── bist_tickers.json   # Önbelleklenmiş hisse listesi
└── templates/
    └── index.html  # Frontend (mobil uyumlu)
```

## Notlar

- Veri kaynağı: Yahoo Finance (yfinance) — EOD/gecikmeli veri
- Kişisel kullanım içindir — kimlik doğrulama yok
- Port: 5050 (değiştirmek için app.py'yi düzenleyin)
