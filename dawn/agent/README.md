# DAWN Agent Service

Local HTTP service for generating patchsets from requirements.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run service
uvicorn service:app --host 127.0.0.1 --port 9411

# Test
curl http://127.0.0.1:9411/health
```

## Architecture

```
DAWN Pipeline → impl.generate_patchset (adapter) → Agent Service (this)
                                                        ↓
                                                  patchset.json
                                                  capabilities_manifest.json
```

## Endpoints

- `POST /v1/patchset:generate` - Generate patchset from requirements
- `GET /health` - Health check
- `GET /` - Service info

## Version

- **v0.1.0**: Rule-based generation (deterministic)
- **v0.2.0**: Ollama integration (planned)
