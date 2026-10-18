"""A scenario's insight as a share card: a PNG laid out for a LinkedIn post, and its caption.

The card leads with the insight: a short title and a subtitle that join the question and its
answer (written from the checked answer, see agents/share.py; the checked headline without a
language model). Below them the key figures and the evidence chart (both computed by code, see
agents/evidence.py), and a footer with the source, how recent the data is, how the numbers were
made and a QR code to the open-source repository. Drawn with Pillow and the bundled open fonts
(Bricolage Grotesque, IBM Plex Sans), so it looks the same on every machine. No LLM here.

Sizes: ``portrait`` 1080 × 1350 (4:5, the largest image in the LinkedIn feed) and ``square``
1080 × 1080, rendered at ``scale`` × for sharp text.
"""

import io
import re
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from luxtrade.viz.format import fmt_pct, month_name

ASSETS = Path(__file__).with_name("assets")
REPO = "github.com/BDelfanian/luxtrade_lens"
SIZES = {"portrait": (1080, 1350), "square": (1080, 1080)}

NAVY, BLUE, RED, SKY = "#13213C", "#0B7DB8", "#C62F35", "#00A3E0"
INK, MUTED, FAINT, LINE = "#1F2937", "#5B6476", "#8A93A3", "#DCE3EC"
BG, WHITE, VIOLET = "#FAFBFC", "#FFFFFF", "#5B47D1"
TONE = {"down": "#D33A36", "up": "#0E8A45", "": VIOLET, "flat": VIOLET}
BARS = ["#E34948", "#2A78D6", "#6250D6"]
WHOLE = "#A3A29C"
SHADES = ["#9EC5F4", "#3987E5", "#184F95"]

_T = {
    "kicker": {
        "en": "WEEKLY TRADE INSIGHT",
        "fr": "LE COMMERCE EN UNE IMAGE",
        "de": "HANDEL IM BLICK",
    },
    "week": {"en": "Week {w} · {d}", "fr": "Semaine {w} · {d}", "de": "Woche {w} · {d}"},
    "data": {"en": "data to {m} {y}", "fr": "données jusqu'à {m} {y}", "de": "Daten bis {m} {y}"},
    "points": {"en": "Key points", "fr": "Points clés", "de": "Kernpunkte"},
    "source": {
        "en": "Source: Eurostat Comext DS-045409, Luxembourg's trade in goods, {data}.",
        "fr": "Source : Eurostat Comext DS-045409, commerce de biens du Luxembourg, {data}.",
        "de": "Quelle: Eurostat Comext DS-045409, Warenhandel Luxemburgs, {data}.",
    },
    "method": {
        "en": "Every number is computed by code from the official data and checked against "
        "the step it comes from; AI only plans the questions and words the answer.",
        "fr": "Chaque chiffre est calculé par le code à partir des données officielles et "
        "vérifié ; l'IA planifie les questions et formule la réponse.",
        "de": "Jede Zahl wird vom Code aus den amtlichen Daten berechnet und geprüft; die KI "
        "plant nur die Fragen und formuliert die Antwort.",
    },
    "how": {
        "en": "How: I asked LuxTrade Lens “{q}” It broke the question into {n} precise "
        "questions, answered each one from Eurostat's official trade data (Comext DS-045409) "
        "with guarded SQL, and checked every number in the answer against the step it came "
        "from ({data}).",
        "fr": "Comment : j'ai demandé à LuxTrade Lens « {q} » L'outil a décomposé la question "
        "en {n} questions précises, a répondu à chacune à partir des données officielles "
        "d'Eurostat (Comext DS-045409) avec du SQL contrôlé, et a vérifié chaque chiffre de la "
        "réponse ({data}).",
        "de": "So entstand es: Ich habe LuxTrade Lens gefragt: „{q}“ Das Tool hat die Frage in "
        "{n} präzise Fragen zerlegt, jede aus den amtlichen Eurostat-Daten (Comext DS-045409) "
        "mit geprüftem SQL beantwortet und jede Zahl der Antwort geprüft ({data}).",
    },
    "open": {"en": "Open source: {url}", "fr": "Open source : {url}", "de": "Open Source: {url}"},
}


def _t(key: str, lang: str, **values: object) -> str:
    return _T[key].get(lang, _T[key]["en"]).format(**values)


