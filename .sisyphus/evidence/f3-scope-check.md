# F3 Scope Fidelity Check

## Verdict: FAIL

## Compliance Table

| Area | Item | Status | Evidence |
|---|---|---:|---|
| Files Created | `webapi/services/change_detection.py` | ✓ | File exists in `webapi/services/` |
| Files Created | `webapi/services/diff_report.py` | ✓ | File exists in `webapi/services/` |
| Files Created | `webapi/services/incremental_analysis_service.py` | ✓ | File exists in `webapi/services/` |
| Files Created | Tests for all three services | ✓ | `tests/test_change_detection.py`, `tests/test_diff_report.py`, `tests/test_incremental_analysis_service.py` |
| Files Modified | `webapi/routers/watchlist.py` - only added endpoints | ✗ | Relative to base, file is entirely new and contains broad watchlist/router logic, not endpoint-only additions |
| Files Modified | `webapi/routers/analysis.py` - only added endpoint | ✗ | Relative to base, file is entirely new, not a minimal endpoint-only edit |
| Files Modified | `webapi/models/analysis.py` - only changed default | ✗ | Relative to base, file is entirely new and contains multiple new request/response models |
| Files Modified | `web/components/watchlist_manager.py` - UI changes only | ✗ | Relative to base, file is entirely new and contains substantial watchlist/business-flow logic |
| Upstream Isolation | NO modifications to `tradingagents/graph/` | ✗ | `tradingagents/graph/propagation.py`, `tradingagents/graph/trading_graph.py` changed vs base |
| Upstream Isolation | NO modifications to `tradingagents/agents/` | ✗ | Multiple files under `tradingagents/agents/` changed vs base |
| Upstream Isolation | NO modifications to `tradingagents/core/cached_analysis_runner.py` | ✓ | No diff reported for that file vs base |
| Upstream Isolation | NO new data sources introduced | ✗ | Provider files exist vs base: `akshare_provider.py`, `ashare_provider.py`, `baostock_provider.py`, `mairui_provider.py` |
| Functionality | Change detection uses thresholds correctly | ✓ | `change_detection.py` uses strict `>` for market threshold; targeted tests pass |
| Functionality | Diff report uses `difflib` (no LLM) | ✓ | `diff_report.py` imports/uses stdlib `difflib` only; tests pass |
| Functionality | Incremental uses `CachedAnalysisRunner` with cache invalidation | ✗ | Service invalidates cache and imports runner, but imports `webapi.services.change_detector` instead of implemented `change_detection.py`; runtime path/signature mismatch |
| Functionality | API endpoints return correct status codes | ✓ | `analysis.py` diff endpoint uses 404/400/500; `watchlist.py` incremental endpoint maps 409/400; tests cover 409/500 service paths |
| Functionality | UI buttons have correct states | ✓ | `watchlist_manager.py` computes `full_disabled`, `incr_disabled`, `diff_disabled` and wires button state accordingly |
| Must NOT Have | NO Redis/MongoDB usage | ✓ | No code usage found in searched Python files; note optional `redis` dependency remains in `requirements-web.txt` |
| Must NOT Have | NO per-stock threshold config | ✓ | No per-stock change-detection threshold feature found; only unrelated `confidence_jump_threshold` exists for turning detection |
| Must NOT Have | NO historical diff | ✓ | Diff flow compares latest two completed analyses only |
| Must NOT Have | NO LLM in diff generation | ✓ | `diff_report.py` contains no LLM calls/imports |

## Additional Verification

- Targeted tests: `pytest tests/test_change_detection.py tests/test_diff_report.py tests/test_incremental_analysis_service.py` -> **53 passed**.
- LSP diagnostics on changed files: **not clean**. Errors reported in:
  - `webapi/services/diff_report.py`
  - `webapi/services/incremental_analysis_service.py`
  - `webapi/routers/analysis.py`
  - `webapi/routers/watchlist.py`
  - `web/components/watchlist_manager.py`

## Deviations

1. **Scope drift outside planned files**: upstream core paths under `tradingagents/graph/` and `tradingagents/agents/` are modified.
2. **Router/model/UI files are not minimal edits**: several checklist items expected narrow modifications, but current branch introduces whole-file implementations.
3. **New data source/provider additions exist** relative to base branch, violating upstream isolation.
4. **Incremental analysis integration bug**: `IncrementalAnalysisService` imports `webapi.services.change_detector.ChangeDetector`, but the implemented file is `webapi/services/change_detection.py`; tests pass only because they inject a stub module.
5. **Verification gate not met**: changed files do not have clean LSP diagnostics.

## Final Verdict

**FAIL** — required services/tests exist and targeted tests pass, but the branch is not 1:1 scope-faithful to the stated plan and upstream isolation constraints.
