"""
Génère README.md à partir de skills.json (bibliothèque standard uniquement).

    python scripts/build_readme.py            # écrit README.md
    python scripts/build_readme.py --check    # échoue si README.md n'est pas à jour

Pourquoi un générateur ?
Chaque groupe d'icônes demande plusieurs variantes d'URL (thème sombre/clair,
mobile/desktop). Les écrire à la main est long et source d'erreurs : on édite
skills.json, on relance le script, et le README reste cohérent.

Fonctionnement côté service (LelouchFR/skill-icons, go-skill-icons.vercel.app) :
  - ?i=a,b,c        liste d'icônes (ids ou alias, cf. README du service)
  - &theme=dark|light|auto   fond des icônes (auto = via prefers-color-scheme
                    *dans* le SVG, donc piloté par l'OS, pas par le thème GitHub)
  - &perline=N      nombre d'icônes par ligne (1..50, ne jamais mettre 0)
  - &titles=...     ATTENTION : activé dès que la valeur est non vide, même
                    "false". On ne l'utilise donc jamais.
  Chaque icône fait 48 px ; la largeur du SVG vaut (N*300-44)*48/256 px.
"""

from __future__ import annotations

import json
import math
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "skills.json"
OUT = ROOT / "README.md"

SERVICE = "https://go-skill-icons.vercel.app/api/icons"

# --- Réglages d'adaptation ---------------------------------------------------
MOBILE_MAX_WIDTH = 600  # px : en dessous, on utilise la mise en page "smartphone"
MOBILE_PER_LINE = 5  # 5 icônes = 273 px : tient sans réduction sur un écran de 320 px
DESKTOP_PER_LINE = 10  # 10 icônes = 554 px : confortable dans la colonne du README
# -----------------------------------------------------------------------------


def balanced_per_line(count: int, cap: int) -> int:
    """Nombre d'icônes par ligne <= cap, réparties équitablement (7 -> 4+3, pas 5+2)."""
    rows = math.ceil(count / cap)
    return math.ceil(count / rows)


def icon_url(ids: list[str], theme: str, per_line: int, *, srcset: bool) -> str:
    # Dans un srcset, la virgule est le séparateur de candidats : on encode celles
    # de la liste d'icônes (%2C) pour ne pas dépendre de l'analyseur de GitHub/camo.
    sep = "%2C" if srcset else ","
    return f"{SERVICE}?i={sep.join(ids)}&amp;theme={theme}&amp;perline={per_line}"


def picture(ids: list[str], alt: str, indent: str = "") -> str:
    """<picture> : thème sombre/clair (prefers-color-scheme) + perline adapté au mobile."""
    n = len(ids)
    desktop = n if n <= DESKTOP_PER_LINE else balanced_per_line(n, DESKTOP_PER_LINE)
    mobile = balanced_per_line(n, MOBILE_PER_LINE)

    sources: list[str] = []
    if mobile != desktop:  # sinon la variante mobile serait identique : inutile
        mq = f"(max-width: {MOBILE_MAX_WIDTH}px)"
        sources.append(
            f'<source media="{mq} and (prefers-color-scheme: dark)" '
            f'srcset="{icon_url(ids, "dark", mobile, srcset=True)}">'
        )
        sources.append(
            f'<source media="{mq}" '
            f'srcset="{icon_url(ids, "light", mobile, srcset=True)}">'
        )
    sources.append(
        f'<source media="(prefers-color-scheme: dark)" '
        f'srcset="{icon_url(ids, "dark", desktop, srcset=True)}">'
    )

    img = f'<img alt="{escape(alt)}" src="{icon_url(ids, "light", desktop, srcset=False)}">'
    lines = ["<picture>", *("  " + s for s in sources), "  " + img, "</picture>"]
    return "\n".join(indent + line for line in lines)


def link(name: str, url: str) -> str:
    return f'<a href="{escape(url)}">{escape(name)}</a>'


def group_block(group: dict) -> str:
    """Un groupe = un bloc centré : libellé, bandeau d'icônes, badges, légende cliquable."""
    skills = group["skills"]
    icons = [s for s in skills if "id" in s]
    badges = [s for s in skills if "badge" in s]

    parts = [f"  <b>{escape(group['label'])}</b>"]
    if icons:
        alt = ", ".join(s["name"] for s in icons)
        parts.append(picture([s["id"] for s in icons], alt, indent="  "))
    if badges:
        parts.append(
            "  "
            + "\n  ".join(
                f'<a href="{escape(b["url"])}"><img alt="{escape(b["name"])}" '
                f'src="{escape(b["badge"])}"></a>'
                for b in badges
            )
        )
    legend = " · ".join(link(s["name"], s["url"]) for s in skills)
    parts.append(
        f"  {legend}"
    )  # texte de taille normale : cibles tactiles plus faciles à viser

    return '<p align="center">\n' + "<br>\n".join(parts) + "\n</p>"


def profile_links(links: list[dict]) -> str:
    items = []
    for item in links:
        pic = picture([item["id"]], item["name"], indent="    ")
        items.append(
            f'  <a href="{escape(item["url"])}" title="{escape(item["name"])}">\n{pic}\n  </a>'
        )
    return '<p align="center">\n' + "\n".join(items) + "\n</p>"


def build(data: dict) -> str:
    out: list[str] = [
        "<!-- Fichier généré par scripts/build_readme.py à partir de skills.json : "
        "modifier skills.json, pas ce fichier. -->",
        "",
        f"# {data['about']['title']}",
        *("\n" + p for p in data["about"]["paragraphs"]),
        "",
        f"## {data['profiles']['title']}",
        "",
        profile_links(data["profiles"]["links"]),
        "",
        f"# {data['stack']['title']}",
    ]
    for section in data["stack"]["sections"]:
        out += ["", f"## {section['title']}", ""]
        out.append("\n\n".join(group_block(g) for g in section["groups"]))
    return "\n".join(out).replace("\n\n\n", "\n\n") + "\n"


def main() -> int:
    readme = build(json.loads(DATA.read_text(encoding="utf-8")))
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != readme:
            print("README.md n'est pas à jour : lancez python scripts/build_readme.py")
            return 1
        print("README.md est à jour.")
        return 0
    OUT.write_text(readme, encoding="utf-8")
    print(f"{OUT.name} généré ({readme.count(chr(10))} lignes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
