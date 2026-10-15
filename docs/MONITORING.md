# Realtime Monitoring Documentation

> Signals are rule-based triggers for **human review**, never recommendations.
> A BUY signal means the symbol matches your configured setup, not that the
> price will rise. Always review manually (e.g. in DEGIRO) before acting.

## Stock Lists

Lists are persistent (PostgreSQL/SQLite via `WatchlistItems`) and scoped
per user. The `default` list keeps backward compatibility with the legacy
`/watchlist` routes.

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/watchlists?user_id=` | All lists with counts |
| `POST /api/v1/watchlists?name=&user_id=` | Create list (idempotent) |
| `GET /api/v1/watchlists/{name}?user_id=` | Symbols in a list |
| `POST /api/v1/watchlists/{name}/symbols?symbol=&user_id=` | Add symbol |
| `DELETE /api/v1/watchlists/{name}/symbols/{symbol}?user_id=` | Remove symbol |
| `DELETE /api/v1/watchlists/{name}?user_id=` | Delete list (not `default`) |

Example:

```bash
curl -X POST "http://localhost:8000/api/v1/watchlists/biotech/symbols?symbol=ABCD"
curl "http://localhost:8000/api/v1/watchlists/biotech"
```

## Signal Rules (`app/signals`)

BUY requires **all** of (configurable in `config/settings.yaml` → `monitor:`):

- `score >= buy_min_score` (default 70)
- `RVOL >= buy_min_rvol` (default 2.0x)
- `spread <= buy_max_spread_pct` when known
- above VWAP when intraday data exists (otherwise the check is skipped
  and reported honestly as `VWAP n/d`)
- no blocking flag (`TRADING_HALT`, `RECENT_OFFERING`, `ACTIVE_ATM`,
  `DELISTING_WARNING`, `GOING_CONCERN`)
- data not stale

SELL triggers on **any** of:

- a new blocking flag appears
- score drops by `>= sell_score_drop` (default 15) since last evaluation
- price loses VWAP by `>= sell_vwap_break_pct` after being above it

Every event carries `reasons[]` so it is fully explainable.

## Divergences (RSI/MACD/Stochastic)

The monitor also detects classic divergences (fractal pivots, last 60 bars):

- **Bearish**: price makes a higher pivot high while RSI (or MACD
  histogram, or stochastic %D) makes a lower high → -20 to the
  technical score (RSI) plus a warning reason.
- **Bullish**: price makes a lower pivot low while the oscillator makes
  a higher low → +10 to the technical score (RSI) plus confirmation reason.
- **Stochastic crosses**: %K crossing above %D is bullish (+5 technical),
  below is bearish (-10 technical), with reasons attached.

A divergence or cross alone never fires a BUY/SELL; it only tilts the
technical score and leaves a trace in the event reasons.

## Monitor Loop (`app/jobs/monitor.py`)

Each round, per symbol (concurrently, semaphore-limited):

1. Fetch quote + daily bars from the configured provider.
2. Compute change %, daily RVOL, spread, momentum/technical/liquidity
   partial scores → deterministic `ScoringEngine` score.
3. Assess risk flags (`RiskEngine`); stale data blocks signals.
4. Evaluate BUY/SELL rules against previous state.
5. Deliver actionable signals via `AlertEngine` (cooldown + dedup per
   `symbol:action`) to console/Telegram/Discord/email/webhook.
6. One symbol failing never kills the round.

Run it:

```bash
# Single pass over a list
python -m app monitor --list biotech --once
# Realtime loop (reloads the list every round, picks up edits live)
python -m app monitor --list biotech
# Offline demo with mock data
python -m app monitor --list biotech --once --mock
```

API:

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/monitor/status` | Loop state + last run stats |
| `GET /api/v1/monitor/events?limit=` | Recent signal events |
| `POST /api/v1/monitor/run?list_name=&user_id=` | One pass over a list |
| `GET /api/v1/monitor/config` | Current thresholds |

## Round Gates (`run_once`, en vivo desde 2026-09-21)

Cada ronda, tras evaluar símbolos individualmente:

1. **Régimen** (`app/signals/regime.py::classify_regime`): breadth % sobre
   VWAP + mediana de cambio + halts del día → `RISK_ON` / `CHOP` /
   `RISK_OFF` / `HALT_STORM`. En `CHOP`/`RISK_OFF` el BUY exige
   score ≥ 80 y RVOL ≥ 4.0; en `HALT_STORM` cero compras nuevas (solo
   exits). Los BUY degradados pasan a HOLD con motivo explícito.
   Config: `monitor.regime_enabled`, `monitor.halt_storm_threshold`.
2. **Correlación** (`correlation_filter`): series de retornos 5m reales por
   símbolo; ante |ρ| > `monitor.max_corr` entre dos candidatos BUY se
   queda el de mayor score y el otro pasa a HOLD anotado. Sin serie 5m
   el candidato se conserva (beneficio de la duda).
3. **Circuitos** (`app/risk/circuit.py::CircuitBreaker`, config `circuit:`):
   veto 24h por símbolo tras −8% o halt sufrido; kill switch de portfolio
   (mediana de la ronda ≤ −5% o ≥3 halts) que degrada todos los BUY a
   HOLD solo-lectura. `GET /monitor/status` expone `regime`,
   `regime_thresholds`, `corr_dropped`, `kill_switch`, `vetoed_symbols`
   y últimos `circuit_events`. Los SELL (salidas) nunca son bloqueados
   por estos gates.
