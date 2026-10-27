#!/usr/bin/env python3
"""Generate profile SVGs. Python 3.11+, standard library only."""

import argparse
from collections import Counter
from datetime import datetime
from html import escape
import json
import os
from pathlib import Path
import re
import textwrap
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
USER = "soy-jhonatan"
PINS = ["tetris", "performance.js", "ar-project", "reproductor-musical"]
COLORS = {"JavaScript": "#f1e05a", "TypeScript": "#3178c6", "HTML": "#e34c26",
          "CSS": "#a78bfa", "Astro": "#ff5a03", "Svelte": "#ff3e00",
          "Python": "#3572a5", "PHP": "#8e9ad4", "Shell": "#89e051"}
BG, LINE, TEXT, MUTED, PINK, CYAN = "#1f222e", "#343947", "#e6edf3", "#9da7b5", "#f75c7e", "#58c7f3"


class GitHubError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Consulta a GitHub fallida (HTTP {status}). No se actualizaron las tarjetas.")


class API:
    def __init__(self, token):
        self.headers = {"Accept": "application/vnd.github+json", "User-Agent": "soy-jhonatan-profile",
                        "X-GitHub-Api-Version": "2026-03-10"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def get(self, path, **params):
        url = "https://api.github.com" + path
        if params:
            url += "?" + urlencode(params)
        for attempt in range(3):
            try:
                with urlopen(Request(url, headers=self.headers), timeout=45) as response:
                    return json.load(response)
            except HTTPError as error:
                if error.code in (429, 500, 502, 503, 504) and attempt < 2:
                    retry = error.headers.get("Retry-After", "")
                    time.sleep(min(30, int(retry) if retry.isdigit() else 3 * (attempt + 1)))
                    continue
                raise GitHubError(error.code) from None
            except (URLError, TimeoutError):
                if attempt == 2:
                    raise RuntimeError("No fue posible conectar con GitHub. Se conservan las tarjetas anteriores.") from None
                time.sleep(3)

    def pages(self, path, **params):
        page = 1
        while True:
            items = self.get(path, **params, per_page=100, page=page)
            if not isinstance(items, list):
                raise RuntimeError("Respuesta inesperada de GitHub; se cancela el conteo.")
            yield from items
            if len(items) < 100:
                return
            page += 1


def collect(api, include_private=False, extras=()):
    public = list(api.pages(f"/users/{USER}/repos", type="owner"))
    repositories = {repo["full_name"].lower(): repo for repo in public}
    if include_private:
        if api.get("/user")["login"].lower() != USER:
            raise RuntimeError("El secreto PROFILE_STATS_TOKEN debe pertenecer a soy-jhonatan.")
        for repo in api.pages("/user/repos", affiliation="owner", visibility="all"):
            if repo["owner"]["login"].lower() == USER:
                repositories[repo["full_name"].lower()] = repo
    for full_name in extras:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
            raise RuntimeError("EXTRA_REPOSITORIES contiene un identificador inválido.")
        repo = api.get("/repos/" + full_name)
        repositories[repo["full_name"].lower()] = repo

    # A SHA is counted globally once, including shared histories across forks.
    commits, branches = {}, 0
    for repo in repositories.values():
        if repo.get("disabled"):
            raise RuntimeError("Un repositorio no está accesible. Se cancela para evitar publicar un total incompleto.")
        path = "/repos/" + repo["full_name"]
        try:
            heads = list(api.pages(path + "/branches"))
        except GitHubError as error:
            if error.status == 409 and repo.get("size") == 0:
                continue
            raise
        branches += len(heads)
        # Query an immutable head SHA: branch names may contain slashes or move.
        for head in sorted({branch["commit"]["sha"] for branch in heads}):
            for item in api.pages(path + "/commits", sha=head, author=USER):
                author = item.get("author") or {}
                if author.get("login", "").lower() == USER:
                    date = item["commit"]["author"]["date"]
                    commits.setdefault(item["sha"], date)

    languages = Counter()
    for repo in public:
        if not repo.get("fork") and not repo.get("disabled"):
            languages.update(api.get("/repos/" + repo["full_name"] + "/languages"))

    now = datetime.now(ZoneInfo("America/Bogota"))
    month_counts = Counter()
    for date in commits.values():
        authored = datetime.fromisoformat(date.replace("Z", "+00:00")).astimezone(ZoneInfo("America/Bogota"))
        month_counts[authored.strftime("%Y-%m")] += 1
    return {"commits": len(commits), "repos": len(repositories), "branches": branches,
            "stars": sum(repo.get("stargazers_count", 0) for repo in public),
            "languages": dict(languages), "monthly": dict(month_counts),
            "pins": {repo["name"]: repo for repo in public if repo["name"] in PINS},
            "updated": now.strftime("%d/%m/%Y"), "ready": True}


def txt(x, y, value, size=14, fill=TEXT, weight=400, anchor="start"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
            f'font-weight="{weight}" text-anchor="{anchor}">{escape(str(value))}</text>')


def card(width, height, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title, quote=True)}">'
            f'<title>{escape(title)}</title><rect x="0.5" y="0.5" width="{width-1}" height="{height-1}" '
            f'rx="9" fill="{BG}" stroke="{LINE}"/>'
            f'<g font-family="DejaVu Sans,Segoe UI,Arial,sans-serif">{body}</g></svg>\n')