@dataclass
class CardContent:
    """What a card shows; ``content_from`` builds it from a scenario record."""

    title: str  # the insight, the card's large text
    subtitle: str  # one sentence: the question's context and the answer's evidence
    question: str  # the question as asked (in the caption, not on the card)
    data_note: str  # e.g. "data to Jun 2026"
    when: date
    lang: str = "en"
    topic: str = ""  # a short label above the title: the scenario's title
    tiles: list[dict] = field(default_factory=list)  # {"value", "label", "detail", "tone"}
    figure: dict | None = None  # an EvidenceFigure dump: kind, title, rows
    points: list[str] = field(default_factory=list)  # shown when there is no figure


def content_from(
    record: object, figures: list, data_note: str, share: dict | None = None
) -> CardContent:
    """A card for a scenario record, its first evidence figure and its share text.

    The share text comes from ``ScenarioBuilder.share``; without it, the checked headline.
    ``record`` is a ``runs.scenarios.ScenarioRecord``, ``figures`` ``EvidenceFigure``s.
    """
    first = figures[0] if figures else None
    share = share or {}
    return CardContent(
        title=share.get("title") or record.headline,
        subtitle=share.get("subtitle", first_sentence(record.conclusion)),
        question=record.question,
        topic=record.title,
        data_note=data_note,
        when=date.fromisoformat(record.created_at[:10]),
        lang=record.language,
        tiles=list(first.tiles) if first else [],
        figure=first.model_dump() if first else None,
        points=[p["text"] for p in record.points],
    )


def data_note(latest: date, lang: str = "en") -> str:
    """How recent the data is, e.g. "data to Jun 2026" (the latest complete month)."""
    return _t("data", lang, m=month_name(latest.month, lang), y=latest.year)


def first_sentence(text: str) -> str:
    """The first sentence of a paragraph."""
    found = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ])", text.strip(), maxsplit=1)
    return found[0] if found else ""


# --- drawing helpers ----------------------------------------------------------------------------
@cache
def _font(family: str, size: int, weight: int, opsz: int | None = None) -> ImageFont.FreeTypeFont:
    """A bundled font at a pixel size and weight (variable fonts: weight and optical size)."""
    path = {
        "display": "BricolageGrotesque.ttf",
        "sans": "IBMPlexSans.ttf",
        "italic": "IBMPlexSans-Italic.ttf",
    }[family]
    font = ImageFont.truetype(str(ASSETS / "fonts" / path), size)
    axes = [a["name"] for a in font.get_variation_axes()]
    values = {b"Weight": weight, b"Width": 100, b"Optical size": opsz or min(max(size, 12), 96)}
    font.set_variation_by_axes([values[a] for a in axes])
    return font


def _wrap(
    text: str,
    font: ImageFont.FreeTypeFont,
    width: float,
    max_lines: int,
    first: float | None = None,
) -> list[str]:
    """Words into lines that fit ``width``; the last kept line ends with … if text is cut.

    ``first`` is the width of the first line, when a lead-in precedes it.
    """
    lines: list[str] = []
    for word in text.split():
        trial = f"{lines[-1]} {word}" if lines else word
        room = first if first is not None and len(lines) == 1 else width
        if lines and font.getlength(trial) <= room:
            lines[-1] = trial
        else:
            lines.append(word)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and font.getlength(lines[-1] + " …") > width:
            lines[-1] = lines[-1].rsplit(" ", 1)[0] if " " in lines[-1] else lines[-1][:-1]
        lines[-1] += " …"
    return lines


