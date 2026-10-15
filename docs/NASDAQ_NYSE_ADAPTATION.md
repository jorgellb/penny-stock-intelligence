# Auditoría y Adaptación NASDAQ/NYSE — Penny Stocks (<$5, sin OTC)

> Alcance: acciones oficiales NASDAQ/NYSE < $5. OTC excluido por completo.
> Enfoque: Simons (reversión/estadística), Connors (reversión corto plazo),
> Donchian (ruptura de canal). Este proyecto NO ejecuta órdenes
> (DEGIRO = ejecución manual); la capa de ejecución se diseña como
> "manual-asistida" + `BrokerAdapter` listo para un broker DMA futuro.

## 0. Veredicto de auditoría (código actual)

| Capa | Componente | Estado | Evidencia |
|---|---|---|---|
| Datos | Ingesta multifuente (yfinance/Finnhub/SEC) | ✅ Cumple | `app/providers/` con Protocols |
| Datos | Baja latencia / Direct Feeds | ❌ No cumple | Solo polling REST; nada SIP-vs-direct |
| Datos | Detección de halts LULD | ⚠️ Parcial | Flag `TRADING_HALT` + penalización 50, sin máquina de estados |
| Datos | SEC realtime + freeze por dilución | ⚠️ Parcial | `DilutionEngine` existe, pero sin congelación automática de señal |
| Datos | Regla $1 / riesgo deslistado | ⚠️ Parcial | Flag `DELISTING_WARNING`, sin contador de días bajo $1 |
| Señal | Régimen de mercado | ❌ No cumple | Sin clasificador bull/bear/chop |
| Señal | Filtro correlación | ❌ No cumple | Sin matriz de correlación intradía |
| Señal | Filtro short-interest/locates | ❌ No cumple | Solo columna `short_interest`, sin gate |
| Señal | Donchian + RVOL≥3-4 + catalizador IA | ⚠️ Parcial | Piezas sueltas (RVOL, breakout, catalyst), sin gate combinado |
| Riesgo | Position sizing dinámico | ❌ No cumple | Nada; solo `default_slippage_pct` en backtest |
| Riesgo | Circuit breakers | ❌ No cumple | Nada a nivel portfolio/día |
| Riesgo | Recálculo post-halt | ❌ No cumple | Nada |
| Ejecución | Routing directo, solo-limit | ❌ No cumple (por diseño) | `DisabledBrokerAdapter`; se especifica como plantillas manuales |

## 1. Capa Infraestructura y Datos

### 1.1 Feeds: SIP vs Direct (realismo retail)
- La cinta SIP consolida con latencia de ~ms frente a direct feeds
  (NASDAQ TotalView / NYSE OpenBook). Un retail no puede pagar co-location;
  la arquitectura correcta es: **interfaz `FeedAdapter` con dos
  implementaciones**: `SipFeed` (Polygon.io Stocks Starter / SIP+, barato,
  MVP) y `DirectFeed` (Activ/Polygon Enterprise, futuro). Toda marca temporal
  conserva `event_time` del feed para medir el lag SIP-vs-direct.
- **Prohibido** basar entradas en velas de 1m SIP durante las 2 primeras
  horas: el desfase SIP es máximo en apertura. Regla: premarket + open con
  quotes del listing exchange únicamente.

### 1.2 Módulo HaltGuardian (LULD)
Estados por símbolo: `TRADING → LIMIT_STATE → HALTED(5-10min) → RESUME_AUCTION → TRADING`.
- Fuente: halts de NASDAQ Trader (`trading-halts` feed) o, en MVP,
  heurística: spread > X% + volumen 0 durante N segundos + quote `H`.
- Al entrar en `HALTED`: **cancelar todas las plantillas de orden
  pendientes** del símbolo, marcar `STALE_DATA`, silenciar señales BUY/SELL
  (solo HOLD), congelar el `SymbolState` del monitor.
