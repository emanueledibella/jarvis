# Revisione e aggiornamento del motore di Jarvis

10 novembre 2026. Obiettivo: ridurre il lavoro necessario per ogni turno e
migliorare la continuità delle richieste lunghe. Il percorso di modifica del
codice si attiva solo quando il proprietario chiede di scrivere o cambiare codice.

## Confronto dei repository

Tutti gli otto checkout in `harnesses` sono stati aggiornati con
`git pull --ff-only` sul rispettivo upstream. Nessun merge locale o rebase.
Sette sono avanzati; `claude-code-leaked` era già allineato. Sono state studiate
le tecniche sotto e implementate nel codice di Jarvis, senza importare sorgenti
dei progetti esaminati.

| Checkout e revisione | Tecnica osservata | Decisione in Jarvis |
| --- | --- | --- |
| Codex `627b579219` | [Ricerca degli strumenti differiti][codex-tools], [cache key e confronto del prefisso][codex-client], [compattazione e conservazione della coda][codex-compact] | Catalogo piccolo e gruppi a richiesta; definizioni in ordine stabile; eliminato il timestamp variabile dal prompt. |
| DeepSeek Harness `fcc0ad4621` | [Loop e superfici degli eventi][dsh-loop], [prefisso stabile anche durante la sintesi][dsh-compact], [ereditarietà dei limiti dei figli][dsh-policy] | Contesto operativo distinto dagli eventi persistenti; stesso provider, ambito e budget del genitore; lo specialista ha un insieme di strumenti più stretto. La compattazione ordinaria è deterministica e non fa una chiamata di sintesi. |
| Gemini CLI `1930f2539` | [Rilevazione di sequenze ripetute][gemini-loop], [compressione che protegge i risultati recenti][gemini-context], [subagenti con limite di turni][gemini-agent] | Rilevazione con firma di argomenti **e** risultati; sequenze con dati nuovi non sono ripetizioni. Risultati recenti protetti finché rientrano nello spazio disponibile. |
| Goose `83d2e92e8` | [Compattazione di chiamate e risposte accoppiate][goose-context], [configurazione dei subagenti][goose-child] | Le coppie rimangono valide nel contesto; le anteprime rimandano all'evidenza originale nello stesso task. |
| Hermes Agent `3d4dd108cf` | [Pruning deterministico senza LLM][hermes-prune], [delega piatta con limiti][hermes-child] | Prima si riducono i risultati vecchi; delega a un solo livello e al massimo due consultazioni per task. |
| Letta Code `d65379f49` | [Richiamo mirato della conversazione][letta-recall], [budget del contesto iniziale][letta-budget], [contesto figlio effimero][letta-child] | Richiamo puntuale dei vecchi messaggi della sola conversazione corrente; nessun fork dell'intera cronologia per la ricerca. Second Brain resta la fonte della memoria personale. |
| OpenCode `23eab68a3c` | [Margine prima del limite e coda recente intatta][opencode-compact], [separazione fra ripresa e replay di effetti][opencode-restart] | Una sola riprova con meno contesto per un errore di capienza. La riprova invia al modello soltanto un nuovo input, senza eseguire di nuovo gli strumenti. Il registro degli effetti resta l'autorità sulle azioni. |
| `claude-code-leaked` `64646773bb` | Checkout non ufficiale; confronto con la documentazione Anthropic su [contesto e strumenti a richiesta][claude-context] e [subagenti isolati][claude-subagents] | Playbook a richiesta e specialista con contesto separato; nessun riuso del sorgente del checkout non ufficiale. |

## Cosa gira in Jarvis

- **Assistente generale.** Il core prepara un prompt stabile e offre pochi
  strumenti per il turno. Un segnale chiaro, per esempio una richiesta sul meteo,
  carica il gruppo pertinente da subito. Se serve altro, `load_tools` carica
  insieme le definizioni e il relativo playbook. Per un intento non riconosciuto
  resta disponibile la scoperta dei gruppi. Gli strumenti continuano a passare
  per il gateway; caricare un gruppo non concede accessi o autorizzazioni.
