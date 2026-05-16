<p align="center">
<h1 align="center">codeloom</h1>
  <p align="center">
    "With codeloom, your coding agent knows what to read."
    <br />
    <a href="#schnellstart">Schnellstart</a> · <a href="../README.md">English</a> · <a href="README_ko.md">한국어</a> · <a href="README_ja.md">日本語</a> · <a href="README_zh.md">中文</a>
  </p>
</p>

<p align="center">
  <a href="https://github.com/algodesigner/codeloom/actions"><img src="https://img.shields.io/github/actions/workflow/status/algodesigner/codeloom/ci.yml?branch=main" alt="CI"></a>
  <a href="https://pypi.org/project/codeloom/"><img src="https://img.shields.io/pypi/v/codeloom" alt="PyPI"></a>
  <a href="https://github.com/algodesigner/codeloom/blob/main/LICENSE"><img src="https://img.shields.io/github/license/algodesigner/codeloom" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
</p>

---

## Warum codeloom?

> raw data from a given number of sources is collected, then compiled by an LLM into a .md wiki, then operated on by various CLIs by the LLM to do Q&A and to incrementally enhance the wiki - Andrej Karpathy

codeloom erstellt mit leichtgewichtigen lokalen LLM-Modellen einen abfragbaren Code Graph und eine Wissensdatenbank aus Codebasen mit 10.000+ Dateien und Wissensdokumenten. Hybride Vektor+Keyword-Suche mit Subgraph-Antwort (Vektor + Keyword → RRF-Fusion mit MST-Subgraph) ermoeglicht Coding-Agents, Ihr gesamtes Projekt wirklich zu verstehen. Installieren Sie es, und Claude Code sieht das Gesamtbild — keine zusaetzlichen Tokens, keine zusaetzlichen Befehle, alles laeuft 100% lokal.

## Schnellstart

```bash
pip install codeloom

cd your-project/
codeloom opencode install    # fuer OpenCode
# oder: codeloom claude install  # fuer Claude Code
```

Sagen Sie Claude Code oder OpenCode:

> "Baue einen Code Graph fuer dieses Projekt"

Das war's. Der Graph wird gebaut und ab sofort bei jeder Suche konsultiert. Der Graph wird automatisch neu gebaut, wenn Ihre Sitzung endet.

## AI-Agent-Integrationen

codeloom integriert sich mit einem Befehl in fuehrende AI Coding Agents:

| Agent | Installation | Beschreibung |
|-------|-------------|-------------|
| **Claude Code** | `codeloom claude install` | Skill + CLAUDE.md + PreToolUse-Hook |
| **OpenCode** | `codeloom opencode install` | Skill in `.opencode/skills/` |
| **Codex CLI** | `codeloom codex install` | AGENTS.md + PreToolUse-Hook |
| **Gemini CLI** | `codeloom gemini install` | GEMINI.md + BeforeTool-Hook |
| **Cursor IDE** | `codeloom cursor install` | `.cursor/rules/`-Regeldatei |
| **Windsurf IDE** | `codeloom windsurf install` | `.windsurf/rules/`-Regeldatei |
| **Cline** | `codeloom cline install` | `.clinerules`-Datei |
| **Aider CLI** | `codeloom aider install` | CONVENTIONS.md + `.aider.conf.yml` |
| **MCP-Server** | `claude mcp add codeloom -- codeloom mcp` | Model Context Protocol 5 Tools |

Jeder `install`-Befehl schreibt eine Kontextdatei und registriert (bei unterstuetzten Plattformen) einen Hook vor Tool-Aufrufen. Entfernen: `codeloom <platform> uninstall`.

## Unterstuetzte Sprachen

### Strukturextraktion (20+ Sprachen)

codeloom verwendet tree-sitter und native Parser zur Extraktion von Funktionen, Klassen, Methoden, Aufrufen, Imports und Vererbung.

| | | | |
|:---:|:---:|:---:|:---:|
| Python | JavaScript | TypeScript | Go |
| Rust | Java | C | C++ |
| C# | Ruby | Swift | Scala |
| Lua | PHP | Elixir | Kotlin |
| Objective-C | Terraform/HCL | | |

Konfigurations- und Dokumentformate werden ebenfalls strukturell extrahiert: YAML, JSON, TOML, Markdown, PDF, HTML, CSV, Shell, R und mehr.

### Mehrsprachige natuerliche Sprache

Textknoten (Dokumente, Kommentare, Markdown) werden mit `intfloat/multilingual-e5-small` eingebettet und unterstuetzen **100+ natuerliche Sprachen** — Deutsch, Koreanisch, Japanisch, Chinesisch, Franzoesisch und mehr. Suchen Sie in Ihrer Sprache, finden Sie Ergebnisse in jeder Sprache.

---

## Funktionen

### Automatischer Rebuild

Bei Integration mit KI-Coding-Agenten (Claude Code, Codex usw.) **baut codeloom den Graphen automatisch neu**, wenn sich Code aendert. Der Stop/SessionEnd-Hook erkennt geaenderte Dateien ueber `git diff` und fuehrt im Hintergrund einen inkrementellen Build durch — kein manuelles Eingreifen noetig.

### Intelligentes Ignore

Unterstuetzt Ignore-Muster aus drei Quellen, alle mit **vollstaendiger gitignore-Spezifikation** (Negation `!`, `**`-Globs, verzeichnisspezifische Muster):

| Quelle | Beschreibung |
|--------|-------------|
| Eingebaut | `.git`, `node_modules`, `__pycache__`, `dist`, `build` usw. |
| `.gitignore` | Automatisches Lesen aus dem Projektstamm — bestehende Git-Ignores funktionieren einfach |
| `.codeloom-ignore` | Projektspezifische Ueberschreibungen fuer den Code-Graphen |