class _Canvas:
    """A Pillow image addressed in logical pixels (``scale`` × in the file)."""

    def __init__(self, width: int, height: int, scale: int) -> None:
        self.s = scale
        self.w, self.h = width, height
        self.img = Image.new("RGB", (width * scale, height * scale), BG)
        self.draw = ImageDraw.Draw(self.img)

    def p(self, *values: float) -> list[int]:
        return [round(v * self.s) for v in values]

    def font(self, family: str, size: int, weight: int, opsz: int | None = None):  # noqa: ANN201
        return _font(family, size * self.s, weight, opsz or min(max(size, 12), 96))

    def rect(self, box: tuple, fill: str, radius: float = 0, outline: str | None = None) -> None:
        self.draw.rounded_rectangle(
            self.p(*box), radius=radius * self.s, fill=fill, outline=outline, width=self.s
        )

    def text(self, xy: tuple, text: str, font: object, fill: str, anchor: str = "la") -> None:
        self.draw.text(self.p(*xy), text, font=font, fill=fill, anchor=anchor)

    def lines(
        self, x: float, y: float, lines: list[str], font: object, fill: str, leading: float
    ) -> float:
        """Draw lines from the top; return the y below them."""
        for line in lines:
            self.text((x, y), line, font, fill)
            y += leading
        return y

    def length(self, text: str, font: object) -> float:
        return font.getlength(text) / self.s

    def tracked(self, xy: tuple, text: str, font: object, fill: str, em: float) -> float:
        """Text with letter-spacing, as the logo is set in the app; return the x after it.

        ``em`` × the font size is added after each letter (negative = tighter).
        """
        x, y = xy
        for ch in text:
            self.text((x, y), ch, font, fill)
            x += self.length(ch, font) + em * font.size / self.s
        return x


# --- the card -----------------------------------------------------------------------------------
def render_card(content: CardContent, size: str = "portrait", scale: int = 2) -> bytes:
    """The share card as PNG bytes."""
    width, height = SIZES[size]
    portrait = size == "portrait"
    c = _Canvas(width, height, scale)
    m = 60  # side margin
    lang = content.lang
    c.rect((0, 0, width, 7), RED)
    c.rect((0, 7, width, 14), SKY)

    # header: the logo on the left, the series and the date on the right
    logo = c.font("display", 44, 800, opsz=44)  # as in the app: ExtraBold, tracked -0.035 em
    x = c.tracked((m, 44), "LuxTrade", logo, NAVY, -0.035)
    c.tracked((x + c.length(" ", logo), 44), "Lens", logo, BLUE, -0.035)
    kicker = c.font("sans", 14, 700)
    label = _t("kicker", lang)
    pill_w = c.length(label, kicker) + 28
    c.rect((width - m - pill_w, 44, width - m, 72), RED, radius=14)
    c.text((width - m - pill_w / 2, 58), label, kicker, WHITE, anchor="mm")
    iso = content.when.isocalendar()
    day = content.when
    stamp = _t("week", lang, w=iso.week, d=f"{day.day} {month_name(day.month, lang)} {day.year}")
    c.text((width - m, 82), stamp, c.font("sans", 16, 400), MUTED, anchor="ra")
    c.rect((m, 118, width - m, 119), LINE)

    # the insight: topic label, title, subtitle (the question and its answer in one)
    full = (width - 2 * m) * c.s
    y = 140
    if content.topic:
        topic = c.font("sans", 15, 700)
        c.tracked((m, y), content.topic.upper(), topic, BLUE, 0.08)
        y += 32
    # the largest size at which the whole title fits three lines (never cut its meaning),
    # preferably without a lone word on its last line
    sizes = (64, 58, 54, 50, 46, 42, 38, 34) if portrait else (56, 52, 48, 44, 40, 36, 32)
    fits = [s for s in sizes if len(_wrap(content.title, c.font("display", s, 750), full, 99)) <= 3]
    size_px = next(
        (
            s
            for s in fits
            if len(lines := _wrap(content.title, c.font("display", s, 750), full, 99)) == 1
            or " " in lines[-1]
        ),
        fits[0] if fits else sizes[-1],
    )
    t_font = c.font("display", size_px, 750)
    t_lines = _wrap(content.title, t_font, full, 3)
    y = c.lines(m, y, t_lines, t_font, NAVY, round(size_px * 1.1)) + 12
    if content.subtitle:
        s_px = 24 if portrait else 22
        s_lines = _wrap(content.subtitle, c.font("sans", s_px, 400), full, 3)
        y = c.lines(m, y, s_lines, c.font("sans", s_px, 400), "#3A4458", round(s_px * 1.38))
    y += 22

    # the key figures
    tiles = content.tiles[:3]
    if tiles:
        tile_h = 150 if portrait else 128
        gap = 16
        tile_w = (width - 2 * m - gap * (len(tiles) - 1)) / len(tiles)
        for k, tile in enumerate(tiles):
            x0 = m + k * (tile_w + gap)
            color = TONE.get(tile.get("tone") or "", VIOLET)
            c.rect((x0, y, x0 + tile_w, y + tile_h), WHITE, radius=14, outline=LINE)
            c.rect((x0, y, x0 + tile_w, y + 6), color, radius=3)
            c.text((x0 + 18, y + 20), tile["value"], c.font("display", 40, 800), color)
            lab = _wrap(tile["label"], c.font("sans", 16, 600), (tile_w - 36) * c.s, 2)
            ty = c.lines(x0 + 18, y + 72, lab, c.font("sans", 16, 600), INK, 21)
            if tile.get("detail") and ty < y + tile_h - 22:
                detail = _wrap(tile["detail"], c.font("sans", 15, 400), (tile_w - 36) * c.s, 1)
                c.lines(x0 + 18, ty + 2, detail, c.font("sans", 15, 400), MUTED, 20)
        y += tile_h + 18

    # the footer at the bottom; the chart takes what is left
    foot_h = 160 if portrait else 148
    foot_y = height - foot_h
    _footer(c, content, foot_y, foot_h, m)
    box = (m, y, width - m, foot_y - 28)
    c.rect(box, WHITE, radius=16, outline=LINE)
    if content.figure and content.figure.get("rows"):
        _chart(c, content.figure, box, lang)
    else:
        _points(c, content.points, box, lang)

    buf = io.BytesIO()
    c.img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _footer(c: _Canvas, content: CardContent, y: float, h: float, m: float) -> None:
    """Navy band: source and data month, how the numbers were made, repository and its QR."""
    lang = content.lang
    c.rect((0, y, c.w, c.h), NAVY)
    qr_size = h - 44
    qr = (
        Image.open(ASSETS / "qr_repo.png")
        .convert("RGB")
        .resize(c.p(qr_size, qr_size), Image.Resampling.NEAREST)
    )
    qx = c.w - m - qr_size
    c.rect((qx - 6, y + 16, qx + qr_size + 6, y + 28 + qr_size), WHITE, radius=8)
    c.img.paste(qr, tuple(c.p(qx, y + 22)))
    text_w = (qx - 24 - m) * c.s
    small = c.font("sans", 14, 400)
    bold = c.font("sans", 15, 700)
    ty = y + 20
    for key, font, color in (("source", bold, WHITE), ("method", small, "#C9D3E3")):
        text = _t(key, lang, data=content.data_note)
        ty = c.lines(m, ty, _wrap(text, font, text_w, 2), font, color, 21) + 6
    c.text((m, y + h - 30), REPO, c.font("sans", 16, 700), "#7FD3F5")