- **Contesto recuperabile.** Le richieste recenti entrano per turni, con un
  tetto iniziale di 12.000 byte per la cronologia. Quando il contesto cresce,
  prima si riducono i vecchi risultati degli strumenti; le risposte molto grandi
  possono diventare anteprime con riferimenti anche nel giro più recente.
  `read_evidence` recupera il risultato originale del task, entro i limiti
  dell'adattatore. `recall_conversation` cerca una frase nel thread corrente,
  rispettando ambito e privacy. Il messaggio corrente non viene tagliato.
- **Cache.** Le ricerche pubbliche e le letture web riuscite si possono
  riusare nel singolo task per 45 secondi; due richieste simultanee identiche
  condividono il lavoro. La cache tiene al massimo 24 elementi, si svuota
  attorno alle mutazioni e non si salva. Nessun riuso di approvazioni,
  errori, azioni o risultati di ricerche private. Per l'API ufficiale OpenAI,
  i turni non privati usano una chiave stabile per conversazione, modello,
  ambito e modalità; non viene richiesta una conservazione estesa.
  [OpenAI Docs: prompt caching][openai-cache].
- **Loop.** Tre giri uguali, o tre ripetizioni della stessa coppia di giri,
  portano a una risposta finale con le evidenze raccolte e senza strumenti
  disponibili. Esiste un limite anche per giri diversi (fino a otto per un
  turno normale, sedici per ricerca/coding, ridotto se il limite globale è
  più basso). In caso di errore di capienza si tenta una sola volta con meno
  cronologia/evidenze. Gli interrupt di approvazione restano riprendibili.
- **Delega.** Quando un messaggio contiene richieste indipendenti, il coordinatore
  può assegnarle a sottoagenti con `delegate_tasks`. Ogni sottoagente riceve
  un estratto del messaggio corrente e gli strumenti di lettura delle capacità
  selezionate. Il limite simultaneo dei sottoagenti è almeno due, anche sul
  core che ammette un solo task principale. Un valore più alto di
  `max_parallel_tasks` vale anche per i sottoagenti. Ogni esecuzione può
  assegnare fino a otto incarichi. I sottoagenti condividono il budget del task e
  hanno al massimo tre giri di strumenti. Il coordinatore riunisce i risultati,
  esegue le modifiche e gestisce le approvazioni.
- **Specialisti e procedure.** In `harness.py`, `SPECIALISTS` associa una
  capacità a un nome e a istruzioni dedicate. Il gruppo `web` usa il
  ricercatore pubblico. Gli altri incarichi usano il sottoagente generico
  con le procedure della capacità definite in `PLAYBOOKS`. Nella ricerca
  approfondita `consult_specialist` permette anche un riscontro mirato.
  Il percorso di coding usa le istruzioni
  del repository, letture per intervallo di righe, modifica esatta con hash
  dell'intero file e verifiche mirate. Un esempio di codice può essere scritto
  nella risposta; gli effetti sul workspace passano dai controlli esistenti.
  `/code …` esplicita l'intento quando la formulazione è ambigua.

I nuovi task usano LangGraph con middleware mirato. I checkpoint precedenti
senza versione del motore continuano a usare il grafo Deep Agents precedente,
così un'approvazione in sospeso non cambia operazione durante l'aggiornamento.
Il percorso vocale mantiene gli avvisi e usa lo stesso core per le consultazioni.

## Misure riproducibili

Prima richiesta al modello, fixture locale; byte UTF-8 delle istruzioni di
sistema e degli schemi degli strumenti in JSON, senza messaggio dell'utente.
Gli hit reali dipendono da provider, modello, soglia e traffico. Il confronto
misura il carico iniziale e non la fattura o il costo totale di un turno che
richiede la scoperta di altri gruppi.

| Richiesta | Strumenti, prima → ora | Byte, prima → ora |
| --- | ---: | ---: |
| Ciao | 84 → 7 | 65.878 → 5.560 |
| Che tempo fa a Torino? | 84 → 8 | 65.878 → 9.031 |
| Prossimo evento in calendario? | 84 → 11 | 65.878 → 11.258 |
| Correggi il bug in app.py | 84 → 19 | 65.878 → 16.951 |