### Inkrementelle Builds

SHA-256-Content-Hashing pro Datei. Nur geaenderte Dateien werden neu extrahiert und neu eingebettet. Unveraenderte Dateien werden aus dem bestehenden Graphen uebernommen — typischerweise **95%+ schneller** als ein vollstaendiger Build.

### Speicherverwaltung

4GB Speicherbudget mit stufenweiser Freigabe. Die Pipeline erzeugt → speichert → gibt frei in jeder Phase: Extraktionsergebnisse werden nach dem Graph-Aufbau freigegeben, Embeddings werden batchweise gestreamt und nach DB-Schreiben freigegeben, der gesamte Graph wird nach der Persistierung freigegeben. GC wird bei 75% Schwellenwert praeventiv ausgeloest.

### 100% Lokal

Keine Cloud-Dienste, keine API-Schluessel, keine Telemetrie. SQLite + FAISS fuer Speicherung, sentence-transformers fuer Embeddings. Alle Daten bleiben auf Ihrem Rechner.

---

## Hybridsuche mit Subgraph-Antwort

Alle Abfragen liefern Seed-Knoten und einen Subgraphen, der zeigt, wie diese verbunden sind:

**Such-Pipeline**

| Signal | Findet |
|--------|--------|
| **Vektorsuche** | Semantisch ähnlichen Code und Dokumente (Dual-Modell: Code + Text) |
| **Keyword-Suche** | Exakte Namenstrefffer via FTS5 (BM25) |

Ergebnisse werden per Weighted Reciprocal Rank Fusion (RRF) zusammengefuehrt und dann ueber MST-basierte kuerzeste Pfade verbunden, um die Beziehungen zwischen Seed-Knoten sichtbar zu machen.

**Antwortformat**
```
seeds:
codeloom/core/pipeline.py:71
codeloom/query/embeddings.py:70

edges:
codeloom/core/pipeline.py:71 -calls-> codeloom/core/extract.py:747
codeloom/core/pipeline.py:0 -co_change-> codeloom/query/embeddings.py:0
```

- `seeds`: Knoten-IDs (Datei:Zeile), gefunden durch die Suche
- `edges`: Subgraph, der Seed-Knoten ueber kuerzeste Pfade verbindet (Zwischenknoten erscheinen in den Kanten)

## CLI-Referenz

Alle Befehle geben standardmaessig kompakten Text aus (fuer AI-Agent-Nutzung konzipiert).

| Befehl | Beschreibung |
|--------|-------------|
| `build <dir>` | Code-Graph erstellen (`--incremental`) |
| `search <query>` | Hybridsuche Vektor+Keyword mit Subgraph (`--top-k`, `--fast`) |
| `search-vector <query>` | Nur Vektor-Aehnlichkeit (Code + Text Dual-Modell) |
| `search-keyword <query>` | Nur FTS5-Keyword-Matching (BM25-Ranking) |
| `query` | Interaktive Such-REPL |
| `communities` | Communities auflisten und durchsuchen (`--search`, `--level`) |
| `stats` | Graph-Statistiken |
| `node <id>` | Knotendetails mit Fuzzy-Matching |
| `export` | Export als JSON, GraphML oder D3.js |
| `visualize` | Interaktive HTML-Visualisierung |
| `clean` | .codeloom/-Datenbank entfernen |
| `doctor` | Installationsstatus pruefen |
| `mcp` | MCP-Server starten (stdio) |
| `claude install\|uninstall` | Claude Code Integration verwalten |
| `codex install\|uninstall` | Codex CLI Integration verwalten |
| `gemini install\|uninstall` | Gemini CLI Integration verwalten |
| `cursor install\|uninstall` | Cursor IDE Integration verwalten |
| `windsurf install\|uninstall` | Windsurf IDE Integration verwalten |
| `cline install\|uninstall` | Cline Integration verwalten |
| `aider install\|uninstall` | Aider CLI Integration verwalten |
| `opencode install\|uninstall` | OpenCode Integration verwalten |

## Leistung

Benchmarks auf der eigenen Codebasis von codeloom (~3.500 Zeilen, 90 Dateien, 1.300 Knoten):

| Operation | Zeit |
|-----------|------|
| Vollstaendiger Build | ~14s |
| Inkrementeller Build (Aenderungen) | ~4s |
| Inkrementeller Build (keine Aenderungen) | ~0,4s |
| Kaltstart-Suche (Dual-Modell) | ~2,8s |
| Kaltstart-Suche (`--fast`) | ~0,2s |
| Warme Suche | ~0,08s |
| Cache-Treffer | <1ms |

- **Einbettungsmodelle**: ~180MB, einmalig nach `~/.codeloom/models/` heruntergeladen
- **Datenbank**: ~2MB (SQLite + FTS5 + FAISS-Indizes)
- **Inkrementelle Builds**: SHA-256-Hashing, 95%+ schneller als vollstaendiger Build

## Anforderungen

- Python 3.10+
- Einbettungsmodelle ~180MB (beim ersten Gebrauch gecacht)

```bash
# Optional: PDF-Extraktion
pip install codeloom[docs]
```

## Entwicklung

```bash
pip install -e ".[dev]"
pytest
ruff check codeloom/
```

## Lizenz

MIT License. Siehe [LICENSE](../LICENSE).

## Mitwirken

Beitraege sind willkommen! Siehe [CONTRIBUTING.md](../CONTRIBUTING.md).
