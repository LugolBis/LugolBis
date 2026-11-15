#!/usr/bin/env python3
"""
Construit le profil : copie les SVG dans le repo, puis génère README.md.
Bibliothèque standard uniquement.

    python scripts/build.py            # télécharge les SVG manquants + écrit README.md
    python scripts/build.py --check    # vérifie que tout est à jour (aucune écriture)

Principe : AUCUN appel à une API au moment de l'affichage. Le README pointe
directement vers les fichiers SVG de CE dépôt (raw.githubusercontent.com).

  assets/icons/    icônes copiées depuis LelouchFR/skill-icons (licence MIT, voir LICENSE)
                   - icône avec thèmes : <nom>-dark.svg + <nom>-light.svg
                   - icône sans thème  : <nom>.svg
  assets/badges/   badges générés par ce script (pas d'équivalent dans skill-icons)

Ajouter une compétence : ajouter une ligne dans skills.json ("icon" = nom du fichier
dans skill-icons, ex. "postgresql"), puis relancer ce script. Le téléchargement n'a lieu
qu'au premier ajout ; les SVG sont ensuite versionnés dans le dépôt.

Thème clair/sombre : balise <picture> + prefers-color-scheme (méthode documentée par GitHub).
Mise en page (settings.layout) : "columns" = un tableau par ensemble de colonnes (skills.json ->
"tables", organisation d'origine) ; "rows" = un tableau par section, une ligne par groupe
(plus étroit : ne déborde sur aucun écran). Les icônes ont une
taille fixe en px (icon_size) et passent à la ligne DANS leur cellule : les colonnes se resserrent
sur petit écran sans jamais réduire les icônes. Les cellules de plus de max_per_row icônes sont
réparties en lignes équilibrées (7 -> 4+3).
"""
from __future__ import annotations

import json
import math
import sys
import textwrap
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "skills.json"
OUT = ROOT / "README.md"
ICONS = ROOT / "assets" / "icons"
BADGES = ROOT / "assets" / "badges"

UPSTREAM = "https://raw.githubusercontent.com/LelouchFR/skill-icons/main"


# --------------------------------------------------------------------------- #
# 1. Icônes : copie locale des SVG
# --------------------------------------------------------------------------- #
def _download(path: str) -> bytes | None:
    try:
        with urllib.request.urlopen(f"{UPSTREAM}/{path}", timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _check_svg(name: str, raw: bytes) -> None:
    root = ET.fromstring(raw)  # lève une erreur si le XML est invalide
    if not root.tag.endswith("svg") or "viewBox" not in root.attrib:
        raise ValueError(f"{name}: SVG inattendu (balise racine ou viewBox manquants)")


def icon_files(icon: str) -> tuple[str, str] | None:
    """(fichier sombre, fichier clair) si l'icône a des thèmes, sinon None."""
    if (ICONS / f"{icon}-dark.svg").exists() and (ICONS / f"{icon}-light.svg").exists():
        return f"{icon}-dark.svg", f"{icon}-light.svg"
    return None


def has_icon(icon: str) -> bool:
    return icon_files(icon) is not None or (ICONS / f"{icon}.svg").exists()


def ensure_icon(icon: str) -> None:
    if has_icon(icon):
        return
    ICONS.mkdir(parents=True, exist_ok=True)
    dark, light = _download(f"assets/{icon}-dark.svg"), _download(f"assets/{icon}-light.svg")
    if dark and light:
        files = {f"{icon}-dark.svg": dark, f"{icon}-light.svg": light}
    else:
        plain = _download(f"assets/{icon}.svg")
        if plain is None:
            raise SystemExit(f"Icône introuvable dans skill-icons : « {icon} » "
                             f"(voir le dossier assets/ de LelouchFR/skill-icons)")
        files = {f"{icon}.svg": plain}
    for fname, raw in files.items():
        _check_svg(fname, raw)
        (ICONS / fname).write_bytes(raw)
        print(f"  + assets/icons/{fname}")


def ensure_license() -> None:
    target = ICONS / "LICENSE"
    if not target.exists():
        raw = _download("LICENSE")
        if raw:
            ICONS.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            print("  + assets/icons/LICENSE")


# --------------------------------------------------------------------------- #
# 2. Badges (technos absentes de skill-icons) : SVG générés localement
# --------------------------------------------------------------------------- #
def badge_slug(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())


def badge_svg(text: str, color: str, height: int) -> str:
    """Badge rectangulaire façon 'for-the-badge' : texte en capitales sur fond uni."""
    label = text.upper()
    r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    # Même règle de contraste que shields.io : texte sombre sur fond clair.
    fg = "#fff" if (r * 299 + g * 587 + b * 114) / 255000 <= 0.69 else "#333"
    text_len = round(8.2 * len(label) - 1, 1)  # estimation ; textLength force l'ajustement exact
    width = round(text_len + 2 * 12)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n'
        f'  <rect width="{width}" height="{height}" fill="#{color}"/>\n'
        f'  <text x="{width / 2}" y="{height / 2 + 3.5}" fill="{fg}" text-anchor="middle" '
        f'font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="10" font-weight="bold" '
        f'textLength="{text_len}" lengthAdjust="spacing">{escape(label)}</text>\n'
        f'</svg>\n'
    )


