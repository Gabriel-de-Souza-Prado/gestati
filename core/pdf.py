"""Fontes incorporadas e serialização compartilhadas pelos PDFs do GESTATI."""
from pathlib import Path
from threading import Lock
import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

LOCK_GERACAO_PDF = Lock()
_FONTES = Path(reportlab.__file__).resolve().parent / "fonts"
pdfmetrics.registerFont(TTFont("Gestati", str(_FONTES / "Vera.ttf")))
pdfmetrics.registerFont(TTFont("GestatiBold", str(_FONTES / "VeraBd.ttf")))
pdfmetrics.registerFontFamily("Gestati", normal="Gestati", bold="GestatiBold")

