# Backend Restructure Plan: Layered Architecture

## Target Structure

```
src/interviewer/
├── app.py                          # FastAPI entry point
├── routes/                         # HTTP routes (no controllers layer)
│   ├── __init__.py
│   ├── v1/
│   │   ├── __init__.py             # Router aggregation
│   │   ├── candidate.py
│   │   ├── corpus.py
│   │   ├── notebooks.py
│   │   ├── operator.py
│   │   └── sessions.py
├── dto/                            # Pydantic DTOs (request/response models)
│   ├── __init__.py
│   ├── candidate.py
│   ├── corpus.py
│   ├── notebooks.py
│   ├── operator.py
│   └── sessions.py
├── exception/                      # Custom exceptions + handlers
│   ├── __init__.py
│   ├── handlers.py
│   └── definitions.py
├── model/                          # ORM table definitions (thin re-exports)
│   ├── __init__.py                 # re-exports from db/schema.py + db/content.py
├── repository/                     # Data access layer
│   ├── __init__.py
│   ├── base.py                     # Generic CRUD helpers
│   ├── notebooks.py                # from notebooks/store.py
│   ├── confidence.py               # from confidence/store.py
│   └── ledger.py                   # from metering/ledger.py
├── service/                        # Business logic
│   ├── __init__.py
│   ├── corpus.py                   # from corpus/service.py
│   ├── notebooks/                  # keep subpackage if too large
│   │   ├── __init__.py
│   │   ├── service.py
│   │   ├── progress.py
│   │   ├── reuse.py
│   │   ├── metering.py
│   │   ├── corpus_view.py
│   │   └── citations.py
│   ├── session_runner.py           # thin wrapper around graph/runner.py
│   ├── judge/                      # existing judge service package
│   ├── identity/                   # existing identity service package
│   ├── confidence/                 # existing confidence service package
│   └── session_service/            # existing session service package
├── config/                         # Configuration classes
│   ├── __init__.py
│   └── settings.py                 # from core/config.py
├── util/                           # Utility classes
│   ├── __init__.py
│   └── [file_handling, validations, etc.]
├── security/                       # Security-related files
│   ├── __init__.py
│   └── auth.py                     # from core/security.py
├── adapters/                       # Third-party API integrations
│   ├── __init__.py
│   ├── gatehouse_adpater.py        # Gatehouse API client
│   ├── interview_lm.py             # existing adapter (moved from corpus/adapters/)
│   └── [other third-party adapters]
├── core/                           # Core constants, wiring, deps (keep as-is)
│   ├── __init__.py
│   ├── constants.py
│   └── security.py                 # will be re-exported from security/
├── schemas/                        # Legacy/flat DTO re-exports (deprecated, migrate to dto/)
├── db/                             # Keep as-is (engine, DDL)
│   ├── engine.py
│   ├── schema.py
│   └── content.py
├── errors.py                       # Keep as-is (exception definitions)
├── schema.py                       # Keep as-is (CustomBaseModel)
├── idempotency.py                  # Keep as-is
├── ingest_worker.py                # Keep as-is
├── wiring.py                       # Keep as-is (composition root)
├── deps.py                         # Keep as-is (process singletons)
├── graph/                          # Keep as-is (LangGraph machine)
├── judge/                          # Keep as-is
├── confidence/                     # Keep as-is (minus store.py → repository/)
├── metering/                       # Keep as-is (minus ledger.py → repository/)
├── embeddings/                     # Keep as-is
├── identity/                       # Keep as-is
├── corpus/                         # Keep core logic, remove router + schemas + service
│   ├── adapters/                   # Keep internal adapters (markdown_folder)
│   ├── contract.py
│   ├── conformance.py
│   ├── loader.py
│   ├── cli.py
│   ├── related.py
│   ├── chunking.py
│   ├── digest.py
│   ├── citations.py
├── notebooks/                      # Keep domain logic, remove router + schemas
│   ├── store.py → repository/
│   ├── service.py
│   ├── progress.py → service/notebooks/
│   ├── reuse.py → service/notebooks/
│   ├── metering.py → service/notebooks/
│   ├── corpus_view.py → service/notebooks/
│   └── citations.py → service/notebooks/
├── sessions/                       # Remove entirely (router + schemas → routes/ + dto/)
├── candidate/                      # Remove entirely (router + schemas → routes/ + dto/)
├── operator/                       # Keep config.py + dependencies.py, remove router + schemas
├── mcp/                            # Keep as-is
└── repositories/                   # Already exists, expand with moved stores
    ├── notebooks.py                # from notebooks/store.py
    ├── confidence.py               # from confidence/store.py
    └── ledger.py                   # from metering/ledger.py
```

## Removed:
- `routers/` (flat package) → `routes/v1/`
- `api/app.py` → `app.py` at root
- `api/` compat shims (deps.py, auth.py, errors.py, idempotency.py, ingest_worker.py, wiring.py)
- `services/__init__.py` barrel → proper `service/` package
- `config.py` (top-level) → `config/settings.py`
- `sessions/` package → `routes/v1/sessions.py` + `dto/sessions.py`
- `candidate/` package → `routes/v1/candidate.py` + `dto/candidate.py`
- `corpus/router.py`, `corpus/schemas.py`, `corpus/service.py` → moved
- `notebooks/router.py`, `notebooks/schemas.py` → moved
- `operator/router.py`, `operator/schemas.py` → moved
- Scraping scripts `backend/scripts/scrape.mjs`, `ingest-transcripts.mjs`, `api-probe.mjs`, `recon.mjs`, `verify.mjs`, `login.mjs` → repo root

## Execution Order

1. Phase 0: Move scraping scripts to repo root ✓
2. Phase 1: Cleanup dead code (config.py, services/__init__.py, api/ shims)
3. Phase 2: Break compat shim + consolidate schemas → dto/
4. Phase 3: Consolidate routers → routes/v1/
5. Phase 4: Extract repository layer (move stores)
6. Phase 5: Extract service layer (move business logic)
7. Phase 6: Create adapters/, util/, exception/ folders
8. Phase 7: Update Dockerfile, README, imports across all files
9. Phase 8: Final verification with pytest

After each phase: run `pytest backend/tests -q` to verify.

## Files Changed Per Phase

### Phase 0: ~6 files moved (scripts) ✓
### Phase 1: ~3 files deleted
### Phase 2: ~25 files edited (imports updated)
### Phase 3: ~15 files (routers moved, app.py updated, domain routers deleted)
### Phase 4: ~20 files (stores moved to repository/, imports updated)
### Phase 5: ~10 files (services consolidated)
### Phase 6: ~5 new files created (adapters, util, exception)
### Phase 7: ~20 files (Dockerfile, README, imports)
### Phase 8: Verification

**Total: ~100 file operations across 9 phases**
