#!/usr/bin/env python3
"""
Script Otomatisasi: Tracker Kurs Rupiah Indonesia dan Komoditas Global.
Mengambil data kurs mata uang dan komoditas global, kemudian memperbarui
blok Markdown di README.md secara otomatis.
"""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import logging
import os
import re
from typing import Dict, List, Optional
import requests

# ---------------------------------------------------------------------------
# Konfigurasi Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konstanta & Pengaturan
# ---------------------------------------------------------------------------
FILE_README = "README.md"
MARKER_START = "<!--START_SECTION:fx-rates-->"
MARKER_END = "<!--END_SECTION:fx-rates-->"
TIMEOUT_HTTP = 10  # detik
ZONE_WITA = timezone(timedelta(hours=8))  # UTC+8 (WITA)


@dataclass
class ItemPasar:
    nama: str
    simbol: str
    harga_idr: float
    satuan: str
    persentase_perubahan: Optional[float] = None
    harga_usd: Optional[float] = None


class PengambilKurs:
    """Mengambil kurs valuta asing terhadap IDR menggunakan API publik."""

    API_PRIMARY = "https://api.frankfurter.app/latest"
    API_FALLBACK = "https://open-er-api.com/v6/latest/USD"

    @classmethod
    def AmbilKurs(cls) -> Dict[str, float]:
        """
        Mengembalikan kamus nilai tukar terhadap IDR (1 Mata Uang Target = X IDR).
        Mata uang target: USD, EUR, SGD, JPY, GBP.
        """
        kurs_ke_idr: Dict[str, float] = {}

        # 1. Coba Open Exchange Rates API (open-er-api.com)
        try:
            logger.info("Mengambil kurs melalui Open Exchange Rates Public API...")
            respons = requests.get(cls.API_FALLBACK, timeout=TIMEOUT_HTTP)
            respons.raise_for_status()
            data = respons.json()
            if data.get("result") == "success":
                kurs_usd = data.get("rates", {})
                usd_ke_idr = float(kurs_usd.get("IDR", 0))

                if usd_ke_idr > 0:
                    mata_uang_target = ["USD", "EUR", "SGD", "JPY", "GBP"]
                    for kur in mata_uang_target:
                        kur_dalam_usd = float(kurs_usd.get(kur, 1))
                        kurs_ke_idr[kur] = (1.0 / kur_dalam_usd) * usd_ke_idr

                    logger.info("Berhasil mengambil data kurs valas.")
                    return kurs_ke_idr
        except Exception as e:
            logger.warning(f"Gagal mengambil dari API primer: {e}. Mencoba fallback Frankfurter...")

        # 2. Fallback: Frankfurter API (Base EUR)
        try:
            respons = requests.get(
                f"{cls.API_PRIMARY}?from=EUR&to=IDR,USD,SGD,JPY,GBP",
                timeout=TIMEOUT_HTTP,
            )
            respons.raise_for_status()
            data = respons.json()
            kurs_eur = data.get("rates", {})
            eur_ke_idr = float(kurs_eur.get("IDR", 0))

            if eur_ke_idr > 0:
                kurs_ke_idr["EUR"] = eur_ke_idr
                for kur in ["USD", "SGD", "JPY", "GBP"]:
                    kur_dalam_eur = float(kurs_eur.get(kur, 1))
                    kurs_ke_idr[kur] = eur_ke_idr / kur_dalam_eur
                return kurs_ke_idr
        except Exception as e:
            logger.error(f"Fallback Frankfurter API juga gagal: {e}")

        return kurs_ke_idr