- Al `RESUME`: esperar 60s post-reanudación, recalcular score/riesgo desde
  cero (el libro se reconstruye en la subasta), exigir RVOL post-halt ≥ 2
  antes de rearmar señales. Penalización de score −50 ya existe
  (`trading_halt`); añadir decaimiento temporal de la penalización.

## 2. Capa Datos regulatorios: SEC + regla $1

### 2.1 DilutionFreeze (tiempo real)
- Poll SEC submissions JSON cada 5 min para símbolos en listas
  (ya existe `SecEdgarProvider`; añadir job `sync_filings_fast`).
- Congelar compras (`freeze_buys=True`) ante: S-1/S-3 efectivo, 424B2/424B5
  (pricing de oferta), 8-K Item 1.01/3.02 (acuerdo de compraventa / ATM
  activado), FWP de oferta. El freeze dura `offering_lookback_days`
  (30d) y genera flag `RECENT_OFFERING` (ya penaliza −20; subir a bloqueo
  total de BUY, no solo penalización).
- ATM: monitorizar prospectus supplement + ventas reportadas; mientras el
  ATM esté activo, toda subida es sospechosa de ser "vendida contra":
  exigir RVOL ≥ 5 para cualquier BUY.

### 2.2 DollarRule ($1, Nasdaq 5450(a)(1) / 5450(b))
- Nuevo monitor: días consecutivos con close < $1.00 (precio de cierre,
  no intradía). Umbrales: **advertencia a 90 días**, **riesgo crítico a
  150 días** (la notificación llega ~30 días hábiles bajo $1; el periodo
  de cumplimiento es 180 días).
- Efecto: warning → −10 score y `max_position` × 0.5; crítico → bloqueo
  de BUY + flag `DELISTING_WARNING` (ya −30) + exigir spread ≤ 2%.
- Reverse splits para recuperar $1: tratar como evento tóxico —
  `RECENT_REVERSE_SPLIT` pasa de penalización a **bloqueo de BUY 90 días**
  (la evidencia histórica en penny stocks post-split es demoledora).

## 3. Capa Señal y modelado

### 3.1 Régimen de mercado (gate global)
Clasificador diario del universo penny (breadth): % de símbolos sobre
VWAP + mediana de cambio. Regímenes: `RISK_ON` (tendencia amplia),
`CHOP` (rango), `RISK_OFF` (venta amplia), `HALT_STORM` (>N halts/día).
- `CHOP`/`RISK_OFF`: BUY exige score ≥ 80 (vs 70) y RVOL ≥ 4.
- `HALT_STORM`: solo SELL/exit, cero BUY nuevos.

### 3.2 Filtro de correlación
Antes de cada BUY, correlación de retornos 5m del símbolo vs resto de la
lista (ventana 60m). Si `|ρ| > 0.85` con otro candidato del mismo día
(mismo pump sectorial / cestas manipuladas), tomar solo el de mayor score.
Evita concentrar 5 posiciones en el mismo esquema pump-and-dump.

### 3.3 Reversión a la media con ShortSqueezeGate (Simons/Connors)
- Estrategia base Connors: RSI(2-4) < 10 + cierre sobre SMA200-diaria +
  entrada al revertir intradía. **Gate previo obligatorio**:
  1. `short_interest_pct_float` < 20% **o** tendencia bajista confirmada
     (bajo VWAP todo el día), si no → prohibido el short/contrarian.
  2. Disponibilidad de locates: sin confirmación de borrow barato
     (tasa < 10% anualizada), prohibido ponerse corto; solo señal LONG
     de reversión o HOLD.
  3. Días-consecutivos-parabólicos > 3 con RVOL creciente = squeeze
     activo → **inversión del modelo**: se bloquea mean-reversion bajista
     y solo se permite momentum-long con stop ATR.
- Sin estos gates, un short squeeze destruye cualquier reversión bajista:
  documentar como restricción dura, no parámetro.

