"""vCard 3.0 for «Lagre Østfoldbussen i kontakter».

Filen bygges alltid fra PUBLIC_SMS_NUMBER via public-konteksten, slik at
telefonnummeret ikke kan avvike fra det nettsiden viser.
"""
from __future__ import annotations

from .templates import _display_number

NAME = "Østfoldbussen"
URL = "https://ostfoldbussen.no"
NOTE = ("Send SMS til dette nummeret for busstider og reiseinformasjon i Østfold. "
        "Ingen app eller internett nødvendig. Tjenesten er gratis, men vanlig "
        "SMS-takst kan gjelde.")


def _escape(value: str) -> str:
    r"""Escape vCard 3.0 special characters (\ ; , newline)."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def international_tel(raw: str) -> str:
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 8:
        digits = "47" + digits
    return "+" + digits


def _fold(line: str) -> str:
    """Fold a content line at 75 octets, continuing with a leading space."""
    data = line.encode("utf-8")
    if len(data) <= 75:
        return line
    parts = []
    first = True
    while data:
        limit = 75 if first else 74
        cut = min(limit, len(data))
        while cut > 0 and cut < len(data) and (data[cut] & 0xC0) == 0x80:
            cut -= 1
        parts.append(data[:cut].decode("utf-8"))
        data = data[cut:]
        first = False
    return "\r\n ".join(parts)


def build_vcard(number: str) -> str:
    tel = international_tel(number)
    if not tel.startswith("+47") or len(tel) != 11:
        raise ValueError("ugyldig norsk SMS-nummer")
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"N:{_escape(NAME)};;;;",
        f"FN:{_escape(NAME)}",
        f"TEL;TYPE=CELL:{tel}",
        f"URL:{URL}",
        f"NOTE:{_escape(NOTE)}",
        "END:VCARD",
    ]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def download_name() -> str:
    return "ostfoldbussen.vcf"


def content_disposition() -> str:
    return 'attachment; filename="ostfoldbussen.vcf"'
