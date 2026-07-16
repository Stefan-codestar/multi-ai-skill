# Streaming-Output Implementierungsdetails

## Architektur

Streaming betrifft NUR die Synthesizer-Phase. Die Worker-Phase bleibt parallel
(alle 3 Antworten muessen vor der Synthese vorliegen).

```
Worker (parallel, nicht gestreamt) -> synthesize_stream() -> live stdout
```

## Komponenten

### providers.py — `stream_complete()` + `_raw_stream()`

`_raw_stream()` ist der Low-Level SSE-Parser:
- Sendet `stream: true` mit `Accept: text/event-stream`
- Parst `data:`-Zeilen, yieldet rohe `delta`-Dicts
- HTTP 400 mit `extra_body` -> automatischer Retry ohne `extra_body`
  (Ollama Cloud unterstuetzt `reasoning_effort` beim Streaming-Endpoint nicht)

`stream_complete()` ist die oeffentliche Schicht mit Thinking-Model-Retry:
- Sammelt Content-Deltas aus `_raw_stream()`
- Wenn 0 Content-Chunks aber `reasoning`-Deltas vorhanden waren:
  Token-Budget wurde durch Reasoning verbraucht -> Retry mit 4x `max_tokens`
  (bis `thinking_retry_cap=65536`), analog zu `complete()`
- Sobald Content-Chunks kommen, werden sie live yielded (echtes Streaming)

### aggregate.py — `synthesize_stream()`

Wie `synthesize()`, aber nutzt `provider.stream_complete()` statt `.complete()`.
Baut die gleichen System/User-Messages, yielded chunks.

### pipeline.py — `run_multiai_stream()`

Generator-Funktion. Worker-Phase per `fan_out()` (unchanged).
Synthese per `synthesize_stream()` — yielded chunks an Caller.
Logging am Ende (best-effort, sammelt `final` aus allen chunks).

### cli.py — `--stream` Flag

`--stream` (ohne `--json`): iteriert `run_multiai_stream()`,
`print(chunk, end='', flush=True)` pro Chunk.

## Bekannte Pitfalls

1. **reasoning_effort + Streaming = HTTP 400**
   Ollama Cloud lehnt `reasoning_effort` im Streaming-Endpoint ab.
   Loesung: HTTP 400 abfangen, `extra_body` entfernen, erneut versuchen.

2. **Thinking-Modelle verbrauchen Token-Budget fuer Reasoning**
   glm-5.2 sendet beim Streaming hunderte `reasoning`-Deltas mit `content: ""`.
   Wenn das `max_tokens`-Budget fuer Reasoning verbraucht ist, bleibt Content leer.
   Loesung: Stream puffern, bei 0 Content + Reasoning -> 4x `max_tokens` retry.
   Dadurch ist der erste Versuch NICHT echt gestreamt (wird gepuffert),
   aber ab dem zweiten Versuch (mit groesserem Budget) kommt Content live.

3. **`RoutingProvider` muss `stream_complete` weiterleiten**
   `RoutingProvider` hat keine eigene API-Logik — muss `stream_complete`
   an den underlying `OllamaCloudProvider` delegieren per `yield from`.

4. **`finish_reason: 'stop'` ohne Content ist kein Fehler**
   Thinking-Modelle koennen mit `finish_reason: 'stop'` enden und
   trotzdem keinen Content geliefert haben. Das ist kein API-Fehler
   sondern ein Budget-Problem -> Thinking-Model-Retry.