def number(value):
    return "—" if value is None else f"{value:,}".replace(",", ".")


def stats_svg(data):
    body = txt(24, 36, "Mis estadísticas en GitHub", 20, PINK, 600)
    rows = [("Commits únicos", data.get("commits")), ("Repositorios analizados", data.get("repos")),
            ("Ramas analizadas", data.get("branches")), ("Estrellas públicas", data.get("stars"))]
    for i, (label, value) in enumerate(rows):
        y = 77 + i * 30
        body += txt(25, y, "•", 18, CYAN) + txt(43, y, label, 14, TEXT, 500)
        body += txt(304, y, number(value), 16, TEXT, 700, "end")
    body += f'<circle cx="408" cy="112" r="44" fill="none" stroke="{LINE}" stroke-width="8"/>'
    body += f'<circle cx="408" cy="112" r="44" fill="none" stroke="{CYAN}" stroke-width="8" stroke-dasharray="218 60" transform="rotate(-90 408 112)"/>'
    body += txt(408, 113, "GIT", 22, CYAN, 700, "middle")
    body += txt(408, 132, "TODAS LAS RAMAS", 7, MUTED, 600, "middle")
    footer = ("SHA únicos · repositorios configurados · " + data.get("updated", "")) if data.get("ready") else "Pendiente de la primera ejecución de GitHub Actions"
    body += txt(25, 207, footer, 10, MUTED)
    return card(495, 228, body, "Commits únicos de todas las ramas analizadas")


