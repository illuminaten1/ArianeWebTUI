#!/usr/bin/env python3
"""
ArianeWeb — Interface Terminal (TUI)
Usage: python3 arianeweb.py [requête]
       python3 arianeweb.py  (lance l'interface interactive)
"""

import sys
import json
import time
import re
import threading
import urllib.request
import urllib.parse
from datetime import datetime
from html.parser import HTMLParser

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Static,
)
from textual import work

# ---------------------------------------------------------------------------
# Constantes API
# ---------------------------------------------------------------------------

SEARCH_URL  = "https://www.conseil-etat.fr/xsearch?type=json"
CONTENT_URL = "https://www.conseil-etat.fr/plugin?plugin=Service.callXdownloadAW&action=Search"
ARIANE_BASE = "https://www.conseil-etat.fr/fr/arianeweb"

SOURCES = [
    ("AW_DCE", "CE"),
    ("AW_DCA", "CAA"),
]

SEARCH_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer":       "https://www.conseil-etat.fr/arianeweb/",
    "Accept":        "application/json",
}

CONTENT_HEADERS = {
    "Content-Type": "application/json",
    "Referer":       "https://www.conseil-etat.fr/arianeweb/",
}

PAGE_SIZE     = 50
REQUEST_DELAY = 0.3


# ---------------------------------------------------------------------------
# Extraction HTML → texte
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    BLOCK_TAGS = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6",
                  "li", "tr", "td", "th", "blockquote", "pre", "article"}
    SKIP_TAGS  = {"script", "style", "head", "noscript"}

    def __init__(self):
        super().__init__()
        self._parts = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._depth += 1
        elif self._depth == 0 and tag in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            self._depth = max(0, self._depth - 1)
        elif self._depth == 0 and tag in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data):
        if self._depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.get_text()


_OPERATORS = {"ET", "OU", "SAUF"}

# Tokenise une requête ArianeWeb :
#   groupe 1 : «expression exacte» (guillemets français)
#   groupe 2 : "expression exacte" (guillemets ASCII)
#   groupe 3 : token libre (peut contenir des jokers ? et *)
_QUERY_TOKEN_RE = re.compile(
    r'[«\u00ab]([^\u00bb»]+)[»\u00bb]'
    r'|"([^"]+)"'
    r'|(\S+)'
)


def parse_query_terms(query: str) -> list[str]:
    """
    Retourne les termes/expressions à surligner issus d'une requête ArianeWeb.
    - Les opérateurs ET, OU, SAUF sont exclus.
    - Les expressions entre guillemets sont conservées comme un seul bloc.
    - Les jokers ? et * sont convertis en motifs regex (. et .*).
    Chaque élément retourné est un motif regex prêt à l'emploi.
    """
    patterns = []
    for m in _QUERY_TOKEN_RE.finditer(query):
        phrase = m.group(1) or m.group(2)
        if phrase:
            # Expression entre guillemets → mot/phrase exacts (délimiteurs de mot)
            patterns.append(r'\b' + re.escape(phrase.strip()) + r'\b')
            continue
        token = m.group(3)
        if not token or token.upper() in _OPERATORS or len(token) < 2:
            continue
        if '?' in token or '*' in token:
            # Convertit les jokers ArianeWeb en motifs regex (pas de \b : le joker
            # peut lui-même représenter la fin du mot)
            pat = ""
            for ch in token:
                if ch == '?':
                    pat += '.'          # exactement un caractère
                elif ch == '*':
                    pat += '.*'         # zéro ou plusieurs caractères
                else:
                    pat += re.escape(ch)
            patterns.append(pat)
        else:
            # Terme libre : délimiteurs de mot pour éviter les correspondances partielles
            patterns.append(r'\b' + re.escape(token) + r'\b')
    return patterns