def _ticks(lo: float, hi: float) -> list[float]:
    """Round gridline values between ``lo`` and ``hi`` (at most about six)."""
    span = hi - lo
    step = next(s for s in (5, 10, 20, 25, 50, 100, 200, 500, 1000) if span / s <= 6)
    first = int(lo // step) * step
    return [v for v in range(first, int(hi) + step, step) if lo <= v <= hi]


def _chart(c: _Canvas, fig: dict, box: tuple, lang: str) -> None:
    """The evidence chart: grouped bars, legend on top, value labels at the bar ends."""
    x0, y0, x1, y1 = box
    rows = fig["rows"]
    kind = fig.get("kind", "change")
    groups = list(dict.fromkeys(r["group"] for r in rows))
    series = list(dict.fromkeys(r["series"] for r in rows))
    if kind == "change":
        colors = BARS[: len(series) - 1] + [WHOLE]
    else:
        colors = SHADES[-len(series) :] if len(series) <= len(SHADES) else SHADES * 3
    title_font = c.font("sans", 18, 600)
    t_lines = _wrap(fig.get("title", ""), title_font, (x1 - x0 - 40) * c.s, 2)
    y = c.lines(x0 + 20, y0 + 16, t_lines, title_font, INK, 24) + 6
    legend = c.font("sans", 15, 500)
    lx = x0 + 20
    for name, color in zip(series, colors, strict=False):
        c.rect((lx, y + 4, lx + 14, y + 18), color, radius=3)
        c.text((lx + 20, y + 1), name, legend, MUTED)
        lx += 20 + c.length(name, legend) + 22
    top, bottom = y + 40, y1 - 46
    left, right = x0 + 64, x1 - 20
    values = [r["value"] for r in rows]
    if kind == "change":
        lo, hi = min(min(values) * 1.25, -10), max(max(values) * 1.25, 6)
    else:
        lo, hi = 0.0, max(values) * 1.25
    span = hi - lo or 1.0

    def ypos(v: float) -> float:
        return bottom - (v - lo) / span * (bottom - top)

    axis = c.font("sans", 14, 400)
    for t in _ticks(lo, hi):
        c.rect((left, ypos(t), right, ypos(t) + 0.6), LINE)
        tick = f"{t:g} %".replace("-", "−")  # a true minus, as in the value labels
        c.text((left - 10, ypos(t)), tick, axis, FAINT, anchor="rm")
    if kind == "change":
        c.rect((left, ypos(0) - 0.6, right, ypos(0) + 0.8), MUTED)
    group_w = (right - left) / len(groups)
    bar_w = min(group_w * 0.78 / len(series), 70 if len(rows) > 4 else 120)
    value_font = c.font("sans", 15, 600)
    label_font = c.font("sans", 15, 500)
    for gi, group in enumerate(groups):
        gx = left + gi * group_w + (group_w - bar_w * len(series)) / 2
        for si, name in enumerate(series):
            row = next((r for r in rows if r["group"] == group and r["series"] == name), None)
            if row is None:
                continue
            v = row["value"]
            bx = gx + si * bar_w
            ya, yb = sorted((ypos(0 if kind == "change" else lo), ypos(v)))
            c.rect((bx + 3, ya, bx + bar_w - 3, max(yb, ya + 1)), colors[si], radius=4)
            text = fmt_pct(v, lang, decimals=0 if kind == "change" else 1, signed=kind == "change")
            ty = ypos(v) - 8 if v >= 0 else ypos(v) + 8
            c.text((bx + bar_w / 2, ty), text, value_font, INK, anchor="ms" if v >= 0 else "mt")
        g_lines = _wrap(str(group), label_font, group_w * c.s - 8, 2)
        for li, line in enumerate(g_lines):
            c.text(
                (left + gi * group_w + group_w / 2, bottom + 12 + li * 18),
                line,
                label_font,
                MUTED,
                anchor="ma",
            )


def _points(c: _Canvas, points: list[str], box: tuple, lang: str) -> None:
    """Without a chart: the answer's key points, at the largest size that fills the box."""
    x0, y0, x1, y1 = box
    c.text((x0 + 24, y0 + 20), _t("points", lang), c.font("sans", 20, 700), INK)
    top, width = y0 + 64, (x1 - x0 - 76) * c.s
    # more points first, but readable (22 px or more): drop points before shrinking the text
    fits = False
    for n in range(min(len(points), 5), min(len(points), 1) - 1, -1):
        for size_px in (28, 26, 24, 22):
            font, leading = c.font("sans", size_px, 400), round(size_px * 1.4)
            wrapped = [_wrap(p, font, width, 99) for p in points[:n]]
            fits = top + sum(len(w) * leading + 18 for w in wrapped) <= y1 - 16
            if fits:
                break
        if fits:
            break
    if not fits:  # a very long first point: cut to fit
        font, leading = c.font("sans", 22, 400), 31
        wrapped = [_wrap(points[0], font, width, max(int((y1 - 16 - top) // 31), 1))]
    gap = (y1 - 16 - top - sum(len(w) * leading for w in wrapped)) / max(len(wrapped), 1)
    y = top
    for lines in wrapped:
        if y + len(lines) * leading > y1 - 12:
            break
        dot = y + leading / 2 - 4
        c.rect((x0 + 28, dot, x0 + 37, dot + 9), VIOLET, radius=3)
        y = c.lines(x0 + 52, y, lines, font, INK, leading) + min(gap, leading)


def linkedin_post(content: CardContent, steps: int, url: str = f"https://{REPO}") -> str:
    """A ready-to-paste LinkedIn caption for the card (the same checked words and figures)."""
    lines = [content.title, ""]
    if content.subtitle:
        lines += [content.subtitle, ""]
    for tile in content.tiles[:3]:
        detail = f" ({tile['detail']})" if tile.get("detail") else ""
        lines.append(f"▪ {tile['value']}: {tile['label']}{detail}")
    if content.tiles:
        lines.append("")
    lang = content.lang
    how = _t("how", lang, q=content.question, n=steps, data=content.data_note)
    lines += [
        how,
        "",
        _t("open", lang, url=url),
        "",
        "#Luxembourg #InternationalTrade #OpenData #Eurostat #DataVisualization #AI",
    ]
    return "\n".join(lines)