### 3.4 Donchian + RVOL + catalizador IA (ruptura)
Gate de entrada long por ruptura Donchian(20d), **todas** obligatorias:
1. Close > máximo 20d **con** RVOL_same_time ≥ 3.0 (≥ 4.0 en régimen CHOP).
2. Catalizador validado por IA con `impact=high` y `confidence ≥ 0.8`,
   de fuente primaria (filing/comunicado), < 24h de antigüedad.
   Sin catalizador → ruptura falsa por defecto → HOLD.
3. Spread ≤ 2% y dollar_volume ≥ $2M en la sesión (liquidez ejecutable).
4. Sin freeze de dilución ni halt en las últimas 2 sesiones.
Esto convierte el breakout rompe-cuello clásico en un evento de
alta convicción y filtra el ~80% de falsas rupturas del sector.

## 4. Capa Riesgo

### 4.1 Position sizing dinámico (nunca fijo)
Fórmula por operación (sobre equity de la cuenta paper):
`risk_per_trade = 0.5% equity` (1% solo si score ≥ 85 + catalizador high).
`shares = risk_per_trade / (1.5 × ATR14)`, limitado por:
- ≤ 5% del volumen medio 5m (impacto),
- ≤ 10% del float (evitar ser la liquidez),
- dollar cap por score: score 70-79 → $2k; 80-89 → $5k; 90+ → $10k
  (cifras ejemplo, configurables en `risk:`).
**Kelly vetado** en penny stocks: las colas son tan gordas que Kelly
puro sobreapuesta; usar Kelly fraccional ≤ 0.25× solo como techo
teórico, nunca como asignador.

### 4.2 Circuit breakers (tres niveles)
- **Símbolo**: −8% intradía desde la entrada o halt → salida total,
  veto 24h al símbolo.
- **Estrategia**: −3% del equity en el día en una estrategia → esa
  estrategia se apaga hasta mañana.
- **Portfolio**: −5% día o 3 halts sufridos → **kill switch**: cancela
  todo, monitor solo-lectura, alerta crítica a Telegram.
Todo persistido en DB (`circuit_events`) para auditoría.

### 4.3 Recálculo post-halt y post-oferta
Tras RESUME o pricing de oferta: invalidar todo el `SymbolState`
(score, VWAP side, bloqueos), exigir 60s + 1 vela completa antes de
reevaluar, y aplicar `post_event_penalty` −15 durante la sesión.

## 5. Capa Ejecución (manual-asistida, restricción DEGIRO)

Dado que DEGIRO es ejecución manual exclusiva:
- El bot genera **plantillas de orden** (no órdenes): símbolo, lado,
  tipo=LIMIT obligatorio, límite calculado (bid/ask ± offset por
  urgencia), cantidad del sizer, validez day, venue sugerida.
- **Prohibidas las market orders** en este universo: el slippage medio
  en quiebres supera el 2-5%. Regla dura en el generador de plantillas.
- Routing directo (ARCA/BATS/EDGX, ECN preferida por spread histórico)
  se deja especificado en `execution:` config y en `BrokerAdapter`
  para un futuro broker DMA; hoy se muestra como instrucción de
  enrutado manual junto a la plantilla.
- Backtest: slippage mínimo 1% + comisión + penalización extra si
  spread > 3% (hoy el backtest ya modela slippage/liquidez; añadir el
  término de spread).

## 6. Roadmap (orden)

1. `HaltGuardian` + freeze de señales (seguridad primero).
2. `DilutionFreeze` + `DollarRule` (datos SEC ya existen).
3. `ShortSqueezeGate` + gate Donchian/RVOL/catalizador.
4. Régimen + correlación.
5. `PositionSizer` + circuit breakers + plantillas de orden limit.
6. `FeedAdapter` SIP-vs-direct (último: es el más caro y el que menos
   alfa aporta a un retail sin co-location).

## 7. Nota de realismo institucional
Sin co-location ni TotalView, este sistema **no compite en latencia
con HFT**: compite en selección (catalizador + dilución + régimen) y
en no-operar (filtros). La ventaja cuantificable está en evitar las
trampas (ofertas, splits, halts, squeezes), no en ser el más rápido.
