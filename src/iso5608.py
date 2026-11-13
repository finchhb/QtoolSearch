"""src/iso5608.py - детерминированный разбор кодов инструментальной оснастки (без LLM).

ISO 5608 (наружные и расточные державки), резьбовые SER/SNR, канавочные KG*/MGEH/CGB,
блоки и лезвия KGFH. Вход - код из каталога или запроса, в том числе с пробелами,
дефисами, суффиксом Deskar «-M-A», кириллицей-омоглифами и в русской раскладке.

parse_holder_code("DCLNR 2525M-12-M-A") ->
    kind=external, clamp=D, shape=C, style=L, clearance=N, hand=R,
    shank_mm=25.0, length_letter=M, insert_size="12", series_key="DCLN-12"

Пластины, фрезы, свёрла, патроны и оправки не разбираются: для них возвращается None.
"""
import re
from typing import Any, Dict, Optional

from src.code_normalize import code_variants, normalize_separators

EXTERNAL = "external"
BORING = "boring"
THREAD_EXTERNAL = "thread_external"
THREAD_INTERNAL = "thread_internal"
GROOVING_EXTERNAL = "grooving_external"
GROOVING_INTERNAL = "grooving_internal"
GROOVING_FACE = "grooving_face"
BLADE = "blade"
BLOCK = "block"

_HANDS = set("LRN")
_THREAD_STYLES = ("SER", "SEL", "SNR", "SNL", "SWR", "SWL", "SVNR", "SVNL", "SCVER", "SCVEL", "CTTR", "CTTL")


def _mk(kind: str, **kw: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "kind": kind, "clamp": None, "shape": None, "style": None, "clearance": None,
        "hand": None, "shank_mm": None, "shank_width_mm": None, "shank_diameter_mm": None,
        "length_letter": None, "insert_size": None, "insert_type": None,
        "groove_width_mm": None, "groove_range_mm": None, "blade_height_mm": None,
        "min_bore_mm": None, "length_mm": None, "series_key": None, "turning": False,
    }
    out.update(kw)
    return out


def _num(text: Optional[str], default: Optional[float] = None) -> Optional[float]:
    if text is None:
        return default
    try:
        return float(str(text).replace(",", "."))
    except ValueError:
        return default


def _size_code(text: Optional[str]) -> Optional[str]:
    """«12» -> 12, «1504» -> 15, «09» -> 09; одна цифра размером не считается."""
    digits = re.sub(r"\D", "", text or "")
    return digits[:2] if len(digits) >= 2 else None


def _style_letters(style: str) -> Dict[str, Optional[str]]:
    """Первые буквы стиля державки: зажим, форма, стиль, задний угол, рука."""
    letters = [c for c in style if c.isalpha()]
    hand = letters[4] if len(letters) >= 5 and letters[4] in _HANDS else None
    clearance = letters[3] if len(letters) >= 4 else None
    if len(letters) == 4 and letters[3] in _HANDS:  # KGIR/CTTR: четвёртая буква — рука
        hand, clearance = letters[3], None
    clamp = letters[0] if letters else None
    shape = letters[1] if len(letters) >= 2 else None
    inner = letters[2] if len(letters) >= 3 else None
    return {"clamp": clamp, "shape": shape, "style": inner, "clearance": clearance, "hand": hand}