def highlight_terms(text: str, query: str) -> str:
    """Échappe le texte pour Rich et surligne les termes de la requête."""
    escaped_only = text.replace("[", "\\[")
    if not query or not text:
        return escaped_only

    patterns = parse_query_terms(query)
    # Les expressions les plus longues en premier pour éviter les chevauchements
    patterns.sort(key=len, reverse=True)
    if not patterns:
        return escaped_only

    combined = re.compile(
        "|".join(f"(?:{p})" for p in patterns), re.IGNORECASE
    )

    result = []
    last_end = 0
    for match in combined.finditer(text):
        start, end = match.start(), match.end()
        result.append(text[last_end:start].replace("[", "\\["))
        matched = match.group().replace("[", "\\[")
        result.append(f"[black on yellow]{matched}[/black on yellow]")
        last_end = end
    result.append(text[last_end:].replace("[", "\\["))
    return "".join(result)


# ---------------------------------------------------------------------------
# Appels API
# ---------------------------------------------------------------------------

def _has_explicit_operators(query: str) -> bool:
    """Détecte la présence d'opérateurs ArianeWeb (ET, OU, SAUF) ou de guillemets."""
    tokens = query.upper().split()
    if any(t in _OPERATORS for t in tokens):
        return True
    return '"' in query or '«' in query or '\u00ab' in query