```sh
.venv/bin/pytest -q -s tests/test_harness.py -k footprint
.venv/bin/pytest -q tests/test_harness.py tests/test_agent_policy.py tests/test_live_voice.py
```

Il dettaglio del task riporta conteggio delle chiamate, letture riusate, picco
degli strumenti esposti e byte delle evidenze omessi. Il dettaglio e
`/api/usage` contano le letture/scritture della cache riportate dal provider
quando disponibili. La stima del budget usa ancora le tariffe configurate,
senza applicare sconti o maggiorazioni della cache.

La sintesi LLM in background, il routing automatico a modelli economici e la
delega ricorsiva possono aggiungere chiamate e complessità. Prima di introdurli,
misurare sui turni reali quanto tempo e quanti token richiedono la scoperta dei
gruppi, le ricerche approfondite e la riprova per capienza.

[codex-tools]: https://github.com/openai/codex/blob/627b579219d492b5445d6d433d3110eb53e507dc/codex-rs/core/src/tools/handlers/tool_search.rs
[codex-client]: https://github.com/openai/codex/blob/627b579219d492b5445d6d433d3110eb53e507dc/codex-rs/core/src/client.rs
[codex-compact]: https://github.com/openai/codex/blob/627b579219d492b5445d6d433d3110eb53e507dc/codex-rs/core/src/compact.rs
[dsh-loop]: https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/core/agent-loop/src/agent.ts
[dsh-compact]: https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/.agents/notes/archived/bug-fix/2026-07-21-compaction-summary-prefix-cache-reuse.md
[dsh-policy]: https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/.agents/notes/archived/feature/2026-07-25-subagent-policy-inheritance.md
[gemini-loop]: https://github.com/google-gemini/gemini-cli/blob/1930f25394c4b6338b64ffdb43083fca41614798/packages/core/src/services/loopDetectionService.ts
[gemini-context]: https://github.com/google-gemini/gemini-cli/blob/1930f25394c4b6338b64ffdb43083fca41614798/packages/core/src/context/chatCompressionService.ts
[gemini-agent]: https://github.com/google-gemini/gemini-cli/blob/1930f25394c4b6338b64ffdb43083fca41614798/packages/core/src/agents/local-executor.ts
[goose-context]: https://github.com/aaif-goose/goose/blob/83d2e92e807372dff9dd61f8c9e46f6c4f070036/crates/goose/src/agents/state_machine/ops_tool_pair_compaction.rs
[goose-child]: https://github.com/aaif-goose/goose/blob/83d2e92e807372dff9dd61f8c9e46f6c4f070036/crates/goose/src/agents/subagent_task_config.rs
[hermes-prune]: https://github.com/NousResearch/hermes-agent/blob/3d4dd108cf52e26cf0d7fb218461e53623a8ec2d/agent/context_compressor_prune.py
[hermes-child]: https://github.com/NousResearch/hermes-agent/blob/3d4dd108cf52e26cf0d7fb218461e53623a8ec2d/tools/delegate_tool_config.py
[letta-recall]: https://github.com/letta-ai/letta-code/blob/d65379f497bfa0c2c55c8be2e5c35b34722c126a/src/agent/prompts/recall_subagent.md
[letta-budget]: https://github.com/letta-ai/letta-code/blob/d65379f497bfa0c2c55c8be2e5c35b34722c126a/src/agent/subagents/context-budget.ts
[letta-child]: https://github.com/letta-ai/letta-code/blob/d65379f497bfa0c2c55c8be2e5c35b34722c126a/src/agent/subagents/ephemeral-subagent.ts
[opencode-compact]: https://github.com/anomalyco/opencode/blob/23eab68a3cae3350c312253c4e6577a6e9f12ab4/packages/core/src/session/compaction.ts
[opencode-restart]: https://github.com/anomalyco/opencode/blob/23eab68a3cae3350c312253c4e6577a6e9f12ab4/packages/core/src/session/execution/restart.ts
[claude-context]: https://code.claude.com/docs/en/how-claude-code-works#the-context-window
[claude-subagents]: https://code.claude.com/docs/en/sub-agents
[openai-cache]: https://developers.openai.com/api/docs/guides/prompt-caching