4. **Kill switch crítico**: en la transición a portfolio-killed (no cada
   ronda) el monitor llama `AlertEngine.send_critical`, que emite por
   todos los providers configurados saltando cooldown/dedup — es la vía
   prioritaria a Telegram. Los trips se persisten en `circuit_events` y
   se sirven en `GET /monitor/circuits`.

## Paper portfolio (sin órdenes, sin broker)

`app/risk/paper.py::PaperTracker` replica las señales finales: BUY abre
(una posición por símbolo, sin piramidar; cantidad de la plantilla o
nocional 2000$), SELL cierra todo, cada ronda actualiza MtM. Costes
all-in vía `apply_costs` con el spread medido. Los circuitos usan PnL
   real cuando hay historial paper (posición para el veto por símbolo,
   `daily_pnl_pct` ET para el kill switch); en vacío conservan el proxy de
   la ronda. Visible en `GET /monitor/status` → `paper{equity, positions,
   daily_pnl_pct, ...}` y como motivos `paper: abre/cierra …` en eventos.
   Cada cierre se persiste en `paper_trades` (migración incluida) y se
   sirve en `GET /monitor/paper/trades`; el resumen vivo está en
   `GET /monitor/paper`. Las abiertas viven en `paper_positions`
   (upsert al abrir, borrado al cerrar, carga perezosa una vez por
   servicio): un reinicio ya no las pierde.

## Snapshots históricos (dataset de calibración)

Cada ronda persiste una fila por símbolo en `monitor_snapshots`
(action, score, price, change, rvol, vwap_distance, risk_flags, régimen
y `config_hash`) más un resumen en `scanner_runs`. Solo features
evaluadas — nunca retornos futuros, para no filtrar targets al vivo.
Servido en `GET /monitor/snapshots?symbol=&limit=`. El `config_hash`
(`app.config.config_fingerprint` sobre monitor/scoring/circuit/gates/
risk/sizing/backtesting) conserva el significado histórico cuando los
pesos cambian (§64).

## Protecciones NASDAQ/NYSE (ver `docs/NASDAQ_NYSE_ADAPTATION.md`)

- **HaltGuardian** (`app/risk/halt.py`): congela señales en halt LULD y
  durante 60s post-reanudación; penaliza score −50 mientras dure.
- **DilutionFreeze + DollarRule** (`app/risk/freeze.py`): S-1/S-3,
  424B2/5 u 8-K con ATM congelan compras 30 días; 90 cierres bajo $1
  avisan, 150 bloquean compras y exigen spread ≤2%.
- **Squeeze** (`app/signals/gates.py`): 3+ días parabólicos con volumen
  creciente anotan el evento (no hay lado corto: solo momentum-long).
- **Sizer + plantillas** (`app/risk/sizing.py`, `app/brokers/templates.py`):
  cada BUY lleva `order_template` LIMIT-only (ARCA/BATS/EDGX) con
  instrucción manual para DEGIRO; market orders rechazadas por construcción.
- **Circuit breakers** (`app/risk/circuit.py`): símbolo/estrategia/portfolio
  con kill switch; **Feeds** (`app/feeds`): SIP hoy, Direct futuro.
- **VWAP de sesión real**: calculado con las barras 5m del día
  (`session_vwap`); activa la exigencia de estar sobre VWAP en BUY y el
  SELL por perderlo (transiciones guardadas entre rondas).
- **Gate Donchian en vivo**: corre en el monitor cuando hay proveedor
  de noticias (IA, con fallback
  heurístico); usa **RVOL same-time real de barras 5m** cuando existen
  (proxy diario si no); régimen y correlación viven como librería testeada
  en `app/signals/` lista para la capa de estrategia.
- **Filings rápidos** (`app/jobs/filings.py`, job `sync_filings_fast`
  cada 5 min): cachea filings recientes por símbolo (TTL 5 min) y el
  monitor congela compras con motivos del filing real, no por proxy.
- **Sesiones ET** (`app/core/market_calendar.py`): RVOL same-time y VWAP
  agrupan por fecha `America/New_York`, sin cortes falsos a medianoche UTC.
- **Acumulación sigilosa** (`app/signals/accumulation.py`, en vivo):
  absorción (volumen sin progreso) + flujo monetario + divergencia
  OBV/precio + rotación de float + compresión de volatilidad → score
  0-100 y fase (umbral 60). El clímax (volumen 3x tras +30%) avisa de
  distribución: no perseguir. `markup_ready` detecta base + ruptura.

## Feed (SIP-first, latencia honesta)

El monitor consume market data a través de `FeedAdapter` (`app/feeds`):
`SipFeed` por defecto. Cada fetch mide su latencia; si supera
`feed.max_fetch_lag_ms` (default 1500ms) el símbolo se marca STALE y no
emite señales. `feed.kind=direct` exige `direct_entitlement` (TotalView/
OpenBook); sin ella hay fallback explícito a SIP con warning — ningún
path asume datos direct en silencio. Estado visible en
`GET /monitor/status` → `feed{kind,last_lag_ms,warning}` y por símbolo
en `details{feed_kind,feed_lag_ms}`.

## Tuning

Start with defaults, then adjust `monitor:` in `config/settings.yaml`:

```yaml
monitor:
  interval_seconds: 60
  buy_min_score: 70
  buy_min_rvol: 2.0
  sell_score_drop: 15
```

Validate changes with the backtest module before trusting new thresholds.