def fetch_page(source_code: str, query: str, offset: int) -> dict:
    # Quand la requête contient des opérateurs ou des guillemets, on désactive
    # le mode "smart" afin que le moteur Sinequa respecte la syntaxe explicite.
    scmode = "boolean" if _has_explicit_operators(query) else "smart"
    params = urllib.parse.urlencode({
        "advanced":   "1",
        "type":       "json",
        "SourceStr4": source_code,
        "text.add":   query,
        "synonyms":   "true",
        "scmode":     scmode,
        "SkipCount":  PAGE_SIZE,
        "SkipFrom":   offset,
        "sort":       "SourceDateTime1.desc,SourceStr5.desc",
    }).encode()
    req = urllib.request.Request(SEARCH_URL, data=params,
                                 headers=SEARCH_HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_document_text(sinequa_id: str) -> str:
    document_id = sinequa_id.replace("/Ariane_Web/", "")
    body = json.dumps({"documentId": document_id, "matchLocations": ""}).encode()
    req = urllib.request.Request(CONTENT_URL, data=body,
                                 headers=CONTENT_HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        return html_to_text(html)
    except Exception as exc:
        return f"[Erreur : {exc}]"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_date(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return raw[:10]


def build_url(doc: dict) -> str | None:
    prefix     = doc.get("SourceStr39", "")
    number     = doc.get("SourceStr5", "")
    raw_date   = doc.get("SourceDateTime1", "")
    date_seg   = raw_date[:10] if raw_date else ""
    if prefix and number and date_seg:
        return f"{ARIANE_BASE}{prefix}{date_seg}/{number}"
    return None


def sort_key(d: dict) -> str:
    date = d.get("date") or "01/01/0001"
    try:
        day, month, year = date.split("/")
        return f"{year}-{month}-{day}"
    except ValueError:
        return "0001-01-01"


# ---------------------------------------------------------------------------
# Écran de visualisation d'une décision
# ---------------------------------------------------------------------------

# Niveaux de zoom : valeur = padding horizontal appliqué au conteneur de texte.
# Plus le padding est grand, plus la colonne est étroite → effet « agrandissement ».
_ZOOM_PADDINGS = [0, 4, 10, 18, 28, 40]
_DEFAULT_ZOOM  = 1  # index par défaut (padding = 4)


class DecisionScreen(ModalScreen):
    """Affiche le texte intégral d'une décision."""

    BINDINGS = [
        Binding("escape", "dismiss",     "Fermer"),
        Binding("q",      "dismiss",     "Fermer"),
        Binding("+",      "zoom_in",     "Agrandir"),
        Binding("=",      "zoom_in",     "Agrandir",    show=False),
        Binding("-",      "zoom_out",    "Réduire"),
        Binding("0",      "zoom_reset",  "Zoom normal", show=False),
    ]

    def __init__(self, decision: dict, query: str = "") -> None:
        super().__init__()
        self.decision     = decision
        self.search_query = query
        self._zoom        = _DEFAULT_ZOOM

    def compose(self) -> ComposeResult:
        d   = self.decision
        typ = d.get("type", "")
        num = d.get("numero", "")
        dat = d.get("date", "")
        jur = d.get("juridiction") or ""
        url = d.get("url") or ""
        texte = d.get("texte") or ""
        can_download = bool(d.get("_sinequa_id")) and not texte

        color = "cyan" if typ == "CE" else "magenta"
        titre = f"[{color}][bold]{typ}[/bold][/{color}]  {num}  [dim]{dat}[/dim]"
        if jur:
            titre += f"  — {jur}"

        with Vertical(id="decision-dialog"):
            yield Static(titre, id="decision-header")
            if url:
                yield Static(url, id="decision-url")
            with ScrollableContainer(id="decision-scroll"):
                if texte:
                    yield Static(highlight_terms(texte, self.search_query), id="decision-text")
                elif can_download:
                    yield Static(
                        "[dim]Texte non encore chargé — cliquez sur le bouton ci-dessous.[/dim]",
                        id="decision-text",
                    )
                else:
                    yield Static(
                        "[dim]Texte non disponible (recherche en métadonnées seulement).[/dim]",
                        id="decision-text",
                    )
            if can_download:
                with Horizontal(id="download-bar"):
                    yield Button("⬇  Télécharger le texte", variant="primary", id="download-btn")
            yield Static(id="decision-footer")

    def on_mount(self) -> None:
        self._apply_zoom()

    # ── Téléchargement à la demande ───────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "download-btn":
            event.button.disabled = True
            event.button.label = "Chargement…"
            self._fetch_text()

    @work(thread=True)
    def _fetch_text(self) -> None:
        sid = self.decision.get("_sinequa_id")
        if not sid:
            return
        texte = fetch_document_text(sid)

        if texte.startswith("[Erreur :"):
            # Échec : on conserve _sinequa_id pour permettre une nouvelle tentative
            safe_err = texte.replace("[", "\\[")
            def _show_error() -> None:
                self.query_one("#decision-text", Static).update(
                    f"[red]{safe_err}[/red]"
                )
                btn = self.query_one("#download-btn", Button)
                btn.disabled = False
                btn.label = "↻  Réessayer"
            self.app.call_from_thread(_show_error)
            return

        self.decision["texte"] = texte
        self.decision.pop("_sinequa_id", None)

        def _update() -> None:
            self.query_one("#decision-text", Static).update(
                highlight_terms(texte, self.search_query)
            )
            try:
                self.query_one("#download-bar").remove()
            except Exception:
                pass

        self.app.call_from_thread(_update)

    # ── Actions zoom ─────────────────────────────────────────────────────────

    def action_zoom_in(self) -> None:
        if self._zoom < len(_ZOOM_PADDINGS) - 1:
            self._zoom += 1
            self._apply_zoom()

    def action_zoom_out(self) -> None:
        if self._zoom > 0:
            self._zoom -= 1
            self._apply_zoom()

    def action_zoom_reset(self) -> None:
        self._zoom = _DEFAULT_ZOOM
        self._apply_zoom()

    def _apply_zoom(self) -> None:
        padding = _ZOOM_PADDINGS[self._zoom]
        self.query_one("#decision-scroll").styles.padding = (1, padding)
        level   = self._zoom - _DEFAULT_ZOOM
        sign    = ("+" if level > 0 else "") if level != 0 else "±"
        zoom_lbl = f"zoom {sign}{level}"
        self.query_one("#decision-footer", Static).update(
            f"[dim]Échap · Q  fermer  —  ↑ ↓ Page↑ Page↓  défiler  —  "
            f"+ agrandir  - réduire  0 normal[/dim]  [bold]{zoom_lbl}[/bold]"
        )


# ---------------------------------------------------------------------------
# Écran de confirmation
# ---------------------------------------------------------------------------

class ConfirmScreen(ModalScreen):
    """Demande confirmation avant la récupération des textes intégraux."""

    BINDINGS = [
        Binding("escape", "cancel",       "Annuler"),
        Binding("left",   "focus_prev",   "", show=False),
        Binding("right",  "focus_next_btn", "", show=False),
    ]

    def __init__(self, total: int) -> None:
        super().__init__()
        self.total = total

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(f"[bold]{self.total}[/bold] décision(s) trouvée(s).", id="confirm-msg")
            yield Label(
                "Lancer la récupération des textes intégraux ?",
                id="confirm-sub",
            )
            with Horizontal(id="confirm-buttons"):
                yield Button("Continuer", variant="success", id="confirm-yes")
                yield Button("Annuler",   variant="error",   id="confirm-no")

    def on_mount(self) -> None:
        # Focus initial sur "Continuer" pour que Enter l'active directement
        self.query_one("#confirm-yes", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")

    def action_focus_prev(self) -> None:
        self.focus_previous()

    def action_focus_next_btn(self) -> None:
        self.focus_next()

    def action_cancel(self) -> None:
        self.dismiss(False)


CSS = """
#content {
    height: 1fr;
}

/* ── Modal de visualisation ─────────────────────────────────────── */

DecisionScreen {
    align: center middle;
}

#decision-dialog {
    background: $surface;
    border: thick $accent;
    width: 90%;
    height: 90%;
}

#decision-header {
    background: $panel;
    padding: 0 2;
    height: 1;
    text-style: bold;
}

#decision-url {
    background: $panel;
    color: $text-muted;
    padding: 0 2;
    height: 1;
}

#decision-scroll {
    height: 1fr;
    padding: 1 2;
}

#decision-text {
    width: 100%;
}

#decision-footer {
    background: $panel;
    color: $text-muted;
    padding: 0 2;
    height: 1;
}

#download-bar {
    align: center middle;
    height: 5;
}

#download-btn {
    width: 34;
}

/* ── Modal de confirmation ──────────────────────────────────────── */

ConfirmScreen {
    align: center middle;
}

#confirm-dialog {
    background: $surface;
    border: thick $accent;
    padding: 2 4;
    width: 62;
    height: auto;
}

#confirm-msg {
    text-align: center;
    text-style: bold;
    color: $accent;
    margin-bottom: 1;
}

#confirm-sub {
    text-align: center;
    color: $text;
    margin-bottom: 2;
}

#confirm-buttons {
    align: center middle;
    height: auto;
}

#confirm-buttons Button {
    margin: 0 2;
}

/* ── Barre de recherche ─────────────────────────────────────────── */

#search-bar {
    height: auto;
    padding: 1 2;
    background: $panel;
    border-bottom: solid $border;
}

#query-input {
    width: 1fr;
    margin-right: 1;
    background: $surface;
    border: tall $border;
}

#query-input:focus {
    border: tall $accent;
}

#search-btn {
    width: 18;
    text-style: bold;
}

#search-btn:disabled {
    background: $surface;
    color: $text-muted;
}

#no-text-cb {
    margin-left: 2;
    background: $panel;
    border: none;
    padding-top: 1;
}

/* ── Résultats ──────────────────────────────────────────────────── */

#results-panel {
    height: 1fr;
    border: tall $border;
    margin: 0 1;
}

#results-title {
    background: $panel;
    color: $accent;
    padding: 0 1;
    height: 1;
    text-style: bold;
}

DataTable {
    height: 1fr;
    background: $surface;
}

DataTable > .datatable--header {
    background: $panel;
    color: $accent;
    text-style: bold;
}

DataTable > .datatable--cursor {
    background: $primary;
    color: $text;
}

DataTable > .datatable--hover {
    background: $surface-lighten-1;
}

/* ── Journal ────────────────────────────────────────────────────── */

#log-panel {
    height: 13;
    border: tall $border;
    margin: 0 1;
}

#log-title {
    background: $panel;
    color: $accent;
    padding: 0 1;
    height: 1;
    text-style: bold;
}

RichLog {
    height: 1fr;
    background: $surface;
}

/* ── Barre de statut ────────────────────────────────────────────── */

#status-bar {
    height: 1;
    background: $panel;
    color: $text-muted;
    padding: 0 2;
}
"""


class ArianeWebTUI(App):
    """Interface TUI pour ArianeWeb — jurisprudences CE et CAA."""

    CSS = CSS

    BINDINGS = [
        Binding("ctrl+s", "export_json",   "Exporter JSON"),
        Binding("escape", "cancel_search", "Annuler"),
        Binding("f5",     "start_search",  "Rechercher"),
        Binding("/",      "focus_search",  "Recherche",   show=False),
        Binding("q",      "quit",          "Quitter"),
    ]

    def __init__(self, initial_query: str = ""):
        super().__init__()
        self.initial_query  = initial_query
        self.all_decisions: list[dict] = []
        self._searching     = False
        self._cancel        = False
        self._confirm_event:  threading.Event | None = None
        self._confirm_result: bool = False

    # ── Composition de l'interface ───────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="content"):
            # Barre de recherche
            with Horizontal(id="search-bar"):
                yield Input(
                    value=self.initial_query,
                    placeholder="Requête (ex: 89-271, urbanisme…)",
                    id="query-input",
                )
                yield Button("Rechercher", variant="success", id="search-btn")
                yield Checkbox("Métadonnées seulement", id="no-text-cb")

            # Tableau de résultats
            with Vertical(id="results-panel"):
                yield Static("▸ Résultats", id="results-title")
                yield DataTable(id="results-table", cursor_type="row", zebra_stripes=True)

            # Journal de progression
            with Vertical(id="log-panel"):
                yield Static("▸ Journal", id="log-title")
                yield RichLog(id="log", highlight=True, markup=True)

            yield Static("", id="status-bar")

        yield Footer()

    # ── Initialisation ───────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._main_thread_id = threading.get_ident()

        table = self.query_one("#results-table", DataTable)
        table.add_columns("Type", "Numéro", "Date", "Juridiction", "URL")

        log = self.query_one("#log", RichLog)
        log.write(
            "[bold cyan]ArianeWeb TUI[/bold cyan] — "
            "Entrez une requête puis appuyez sur [bold]Rechercher[/bold] ou [bold]F5[/bold].\n"
            "[dim]Entrée sur une ligne pour lire le texte • Ctrl+S pour exporter • Échap pour annuler • Q pour quitter[/dim]"
        )

        self.query_one("#query-input", Input).focus()

        if self.initial_query:
            self.call_after_refresh(self._run_search)

    # ── Événements ───────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "search-btn":
            self._run_search()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "query-input":
            self._run_search()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        try:
            idx = int(event.row_key.value)
            decision = self.all_decisions[idx]
        except (ValueError, IndexError, TypeError):
            return
        query = self.query_one("#query-input", Input).value.strip()
        self.push_screen(DecisionScreen(decision, query=query))

    # ── Actions ──────────────────────────────────────────────────────────

    def action_start_search(self) -> None:
        self._run_search()

    def action_focus_search(self) -> None:
        self.query_one("#query-input", Input).focus()

    def action_cancel_search(self) -> None:
        if self._searching:
            self._cancel = True
            self._log("[yellow]⚠ Annulation demandée…[/yellow]")

    def action_export_json(self) -> None:
        if not self.all_decisions:
            self._log("[yellow]Aucune décision à exporter.[/yellow]")
            return
        query    = self.query_one("#query-input", Input).value.strip()
        # Exclure les clés internes (préfixe _) de l'export
        clean_decisions = [
            {k: v for k, v in d.items() if not k.startswith("_")}
            for d in self.all_decisions
        ]
        output   = {
            "requete":         query,
            "date_extraction": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total":           len(clean_decisions),
            "decisions":       clean_decisions,
        }
        # Nettoyer le nom de fichier (guillemets, espaces, slashs…)
        safe_query = re.sub(r'[^\w\-]', '_', query)
        safe_query = re.sub(r'_+', '_', safe_query).strip('_') or "export"
        out_file = f"resultats_{safe_query}.json"
        try:
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
            self._log(f"[bold green]✓ Exporté → {out_file}[/bold green]")
            self._set_status(f"Fichier créé : {out_file}")
        except OSError as exc:
            self._log(f"[red]✗ Impossible d'écrire {out_file} : {exc}[/red]")

    # ── Logique interne ──────────────────────────────────────────────────

    def _run_search(self) -> None:
        if self._searching:
            return
        query = self.query_one("#query-input", Input).value.strip()
        if not query:
            self._log("[red]Veuillez saisir une requête.[/red]")
            return

        # Réinitialisation
        self._searching = True
        self._cancel    = False
        self.all_decisions = []

        table = self.query_one("#results-table", DataTable)
        table.clear()
        self.query_one("#results-title", Static).update("▸ Résultats")

        btn = self.query_one("#search-btn", Button)
        btn.disabled = True
        btn.label    = "Recherche…"

        no_text = self.query_one("#no-text-cb", Checkbox).value
        self._set_status(f"Recherche en cours : « {query} »")
        self._search_worker(query, no_text)

    @work(thread=True, exclusive=True)
    def _search_worker(self, query: str, no_text: bool) -> None:

        self._log(f"\n[bold]━━ Recherche : «[/bold] [cyan]{query}[/cyan] [bold]»━━[/bold]")
        if no_text:
            self._log("[dim]Mode : métadonnées seulement[/dim]")
        else:
            self._log("[dim]Mode : textes intégraux (cocher « Métadonnées seulement » pour désactiver)[/dim]")

        all_decisions: list[dict] = []

        # 1. Collecte des métadonnées
        for source_code, label in SOURCES:
            if self._cancel:
                break
            try:
                raw_docs = self._collect_all(source_code, label, query)
                for doc in raw_docs:
                    all_decisions.append({
                        "_sinequa_id": doc.get("Id"),
                        "type":        label,
                        "juridiction": doc.get("SourceStr3"),
                        "numero":      doc.get("SourceStr5"),
                        "date":        parse_date(doc.get("SourceDateTime1")),
                        "url":         build_url(doc),
                        "texte":       None,
                    })
            except Exception as exc:
                self._log(f"[red]✗ Erreur [{label}] : {exc}[/red]")

        all_decisions.sort(key=sort_key, reverse=True)

        # 2. Confirmation avant la récupération des textes intégraux
        if not no_text and not self._cancel and all_decisions:
            total = len(all_decisions)
            if not self._wait_for_confirm(total):
                # L'utilisateur a annulé : on conserve les métadonnées
                self._cancel = True

        # 3. Récupération des textes intégraux
        if not no_text and not self._cancel:
            total = len(all_decisions)
            self._log(f"\n[bold]Récupération des textes ({total} décisions)…[/bold]")
            for i, decision in enumerate(all_decisions, 1):
                if self._cancel:
                    break
                sid = decision.pop("_sinequa_id", None)
                if sid:
                    decision["texte"] = fetch_document_text(sid)
                    n = len(decision["texte"] or "")
                    self._log(
                        f"  [dim]{i:>3}/{total}[/dim] "
                        f"[cyan]{decision['type']}[/cyan] "
                        f"[white]{decision['numero']}[/white] "
                        f"[dim]({decision['date']})[/dim] "
                        f"[green]✓ {n} car.[/green]"
                    )
                    if i < total:
                        time.sleep(REQUEST_DELAY)
                else:
                    decision.pop("_sinequa_id", None)
        else:
            for d in all_decisions:
                # _sinequa_id conservé : permet le téléchargement à la demande
                # depuis le visualisateur si l'utilisateur le souhaite.
                if "texte" in d:
                    del d["texte"]

        # 4. Affichage dans le tableau
        table = self.query_one("#results-table", DataTable)
        for i, d in enumerate(all_decisions):
            url = d.get("url") or ""
            self.call_from_thread(
                table.add_row,
                f"[{'cyan' if d.get('type') == 'CE' else 'magenta'}]{d.get('type', '')}[/]",
                d.get("numero", ""),
                d.get("date", ""),
                (d.get("juridiction") or "")[:40],
                url,
                key=str(i),
            )

        self.all_decisions = all_decisions
        self._searching    = False

        n = len(all_decisions)
        cancelled = " (annulée)" if self._cancel else ""
        self._log(
            f"\n[bold green]✓ {n} décision(s) trouvée(s){cancelled}.[/bold green] "
            "[dim]Ctrl+S pour exporter.[/dim]"
        )
        self._set_status(f"{n} décision(s) — Ctrl+S pour exporter en JSON")

        # Réactivation du bouton + titre + focus sur le tableau si des résultats existent
        def _enable_btn() -> None:
            btn = self.query_one("#search-btn", Button)
            btn.disabled = False
            btn.label = "Rechercher"
            n_res = len(all_decisions)
            self.query_one("#results-title", Static).update(
                f"▸ Résultats ({n_res})" if n_res else "▸ Résultats"
            )
            if all_decisions:
                self.query_one("#results-table", DataTable).focus()

        self.call_from_thread(_enable_btn)

    def _wait_for_confirm(self, total: int) -> bool:
        """Bloque le thread worker jusqu'à ce que l'utilisateur confirme ou annule."""
        event = threading.Event()
        self._confirm_event  = event
        self._confirm_result = False
        self.call_from_thread(self._push_confirm_screen, total)
        event.wait()
        return self._confirm_result

    def _push_confirm_screen(self, total: int) -> None:
        """Pousse le modal de confirmation depuis le thread principal."""
        def on_dismiss(result: bool) -> None:
            self._confirm_result = result
            if self._confirm_event:
                self._confirm_event.set()
        self.push_screen(ConfirmScreen(total), callback=on_dismiss)

    def _collect_all(self, source_code: str, label: str, query: str) -> list[dict]:
        results, offset = [], 0
        page  = fetch_page(source_code, query, offset)
        total = page.get("TotalCount", 0)
        self._log(f"  [{label}] [bold]{total}[/bold] résultat(s)")

        results.extend(page.get("Documents", []))

        while len(results) < total and not self._cancel:
            offset += PAGE_SIZE
            page = fetch_page(source_code, query, offset)
            docs = page.get("Documents", [])
            if not docs:
                break
            results.extend(docs)
            self._log(f"  [{label}] {len(results)}/{total} récupérés…")

        return results

    # ── Utilitaires thread-safe ───────────────────────────────────────────
    # Ces helpers détectent le thread courant : si on est sur le thread
    # principal de l'app, on appelle directement ; sinon on passe par
    # call_from_thread (seule façon valide depuis un worker thread).

    def _log(self, msg: str) -> None:
        log = self.query_one("#log", RichLog)
        if threading.get_ident() == self._main_thread_id:
            log.write(msg)
        else:
            self.call_from_thread(log.write, msg)

    def _set_status(self, msg: str) -> None:
        bar = self.query_one("#status-bar", Static)
        if threading.get_ident() == self._main_thread_id:
            bar.update(f" {msg}")
        else:
            self.call_from_thread(bar.update, f" {msg}")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    initial_query = sys.argv[1] if len(sys.argv) > 1 else ""
    ArianeWebTUI(initial_query=initial_query).run()