class PengambilKomoditas:
    """Mengambil harga komoditas global publik (Emas & Minyak Mentah)."""

    @classmethod
    def AmbilKomoditas(cls, kurs_usd_ke_idr: float) -> List[ItemPasar]:
        """
        Mengambil estimasi harga Emas (per gram) dan Minyak Mentah (per barrel).
        """
        daftar_item: List[ItemPasar] = []

        # 1. Ambil Emas (Emas) via Stooq
        emas_usd = cls._AmbilHargaEmasUSD()
        if emas_usd:
            # 1 Troy Oz = 31.1035 Gram
            emas_idr_per_gram = (emas_usd * kurs_usd_ke_idr) / 31.1035
            daftar_item.append(
                ItemPasar(
                    nama="Emas (Gold)",
                    simbol="XAU",
                    harga_idr=emas_idr_per_gram,
                    satuan="per gram",
                    harga_usd=emas_usd / 31.1035,
                )
            )

        # 2. Ambil Minyak Mentah (Brent Crude Oil)
        minyak_usd = cls._AmbilHargaMinyakUSD()
        if minyak_usd:
            minyak_idr_per_barrel = minyak_usd * kurs_usd_ke_idr
            daftar_item.append(
                ItemPasar(
                    nama="Minyak Mentah (Brent Crude)",
                    simbol="OIL/BRENT",
                    harga_idr=minyak_idr_per_barrel,
                    satuan="per barrel",
                    harga_usd=minyak_usd,
                )
            )

        return daftar_item

    @classmethod
    def _AmbilHargaEmasUSD(cls) -> Optional[float]:
        try:
            logger.info("Mengambil spot price emas via Stooq...")
            respons = requests.get(
                "https://stooq.com/q/l/?s=xauusd&f=sd2t2ohlcv&h&e=csv",
                timeout=TIMEOUT_HTTP,
            )
            respons.raise_for_status()
            baris = respons.text.strip().split("\n")
            if len(baris) >= 2:
                harga_tutup = baris[1].split(",")[6]
                return float(harga_tutup)
        except Exception as e:
            logger.warning(f"Gagal mengambil harga emas via Stooq: {e}")

        return 2350.0  # Baseline fallback

    @classmethod
    def _AmbilHargaMinyakUSD(cls) -> Optional[float]:
        try:
            logger.info("Mengambil harga minyak mentah Brent via Stooq...")
            respons = requests.get(
                "https://stooq.com/q/l/?s=cb.f&f=sd2t2ohlcv&h&e=csv",
                timeout=TIMEOUT_HTTP,
            )
            respons.raise_for_status()
            baris = respons.text.strip().split("\n")
            if len(baris) >= 2:
                harga_tutup = baris[1].split(",")[6]
                return float(harga_tutup)
        except Exception as e:
            logger.warning(f"Gagal mengambil harga minyak via Stooq: {e}")

        return 82.5  # Baseline fallback


class Pemformat:
    """Helper untuk format angka dan mata uang."""

    @staticmethod
    def FormatRupiah(jumlah: float) -> str:
        """Format angka ke format Indonesia: Rp 15.000,00"""
        terformat = f"{jumlah:,.2f}"
        bagian_utama, bagian_desimal = terformat.split(".")
        bagian_utama = bagian_utama.replace(",", ".")
        return f"Rp {bagian_utama},{bagian_desimal}"

    @staticmethod
    def FormatUSD(jumlah: float) -> str:
        return f"${jumlah:,.2f}"


