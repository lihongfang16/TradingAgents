# cli/ — Command Line Interface

## OVERVIEW

Typer+Rich CLI application providing interactive terminal UI for running TradingAgents analysis. Registered as `tradingagents` console script via `pyproject.toml`.

## STRUCTURE

```
cli/
├── main.py            # Typer app (1537 lines), analyze command, MessageBuffer state mgmt
├── models.py          # AnalystType enum
├── config.py          # CLI config handling
├── utils.py           # Rich formatting, display utilities (358 lines)
├── announcements.py   # Remote announcement fetcher
├── stats_handler.py   # Statistics tracking
└── static/            # ASCII art welcome banner
```

## KEY PATTERNS

- `MessageBuffer` class manages streaming state — accumulates chunks from `graph.graph.stream()` and updates Rich Live display
- `AnalystType` enum defines selectable analysts (market, social, news, fundamentals)
- Rich Live display shows real-time agent progress as analysis runs
- `stats_handler.py` tracks usage statistics

## ENTRY POINTS

```python
# pyproject.toml [project.scripts]
tradingagents = "cli.main:app"     # Installed command
python -m cli.main                  # Direct from source
```

## NOTES

- `main.py` is the largest file in the project (1537 lines) — consider refactoring
- CLI shares `AnalysisRunner` with webapi but manages its own display/output
- `static/` contains ASCII art used in welcome screen
