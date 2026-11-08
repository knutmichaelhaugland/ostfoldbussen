"""SMS-segmenttelling (GSM 03.38 / UCS-2) – stdlib, deterministisk.

Norske tegn æ/ø/å/Æ/Ø/Å ligger i GSM-7s standardalfabet og koster 1 septet.
Tegn som «» – · … ’ og liknende ligger IKKE i GSM-7 og tvinger hele meldingen
til UCS-2. Formatteringen vår saniterer derfor til GSM-7-vennlig tekst.
"""

from __future__ import annotations

from dataclasses import dataclass

# GSM 03.38 standardalfabet (uten extension-tabellen).
GSM7_BASIC = (
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ"
    " !\"#¤%&'()*+,-./0123456789:;<=>?¡"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿"
    "abcdefghijklmnopqrstuvwxyzäöñüà"
)
# Extension-tegn koster 2 septeter (ESC + tegn).
GSM7_EXTENSION = "^{}\\[~]|€"

GSM7_SINGLE_MAX = 160
GSM7_MULTI_MAX = 153
UCS2_SINGLE_MAX = 70
UCS2_MULTI_MAX = 67


@dataclass(frozen=True)
class SegmentInfo:
    encoding: str  # "GSM-7" eller "UCS-2"
    segments: int
    units: int  # septeter (GSM-7) eller UTF-16-kodeenheter (UCS-2)
    per_segment: int
    chars: int
    gsm7_safe: bool

    def as_text(self) -> str:
        return (
            f"{self.encoding}: {self.segments} segment(er), "
            f"{self.units}/{self.per_segment} per segment, {self.chars} tegn"
        )


def is_gsm7_safe(text: str) -> bool:
    return all(ch in GSM7_BASIC or ch in GSM7_EXTENSION for ch in text)


def gsm7_units(text: str) -> int:
    return sum(2 if ch in GSM7_EXTENSION else 1 for ch in text)


def ucs2_units(text: str) -> int:
    # Python-lengde er ikke det samme som UTF-16-kodeenheter for astraltegn.
    return len(text.encode("utf-16-le")) // 2


def count_segments(text: str) -> SegmentInfo:
    """Tell SMS-segmenter deterministisk.

    GSM-7: 160 tegn enkelt, 153 per del ved flere deler (7 septeter til UDH).
    UCS-2: 70 tegn enkelt, 67 per del ved flere deler.
    """
    if text is None:
        text = ""
    chars = len(text)
    if is_gsm7_safe(text):
        units = gsm7_units(text)
        if units <= GSM7_SINGLE_MAX:
            segments = 1 if units > 0 else 1
            per = GSM7_SINGLE_MAX
        else:
            segments = (units + GSM7_MULTI_MAX - 1) // GSM7_MULTI_MAX
            per = GSM7_MULTI_MAX
        return SegmentInfo("GSM-7", segments, units, per, chars, True)
    units = ucs2_units(text)
    if units <= UCS2_SINGLE_MAX:
        segments = 1
        per = UCS2_SINGLE_MAX
    else:
        segments = (units + UCS2_MULTI_MAX - 1) // UCS2_MULTI_MAX
        per = UCS2_MULTI_MAX
    return SegmentInfo("UCS-2", segments, units, per, chars, False)