def _parse_one(s: str) -> Optional[Dict[str, Any]]:
    # --- блок и лезвия KGFH: 2020-26 это блок, 26-2-M - лезвие -------------------------------
    m = re.match(r"^KGFH-?(\d{2})(\d{2})-?(\d{2})(?:-?(.*))?$", s)
    if m:
        return _mk(BLOCK, clamp="K", shape="G", style="F", clearance="H",
                   shank_mm=float(m.group(1)), shank_width_mm=float(m.group(2)),
                   blade_height_mm=float(m.group(3)), series_key=f"KGFH-{m.group(3)}")
    m = re.match(r"^KGFH-?(\d{2})-?(\d{1,4}(?:[.,]\d+)?)(?:-?(.*))?$", s)
    if m:
        width = _num(m.group(2))
        return _mk(BLADE, clamp="K", shape="G", style="F", clearance="H",
                   blade_height_mm=float(m.group(1)), groove_width_mm=width,
                   series_key=f"KGFH-{m.group(1)}-{m.group(2)}")

    # --- торцевые канавки KGFDR 2020K-2535-3-M ------------------------------------------------
    m = re.match(r"^KGFD([LR])-?(\d{2})(\d{2})([A-Z])?-?(\d{2})(\d{2})-?(\d{1,4}(?:[.,]\d+)?)(?:-?(.*))?$", s)
    if m:
        width = _num(m.group(7))
        return _mk(GROOVING_FACE, clamp="K", shape="G", style="F", clearance="D", hand=m.group(1),
                   shank_mm=float(m.group(2)), shank_width_mm=float(m.group(3)),
                   length_letter=m.group(4), groove_width_mm=width,
                   groove_range_mm=f"{m.group(5)}-{m.group(6)}",
                   series_key=f"KGFD-{m.group(7)}")

    # --- наружные канавки KGDR 2525M-3T20-M ---------------------------------------------------
    m = re.match(r"^KGD([LR])-?(\d{2})(\d{2})([A-Z])?-?(\d+)T(\d+)(?:-?(.*))?$", s)
    if m:
        return _mk(GROOVING_EXTERNAL, clamp="K", shape="G", style="D", hand=m.group(1),
                   shank_mm=float(m.group(2)), shank_width_mm=float(m.group(3)),
                   length_letter=m.group(4), groove_width_mm=float(m.group(5)),
                   series_key=f"KGD-{m.group(5)}")

    # --- канавочные MGEH/MGEV и внутренние MGIV: MGEHR2020-3C, MGIVR2016-1.5 -------------
    m = re.match(r"^(MGEH|MGEV)([LR])(\d{2})(\d{2})-?(\d{1,4}(?:[.,]\d+)?)(?:-?([A-Z0-9]*))?$", s)
    if m:
        return _mk(GROOVING_EXTERNAL, clamp="M", shape="G", style="E", clearance=m.group(1)[3],
                   hand=m.group(2), shank_mm=float(m.group(3)), shank_width_mm=float(m.group(4)),
                   groove_width_mm=_num(m.group(5)), series_key=f"{m.group(1)}-{m.group(5)}")
    m = re.match(r"^MGIV([LR])(\d{2})(\d{2})-?(\d{1,4}(?:[.,]\d+)?)(?:-?([A-Z0-9]*))?$", s)
    if m:
        return _mk(GROOVING_INTERNAL, clamp="M", shape="G", style="I", clearance="V",
                   hand=m.group(1), shank_mm=float(m.group(2)), shank_width_mm=float(m.group(3)),
                   groove_width_mm=_num(m.group(4)), series_key=f"MGIV-{m.group(4)}")

    # --- отрезные TTER/TTEL и QEKS ------------------------------------------------------------
    m = re.match(r"^TTE([LR])(\d{2})(\d{2})-?(\d{1,4}(?:[.,]\d+)?)(?:-?([A-Z0-9]*))?$", s)
    if m:
        return _mk(GROOVING_EXTERNAL, clamp="T", shape="T", style="E", hand=m.group(1),
                   shank_mm=float(m.group(2)), shank_width_mm=float(m.group(3)),
                   groove_width_mm=_num(m.group(4)), series_key=f"TTE-{m.group(4)}")
    m = re.match(r"^QEKS(\d{2})(\d{2})([A-Z])?-?(\d{2})$", s)
    if m:
        return _mk(GROOVING_EXTERNAL, clamp="Q", shape="E", style="K",
                   shank_mm=float(m.group(1)), shank_width_mm=float(m.group(2)),
                   length_letter=m.group(3), insert_size=m.group(4),
                   series_key=f"QEK-{m.group(4)}")

    # --- отрезные CGBL/CGBR -------------------------------------------------------------------
    m = re.match(r"^CGB([LR])(\d{2})(\d{2})([A-Z])?-?(\d{2})$", s)
    if m:
        return _mk(GROOVING_EXTERNAL, clamp="C", shape="G", style="B", hand=m.group(1),
                   shank_mm=float(m.group(2)), shank_width_mm=float(m.group(3)),
                   length_letter=m.group(4), insert_size=m.group(5),
                   series_key=f"CGB-{m.group(5)}")

    # --- канавочные KTGFR/KTGFSL --------------------------------------------------------------
    m = re.match(r"^KTGF([A-Z]?)([LR])(\d{2})(\d{2})([A-Z])?-?(\d{2})$", s)
    if m:
        return _mk(GROOVING_EXTERNAL, clamp="K", shape="T", style="G", clearance="F", hand=m.group(2),
                   shank_mm=float(m.group(3)), shank_width_mm=float(m.group(4)),
                   length_letter=m.group(5), insert_size=m.group(6),
                   series_key=f"KTGF-{m.group(6)}")

    # --- канавочные GQCR ----------------------------------------------------------------------
    m = re.match(r"^GQC([LR])(\d{2})(\d{2})([A-Z])?-?(\d{2})(?:-(\d+))?$", s)
    if m:
        return _mk(GROOVING_EXTERNAL, clamp="G", shape="Q", style="C", hand=m.group(1),
                   shank_mm=float(m.group(2)), shank_width_mm=float(m.group(3)),
                   length_letter=m.group(4), insert_size=m.group(5),
                   series_key=f"GQC-{m.group(5)}")

    # --- внутренние канавки HNGR08J07 ---------------------------------------------------------
    m = re.match(r"^HNG([LR])(\d{2})([A-Z])(\d{2})$", s)
    if m:
        return _mk(GROOVING_INTERNAL, clamp="H", shape="N", style="G", hand=m.group(1),
                   shank_diameter_mm=float(m.group(2)), length_letter=m.group(3),
                   insert_size=m.group(4), series_key=f"HNG-{m.group(4)}")

    # --- торцевые канавки FGHH: размеры живут в названии, код даёт только серию ---------------
    m = re.match(r"^FGHH$", s)
    if m:
        return _mk(GROOVING_FACE, clamp="F", shape="G", style="H", clearance="H", series_key="FGHH")

    # --- борштанги EWB1608-32 -----------------------------------------------------------------
    m = re.match(r"^EWB(\d{2})(\d{2})-?(\d{2,3})$", s)
    if m:
        return _mk(BORING, clamp="E", shape="W", style="B",
                   shank_diameter_mm=float(m.group(1)),
                   length_mm=float(m.group(3)), series_key=f"EWB-{m.group(1)}")

    # --- резьбовые SER/SNR/SWR/SVNR/SCVER/CTTR ----------------------------------------------
    style_alt = "|".join(sorted(_THREAD_STYLES, key=len, reverse=True))
    m = re.match(
        rf"^({style_alt})-?(\d{{2}})(\d{{2}})([A-Z])?-?(\d{{1,4}})(?:-?([A-Z0-9-]*))?$", s
    )
    if m:
        style, a, b, length, size = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        internal = style[1] == "N"
        diameter = float(b) if a == "00" else None
        shank = None if diameter is not None else float(a)
        width = None if diameter is not None else float(b)
        size_code = _size_code(size)
        return _mk(THREAD_INTERNAL if internal else THREAD_EXTERNAL,
                   clamp=style[0], shape=style[1], style=style[2:], hand=style[-1],
                   shank_mm=shank, shank_width_mm=width, shank_diameter_mm=diameter,
                   length_letter=length, insert_size=size_code,
                   insert_type=f"{size_code}{'IR' if internal else 'ER'}" if size_code else None,
                   series_key=f"{style}-{size_code or size}")

    # --- расточные: S16Q-SCLCR-09-M-A, S16Q-KGIR-3, C06K-SCLCR06, S25S-2MWN08-33 -----------
    m = re.match(
        r"^([SCEH])(\d{2})(\d{2})?([A-Z])-?([A-Z0-9]{2,6}?)-?(\d{1,4}(?:[.,]\d+)?)(?:-?([A-Z0-9-]*))?$", s
    )
    if m:
        base = m.group(5)
        letters = _style_letters(base)
        min_bore = None
        if m.group(7):
            a = re.match(r"^A(\d{1,3})$", m.group(7))
            if a:
                min_bore = float(a.group(1))
        size_code = _size_code(m.group(6))
        width = None
        kind = BORING
        insert_type = None
        if base.startswith("KGI"):
            kind = GROOVING_INTERNAL
            width = _num(m.group(6))
            size_code = None
        elif base.startswith("CTT"):
            kind = THREAD_EXTERNAL
            insert_type = f"{size_code}ER" if size_code else None
        return _mk(kind, **letters,
                   shank_diameter_mm=float(m.group(2)), length_letter=m.group(4),
                   insert_size=size_code, insert_type=insert_type,
                   groove_width_mm=width, min_bore_mm=min_bore,
                   series_key=f"{base[:4]}-{size_code or m.group(6)}",
                   turning=kind == BORING)

    # --- наружные державки: DCLNR2525M12, DCLNR 2525M-12-M-A, DDJNR2020K1504 -----------------
    m = re.match(r"^([A-Z]{4})([LRN])-?(\d{2})(\d{2})([A-Z])?-?(\d{1,4})?(?:-?([A-Z0-9-]*))?$", s)
    if m:
        size = _size_code(m.group(6))
        return _mk(EXTERNAL, clamp=m.group(1)[0], shape=m.group(1)[1], style=m.group(1)[2],
                   clearance=m.group(1)[3], hand=m.group(2),
                   shank_mm=float(m.group(3)), shank_width_mm=float(m.group(4)),
                   length_letter=m.group(5), insert_size=size,
                   series_key=f"{m.group(1)}-{size or m.group(6) or '?'}", turning=True)
    return None


def parse_holder_code(code: Optional[str]) -> Optional[Dict[str, Any]]:
    """Код оснастки -> поля ISO 5608 или None, если это не державка/резец."""
    if not code:
        return None
    for variant in code_variants(code):
        parsed = _parse_one(normalize_separators(variant.upper()))
        if parsed:
            parsed["code"] = normalize_separators(variant.upper())
            return parsed
    return None