def languages_svg(data):
    body = txt(24, 36, "Lenguajes en mis repositorios", 20, PINK, 600)
    entries = sorted(data.get("languages", {}).items(), key=lambda entry: (-entry[1], entry[0]))[:8]
    if not entries:
        body += txt(24, 95, "Se actualiza con GitHub Actions", 14, MUTED)
    else:
        total = sum(data["languages"].values())
        x = 24.0
        for index, (lang, size) in enumerate(entries):
            width = 447 * size / total
            color = COLORS.get(lang, "#8b949e")
            body += f'<rect x="{x:.2f}" y="58" width="{width:.2f}" height="10" fill="{color}"/>'
            x += width
            cx, cy = 29 + (index % 2) * 229, 96 + (index // 2) * 27
            body += f'<circle cx="{cx}" cy="{cy-4}" r="4.5" fill="{color}"/>'
            body += txt(cx+12, cy, f"{lang} {size/total:.1%}", 12)
        if len(data["languages"]) > 8:
            body += f'<rect x="{x:.2f}" y="58" width="{max(0,471-x):.2f}" height="10" fill="{LINE}"/>'
    body += txt(24, 207, "Código público · ramas predeterminadas · sin forks", 10, MUTED)
    return card(495, 228, body, "Distribución de lenguajes por bytes de código público")


def pin_svg(name, repo):
    body = txt(23, 33, name, 19, PINK, 600)
    description = repo.get("description") or "Explora el código y los detalles del proyecto."
    description = " ".join(description.split())
    lines = textwrap.wrap(description, width=60)[:2]
    if len(description) > sum(map(len, lines)) + 2 and lines:
        lines[-1] = lines[-1].rstrip(". ") + "…"
    for index, line in enumerate(lines):
        body += txt(23, 64+index*20, line, 12, TEXT)
    lang = repo.get("language") or "Código"
    body += f'<circle cx="28" cy="116" r="5" fill="{COLORS.get(lang, MUTED)}"/>'
    body += txt(41, 120, lang, 12, MUTED)
    stars = repo.get("stargazers_count")
    if stars is not None:
        body += txt(245, 120, f"★ {number(stars)}", 12, "#f8d866")
    body += txt(470, 120, "Ver repositorio →", 11, MUTED, anchor="end")
    return card(495, 145, body, f"Repositorio {name}")


def activity_svg(data):
    body = txt(25, 35, "Un año construyendo", 20, PINK, 600)
    body += txt(25, 58, "Commits únicos por mes · todas las ramas analizadas", 12, MUTED)
    if not data.get("ready"):
        body += txt(25, 135, "El gráfico aparecerá al ejecutar GitHub Actions.", 15, MUTED)
        return card(1000, 260, body, "Actividad mensual pendiente de actualización")
    today = datetime.now(ZoneInfo("America/Bogota"))
    index = today.year * 12 + today.month - 1
    months = [f"{(index-offset)//12:04d}-{(index-offset)%12+1:02d}" for offset in range(11, -1, -1)]
    counts = [data.get("monthly", {}).get(month, 0) for month in months]
    maximum = max(counts, default=0) or 1
    names = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    for i, (month, count) in enumerate(zip(months, counts)):
        x, height = 38 + i * 79, 116 * count / maximum
        body += f'<rect x="{x}" y="{204-height:.2f}" width="47" height="{max(1,height):.2f}" rx="4" fill="{PINK if i==11 else CYAN}" opacity="{1 if i==11 else 0.65}"/>'
        body += txt(x+23, 193-height, number(count), 11, TEXT, anchor="middle")
        body += txt(x+23, 226, names[int(month[-2:])-1], 11, MUTED, anchor="middle")
        body += txt(x+23, 242, month[:4], 8, MUTED, anchor="middle")
    return card(1000, 260, body, "Commits únicos en los últimos doce meses")


def initial_data():
    return {"ready": False, "pins": {
        "tetris": {"language": "JavaScript", "description": "Un juego de Tetris desarrollado en JavaScript."},
        "performance.js": {"language": "JavaScript"},
        "ar-project": {"language": "TypeScript"},
        "reproductor-musical": {"language": "Astro", "description": "Interfaz musical para practicar CSS y Tailwind."}}}


def render(data, root=ROOT):
    assets = root / "assets"
    (assets / "repos").mkdir(parents=True, exist_ok=True)
    header = ('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="78" viewBox="0 0 800 78" role="img">'
              '<title>Jhonatan Portocarrero · soy-jhonatan</title>'
              '<text x="400" y="45" text-anchor="middle" fill="#f75c7e" font-size="29" '
              'font-family="DejaVu Sans Mono,Fira Code,monospace">Jhonatan Portocarrero</text>'
              '<text x="400" y="69" text-anchor="middle" fill="#9da7b5" font-size="11" '
              'font-family="DejaVu Sans Mono,monospace">&lt; soy-jhonatan /&gt;</text></svg>\n')
    outputs = {"header.svg": header, "stats.svg": stats_svg(data),
               "languages.svg": languages_svg(data), "activity.svg": activity_svg(data)}
    for name in PINS:
        outputs[f"repos/{name}.svg"] = pin_svg(name, data.get("pins", {}).get(name, {}))
    # All requests succeed before anything is written. No secrets, repo lists or SHAs are saved.
    for name, svg in outputs.items():
        (assets / name).write_text(svg, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initialize", action="store_true", help="Generate initial cards without network or invented totals.")
    args = parser.parse_args()
    if args.initialize:
        data = initial_data()
    else:
        token = os.environ.get("PROFILE_STATS_TOKEN") or os.environ.get("GH_TOKEN", "")
        extras = [value.strip() for value in re.split(r"[,\n]", os.environ.get("EXTRA_REPOSITORIES", "")) if value.strip()]
        data = collect(API(token), os.environ.get("INCLUDE_PRIVATE", "false").lower() == "true", extras)
    render(data)
    print("Tarjetas generadas correctamente." if not data.get("ready") else f"Tarjetas actualizadas: {data['commits']} commits únicos.")


if __name__ == "__main__":
    main()