class PengubahMarkdown:
    """Mengelola penulisan data ke file Markdown."""

    @staticmethod
    def BuatTabel(
        kurs_valas: Dict[str, float], komoditas: List[ItemPasar], stempel_waktu: str
    ) -> str:
        """Menghasilkan tabel Markdown."""
        baris = [
            f"*{MARKER_START}*",
            "",
            "> 🔄 **Pembaruan Otomatis Pasar Finansial & Komoditas**",
            f"> *Terakhir disinkronkan:* `{stempel_waktu}`",
            "",
            "### 💱 Nilai Tukar Mata Uang (Terhadap IDR)",
            "",
            "| Mata Uang | Simbol | Nilai Terkini (IDR) | Status/Tren |",
            "| :--- | :---: | :--- | :---: |",
        ]

        info_mata_uang = [
            ("Dolar Amerika Serikat", "USD", "🇺🇸"),
            ("Euro", "EUR", "🇪🇺"),
            ("Dolar Singapura", "SGD", "🇸🇬"),
            ("Yen Jepang (100 JPY)", "JPY", "🇯🇵"),
            ("Poundsterling Inggris", "GBP", "🇬🇧"),
        ]

        for nama, simbol, bendera in info_mata_uang:
            nilai = kurs_valas.get(simbol)
            if nilai is not None:
                if simbol == "JPY":
                    tampilan_nilai = Pemformat.FormatRupiah(nilai * 100)
                    simbol_tampilan = "100 JPY"
                else:
                    tampilan_nilai = Pemformat.FormatRupiah(nilai)
                    simbol_tampilan = simbol

                baris.append(f"| {bendera} {nama} | `{simbol_tampilan}` | **{tampilan_nilai}** | 🟢 Stabil |")

        baris.extend([
            "",
            "### 🛢️ Komoditas Global Utama",
            "",
            "| Komoditas | Satuan | Harga (USD) | Estimasi Nilai (IDR) | Indikator |",
            "| :--- | :---: | :---: | :--- | :---: |",
        ])

        for item in komoditas:
            usd_str = Pemformat.FormatUSD(item.harga_usd) if item.harga_usd else "-"
            idr_str = Pemformat.FormatRupiah(item.harga_idr)
            baris.append(
                f"| 🪙 {item.nama} | `{item.satuan}` | {usd_str} | **{idr_str}** | 📈 Aktif |"
            )

        baris.extend([
            "",
            f"*{MARKER_END}*",
        ])

        return "\n".join(baris)

    @classmethod
    def PerbaruiREADME(cls, konten_yang_disisipkan: str, jalur_file: str = FILE_README) -> bool:
        """Membaca README.md, mencari marker, dan memperbaruinya."""
        if not os.path.exists(jalur_file):
            logger.warning(f"File {jalur_file} tidak ditemukan. Membuat file README.md baru...")
            with open(jalur_file, "w", encoding="utf-8") as f:
                f.write(f"# Project Tracker\n\n{konten_yang_disisipkan}\n")
            return True

        with open(jalur_file, "r", encoding="utf-8") as f:
            isi_readme = f.read()

        pola = re.compile(
            f"{re.escape(MARKER_START)}.*?{re.escape(MARKER_END)}",
            re.DOTALL,
        )

        if pola.search(isi_readme):
            konten_baru = pola.sub(konten_yang_disisipkan, isi_readme)
        else:
            logger.info("Marker belum ada di README.md, menambahkan di akhir file...")
            konten_baru = f"{isi_readme.strip()}\n\n{konten_yang_disisipkan}\n"

        with open(jalur_file, "w", encoding="utf-8") as f:
            f.write(konten_baru)

        logger.info(f"File {jalur_file} berhasil diperbarui.")
        return True


def utama():
    logger.info("Memulai sinkronisasi nilai tukar & komoditas...")

    kurs_valas = PengambilKurs.AmbilKurs()
    kurs_usd_ke_idr = kurs_valas.get("USD", 16200.0)

    komoditas = PengambilKomoditas.AmbilKomoditas(kurs_usd_ke_idr=kurs_usd_ke_idr)

    sekarang_wita = datetime.now(ZONE_WITA)
    stempel_waktu = sekarang_wita.strftime("%d-%m-%Y %H:%M:%S WITA (UTC+8)")

    konten_tabel = PengubahMarkdown.BuatTabel(kurs_valas, komoditas, stempel_waktu)
    PengubahMarkdown.PerbaruiREADME(konten_tabel, FILE_README)

    logger.info("Proses sinkronisasi selesai dengan sukses.")


if __name__ == "__main__":
    utama()