def write_badge(skill: dict, height: int, write: bool = True) -> str:
    fname = f"{badge_slug(skill['name'])}.svg"
    svg = badge_svg(skill["badge"]["text"], skill["badge"]["color"], height)
    ET.fromstring(svg)
    path = BADGES / fname
    if write and (not path.exists() or path.read_text(encoding="utf-8") != svg):
        BADGES.mkdir(parents=True, exist_ok=True)
        path.write_text(svg, encoding="utf-8", newline="\n")
    return fname


# --------------------------------------------------------------------------- #
# 3. README
# --------------------------------------------------------------------------- #
class Builder:
    def __init__(self, data: dict, write: bool = True) -> None:
        self.write = write
        s = data["settings"]
        self.base = s["base_url"].rstrip("/")
        self.size = int(s["icon_size"])
        self.badge_h = int(s["badge_height"])
        self.max_per_row = int(s.get("max_per_row", 5))
        self.layout = s.get("layout", "columns")
        if self.layout not in ("columns", "rows"):
            raise SystemExit('settings.layout doit valoir "columns" ou "rows"')

    def icon_url(self, fname: str) -> str:
        return f"{self.base}/assets/icons/{fname}"

    def icon(self, skill: dict) -> str:
        """Une icône cliquable. Avec thèmes : <picture> ; sinon : simple <img>."""
        name, dim = escape(skill["name"]), f'width="{self.size}" height="{self.size}"'
        themed = icon_files(skill["icon"])
        if themed:
            dark, light = themed
            inner = (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{self.icon_url(dark)}">'
                     f'<img alt="{name}" src="{self.icon_url(light)}" {dim}></picture>')
        else:
            inner = f'<img alt="{name}" src="{self.icon_url(skill["icon"] + ".svg")}" {dim}>'
        return f'<a href="{escape(skill["url"])}" title="{name}">{inner}</a>'

    def badge(self, skill: dict) -> str:
        fname = write_badge(skill, self.badge_h, self.write)
        name = escape(skill["name"])
        return (f'<a href="{escape(skill["url"])}" title="{name}"><img alt="{name}" '
                f'src="{self.base}/assets/badges/{fname}" height="{self.badge_h}"></a>')

    def cell_icons(self, group: dict) -> str:
        """Contenu de la cellule « icônes » : icônes (retour à la ligne automatique), puis badges."""
        skills = group["skills"]
        icons = [s for s in skills if "icon" in s]
        badges = [s for s in skills if "badge" in s]
        lines: list[str] = []
        if icons:
            # Au-delà de max_per_row, lignes équilibrées (7 -> 4+3) plutôt qu'une icône orpheline.
            per_row = math.ceil(len(icons) / math.ceil(len(icons) / self.max_per_row))
            for i in range(0, len(icons), per_row):
                lines.append("&nbsp;\n".join(self.icon(s) for s in icons[i:i + per_row]))
        if badges:
            lines.append("&nbsp;\n".join(self.badge(s) for s in badges))
        return "<br>\n".join(lines)

    def table(self, groups: list[dict]) -> str:
        """Un tableau : une colonne par groupe ; lignes = titre, icônes, légende cliquable."""
        def row(tag: str, cells: list[str], attrs: str) -> str:
            def cell(c: str) -> str:
                if "\n" not in c:  # cellule d'une ligne : balises sur la même ligne
                    return f"      <{tag} {attrs}>{c}</{tag}>"
                return f"      <{tag} {attrs}>\n" + textwrap.indent(c, "        ") + f"\n      </{tag}>"
            return "    <tr>\n" + "\n".join(cell(c) for c in cells) + "\n    </tr>"

        head = [escape(g["label"]) for g in groups]
        icons = [self.cell_icons(g) for g in groups]
        legend = [" · ".join(f'<a href="{escape(k["url"])}">{escape(k["name"])}</a>' for k in g["skills"])
                  for g in groups]
        return "\n".join([
            '<table align="center">',
            "  <thead>", row("th", head, 'align="center"'), "  </thead>",
            "  <tbody>",
            row("td", icons, 'align="center" valign="middle"'),
            row("td", legend, 'align="center" valign="top"'),
            "  </tbody>",
            "</table>",
        ])

    def table_rows(self, groups: list[dict]) -> str:
        """Variante « rows » : une ligne par groupe (titre | icônes + légende). Ne déborde jamais."""
        out = ['<table align="center">', "  <tbody>"]
        for g in groups:
            legend = " · ".join(f'<a href="{escape(k["url"])}">{escape(k["name"])}</a>' for k in g["skills"])
            body = self.cell_icons(g) + "<br>\n" + legend
            out += ["    <tr>", f'      <th align="center">{escape(g["label"])}</th>',
                    '      <td align="center">', textwrap.indent(body, "        "), "      </td>", "    </tr>"]
        return "\n".join(out + ["  </tbody>", "</table>"])

    def profiles(self, links: list[dict]) -> str:
        return '<p align="center">\n  ' + "&nbsp;\n  ".join(self.icon(s) for s in links) + "\n</p>"

    def readme(self, data: dict) -> str:
        out = [
            "<!-- Fichier généré par scripts/build.py à partir de skills.json : "
            "modifier skills.json, pas ce fichier. -->",
            "", f"# {data['about']['title']}",
            *("\n" + p for p in data["about"]["paragraphs"]),
            "", f"## {data['profiles']['title']}", "",
            self.profiles(data["profiles"]["links"]),
            "", f"# {data['stack']['title']}",
        ]
        for section in data["stack"]["sections"]:
            out += ["", f"## {section['title']}", ""]
            if self.layout == "rows":  # un seul tableau par section
                out.append(self.table_rows([g for t in section["tables"] for g in t]))
            else:
                out.append("\n\n".join(self.table(t) for t in section["tables"]))
        return "\n".join(out).replace("\n\n\n", "\n\n") + "\n"


def all_skills(data: dict):
    yield from data["profiles"]["links"]
    for section in data["stack"]["sections"]:
        for table in section["tables"]:
            for group in table:
                yield from group["skills"]


def main() -> int:
    check = "--check" in sys.argv
    data = json.loads(DATA.read_text(encoding="utf-8"))

    missing = sorted({s["icon"] for s in all_skills(data) if "icon" in s and not has_icon(s["icon"])})
    if check and missing:
        print("SVG manquants dans assets/icons :", ", ".join(missing))
        return 1
    if not check:
        for icon in missing:
            ensure_icon(icon)
        ensure_license()

    readme = Builder(data, write=not check).readme(data)
    if check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != readme:
            print("README.md n'est pas à jour : lancez python scripts/build.py")
            return 1
        print("Tout est à jour.")
        return 0
    OUT.write_text(readme, encoding="utf-8", newline="\n")
    print(f"{OUT.name} généré ({readme.count(chr(10))} lignes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
