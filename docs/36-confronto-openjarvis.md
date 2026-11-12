# Confronto tra Jarvis e OpenJarvis

Analisi del 4 novembre 2026.

Successivamente sono state implementate le tre estensioni selezionate: browser interattivo, Python isolato e Apple Salute con importazione XML/ZIP e condivisione diretta HealthKit dalla companion iOS. Stato e configurazione sono nel [capitolo 37](37-browser-python-apple-health.md); la matrice seguente conserva il confronto precedente all’implementazione.

- OpenJarvis: branch main, commit [324c9c3](https://github.com/open-jarvis/OpenJarvis/tree/324c9c3ac61bff07a0d99b715a7511dcd78600c4), acquisito con clone superficiale in una directory temporanea.
- Jarvis: baseline 6ff2d65 e contenuto effettivo del workspace, comprese le modifiche non ancora committate alla voce e alle companion del 4 novembre.
- Metodo: confronto statico di documentazione, implementazioni, configurazioni e test presenti. Non sono stati avviati OpenJarvis, modelli, servizi personali o nuove integrazioni.
- Le priorità e le modalità di integrazione sono valutazioni progettuali per il nostro Jarvis. La presenza di codice upstream non dimostra il funzionamento con i nostri account, dispositivi o carichi.

## Valutazione

OpenJarvis offre soprattutto una piattaforma più ampia per ricerca documentale, integrazioni, skill e sperimentazione sui modelli. Il nostro Jarvis possiede già gran parte delle funzioni quotidiane di un assistente personale.

Le integrazioni con il miglior rapporto fra utilità e compatibilità sono:

1. Catalogo di skill e procedure riutilizzabili.
2. Indice documentale ricercabile, con fonti e connettori selezionati.
3. Browser interattivo ed esecuzione di codice in un worker isolato.
4. Misurazioni di qualità/prestazioni e scelta del modello all'inizio del compito.
5. Canali Telegram/Slack, se utili oltre alle companion che già abbiamo.

Conviene sviluppare adattatori nella nostra architettura. Non emerge una necessità di sostituire FastAPI, LangGraph, Deep Agents, la memoria Second Brain o le companion.

## 1. Funzioni già presenti nel nostro Jarvis

Queste aree non costituiscono nuove funzionalità da importare soltanto perché compaiono nella presentazione di OpenJarvis.

| Area | Riscontro nel nostro repository | Differenza utile da valutare |
| --- | --- | --- |
| Chat, piani, strumenti e delega | [agent.py](../src/jarvis/agent.py), [tools.py](../src/jarvis/tools.py); Deep Agents aggiunge anche il subagente general purpose e la sintesi del contesto | Catalogo di specialisti e procedure configurabili; non la semplice possibilità di delegare |
| Modelli locali e cloud | [Settings](../src/jarvis/config.py), [TaskManager.model](../src/jarvis/agent.py#L201): Ollama, endpoint compatibili OpenAI, OpenAI e Anthropic | Gestione di più endpoint contemporaneamente, scelta per tipo di compito, provisioning e diagnostica |
| Memoria persistente | [memory.py](../src/jarvis/memory.py), [memory_retrieval.py](../src/jarvis/memory_retrieval.py): Second Brain, fonti/revisioni, ambiti, correzioni e letture automatiche | Ricerca su archivi documentali e servizi più numerosi |
| Briefing e produttività | [daily.py](../src/jarvis/daily.py), [calendar_assistant.py](../src/jarvis/calendar_assistant.py), [organizer.py](../src/jarvis/organizer.py) | Nuove fonti per il briefing, anziché ricostruire il briefing stesso |
| Mail e calendario | [mail.py](../src/jarvis/mail.py), [integrations.py](../src/jarvis/integrations.py): Gmail/Microsoft, bozze/invio revisionato, Apple/Google/Microsoft/ICS | Indicizzazione trasversale e nuovi servizi; non aggiungere un secondo sistema mail |
| Routine, monitor e automazioni | [scheduler.py](../src/jarvis/scheduler.py), [automations.py](../src/jarvis/automations.py): cron/intervalli, riavvio, monitor web, sorgenti evento | Stato di un obiettivo mantenuto fra esecuzioni e workflow dichiarativi |
| Documenti e schermate | [documents.py](../src/jarvis/documents.py), [screen.py](../src/jarvis/screen.py): estrazione, OCR, parti citabili, confronto e finestra scelta | Un indice comune dei contenuti e browser con azioni |
| Sviluppo, domotica e MCP | [development.py](../src/jarvis/development.py), [home_assistant.py](../src/jarvis/home_assistant.py), [lighting.py](../src/jarvis/lighting.py) | Nuovi adattatori dedicati; molti servizi possono già essere aggiunti via MCP |
| Voce, telefonia e accesso remoto | [parità del 4 novembre](35-companion-native-parity.md), [remote_voice.py](../src/jarvis/remote_voice.py), [telephony.py](../src/jarvis/telephony.py), companion desktop/mobile | Motori vocali ulteriori e copertura locale su altre piattaforme |
| Costi, autorizzazioni e tracciamento effetti | [budget.py](../src/jarvis/budget.py), [policy.py](../src/jarvis/policy.py), [remote_jobs.py](../src/jarvis/remote_jobs.py) | Metriche di inferenza e valutazioni sistematiche, oltre a costi/token e registro operativo già presenti |

La documentazione del 3 novembre descrive ancora alcune limitazioni vocali superate dalle modifiche successive. Per questo confronto prevalgono il codice attuale, il changelog e il capitolo 35. Restano necessarie le verifiche acustiche e sui dispositivi fisici indicate in quel capitolo.

## 2. Differenze concrete e integrabilità

“Assente” indica l'assenza di una funzione dedicata nel repository Jarvis esaminato. Non esclude che un server MCP esterno, opportunamente configurato, possa già fornire una capacità equivalente. “Parziale” significa che la base esiste e il vantaggio consiste nell'estenderla.

### Aggiunte più utili

| Funzionalità in OpenJarvis | Stato in Jarvis | Cosa integrare concretamente | Impegno relativo |
| --- | --- | --- | --- |
| Skill con SKILL.md e pipeline TOML; catalogo, import e dipendenze [OJ-SKILL] | Assente come prodotto; Deep Agents supporta già skill ma la nostra chiamata non ne configura le sorgenti | Catalogo locale, loader in sola lettura, attivazione selettiva e procedure che chiamano i nostri tool | Medio |
| Ricerca in documenti indicizzati, filtri e risposte con fonti [OJ-RESEARCH] [OJ-SEARCH] | Parziale: legge/confronta documenti e interroga Second Brain; non ha un indice comune degli allegati e degli archivi | Indicizzazione dei documenti autorizzati e tool di ricerca per ambito, origine, autore e data | Medio/alto |
| Connettori per Drive, Notion, Obsidian, Dropbox, Slack, note e riunioni [OJ-CONNECT] | Mancano adattatori dedicati per queste fonti; mail/calendari sono già presenti | Prima uno o due servizi realmente usati, con sincronizzazione, eliminazione e freschezza verificabili | Medio per connettore |
| Browser con navigazione, click, compilazione, estrazione e screenshot [OJ-BROWSER] | Assente come capacità dedicata; ricerca web e lettura HTTP sono già implementate in productivity.py | Worker Playwright con sessioni separate; tool nel gateway e, per il browser del computer, una nuova capacità dell'executor | Medio/alto |
| Interprete Python in Docker e strumenti shell isolati [OJ-DOCKER] | Parziale: comandi autorizzati e sandbox macOS esistono; manca un ambiente di calcolo isolato portabile e sul server | Worker per calcoli, CSV e test, con limiti di risorse, artefatti e nessuna credenziale del core | Medio/alto |
| Metriche di inferenza, energia e aggregazioni per modello [OJ-TELEMETRY] | Parziale: costi, prenotazioni budget, token, eventi e stato dei task esistono | Latenza, tempo al primo token, esiti, costo per compito, confronti fra modelli; energia opzionale | Medio |
| Evals di correttezza e benchmark di prestazioni [OJ-EVAL] | Parziale: abbiamo regressioni del prodotto e test di tool calling, non una suite comparativa di qualità dei modelli | Dataset sintetico italiano/inglese di compiti Jarvis e confronto ripetibile dei modelli | Medio |
| Conversazioni tramite Telegram/Slack/Discord e altri canali [OJ-TELEGRAM] [OJ-SLACK] [OJ-DISCORD] | Assente come canale di chat dedicato; companion, voce e telefonia sono presenti | Adattatore iniziale Telegram o Slack collegato a TaskManager, conversazione e identità del proprietario; WhatsApp richiede il percorso API/webhook [OJ-WEBHOOK] | Medio |

### Estensioni possibili con condizioni

| Funzionalità in OpenJarvis | Stato/differenza rispetto a Jarvis | Valutazione |
| --- | --- | --- |
| Router euristico e selezione appresa dalle tracce [OJ-ROUTER] [OJ-LEARNED] | Il nostro profilo hybrid sceglie il provider in base alla configurazione all'avvio del task. Non classifica la difficoltà della richiesta | Utile dopo misurazioni affidabili. Prima versione: regole esplicite all'avvio, modello/endpoint/prezzi congelati per il task |
| Più motori, rilevamento hardware e diagnostica [OJ-ENGINE] [OJ-MULTI] [OJ-DOCTOR] | Ollama, molte API locali compatibili e il comando doctor sono già presenti. Mancano catalogo multi-endpoint e selezione basata sull'hardware | Estendere la diagnostica esistente con rilevamento hardware e preset dei runtime; verificare il tool calling di ogni modello |
| Download modelli e aggiornamento CLI [OJ-API] [OJ-UPDATE] | Abbiamo build, installazione e diagnostica; non un analogo gestore integrato del download dei modelli o self-update | Miglioria operativa utile. Il comando upstream aggiorna l'installazione Python/Git e non dimostra un sistema di aggiornamenti desktop firmati |
| Apple Foundation Models diretto e provider cloud ulteriori [OJ-ENGINE] | Non abbiamo un adattatore AFM diretto o un provider Google nativo. Un endpoint compatibile può già ridurre parte del lavoro | AFM richiede i requisiti macOS/hardware/SDK dichiarati upstream; verificare contesto, strumenti e qualità prima di adottarlo |
| Workflow dichiarativi, condizioni, cicli e nodi paralleli [OJ-WORKFLOW] | Abbiamo LangGraph/Deep Agents, routine e task concorrenti, ma non un catalogo di workflow dell'utente | Realizzare procedure sul LangGraph già presente, mantenendo checkpoint e controlli sugli effetti |
| Operatori persistenti con memoria di lavoro tra esecuzioni [OJ-MONITOR] | Routine e monitor esistono. Manca un oggetto “obiettivo persistente” con avanzamento e contesto strutturato riutilizzato a ogni ciclo | Estensione dello scheduler esistente; non installare un secondo scheduler sullo stesso lavoro |
| Specialisti e wrapper Claude Code/OpenCode/OpenHands [OJ-AGENTS] | La capacità di programmare/delegare esiste. Non abbiamo un selettore di questi backend specializzati | Opzionale; aggiungere solo backend necessari, con ambiente, credenziali e budget distinti |
| Kokoro locale e più motori STT/TTS [OJ-KOKORO] | Voce Apple/OpenAI e percorsi STT già esistono, anche nelle companion aggiornate. Manca Kokoro e una catena vocale locale condivisa per ogni piattaforma | Utile per qualità/offline su Windows/Linux; richiede distribuzione dei modelli e collaudo audio, non soltanto una dipendenza Python |
| RSS/news, Google Tasks, contatti e fonti per briefing più ricchi [OJ-CONNECTORS] | Progetti/attività, meteo, calendario e briefing sono già presenti; queste sorgenti dedicate mancano | RSS e contatti sono aggiunte circoscritte. Google Tasks è una sincronizzazione da progettare con conflitti, non un rimpiazzo dell'organizer |
| Strava, Oura, Apple Health e cronologia musicale [OJ-STRAVA] [OJ-HEALTH] [OJ-SPOTIFY] | Mancano adattatori dedicati | Priorità bassa finché non servono. Apple Health upstream legge file/database locali o un export; Spotify indicizza ascolti recenti, non dimostra controllo della riproduzione |
| Generazione immagini e trascrizione di file audio [OJ-IMAGE] [OJ-AUDIO] | Manca un tool immagini; esistono già trascrizione/voce, ma non un servizio generale di allegati audio equivalente | Tool opzionali, costi media separati e restituzione di artefatti. Il vecchio adattatore immagini upstream va aggiornato/verificato prima del riuso |
| Query a database esterni e strumenti dati [OJ-DB] | Comandi e lettura CSV consentono già analisi; manca una connessione DB dedicata e controllata | Possibile con credenziali realmente read-only, database ammessi e query limitate; non esporre il DB operativo di Jarvis al modello |
| Dati macroeconomici e cambi tramite FXMacroData [OJ-FX] | Non abbiamo un adattatore specifico | Tool di dominio opzionale; non aggiunge una capacità generale necessaria all'assistente |
| Grafo di conoscenza [OJ-GRAPH] | La memoria Second Brain è già la fonte canonica e i tool di lettura ammessi includono reason_memory | Verificare quanto offre il servizio configurato. Non duplicare entità/fatti in un secondo grafo solo per avere un modulo interno |
| Scan dei confini dati, detector e policy di sicurezza [OJ-BOUNDARY] [OJ-SECURITY] | Abbiamo già separazione ambiti, contesto non fidato, controlli di rete, gateway, segreti e registro degli effetti | Importare idee per diagnostica e verifiche aggiuntive; preservare le nostre regole operative |
| Esposizione degli strumenti via MCP e libreria A2A [OJ-MCP] [OJ-A2A] | Jarvis è già client MCP; non ha una facciata generale per essere chiamato da altri agenti | Estensione opzionale con identità/grant dedicati. A2A upstream è una libreria, non una funzione attivabile nel server corrente tramite sola configurazione [OJ-BOUNDARY] |
| API di chat compatibile OpenAI [OJ-API] | Il nostro core offre le API Jarvis per i propri client, non una facciata chat/completions generale | Utile solo per collegare client esterni; occorre tradurre identità, sessioni, streaming e decisioni sugli effetti |
| Runner Wasmtime per moduli WASM [OJ-WASM] | Assente | Opzione sperimentale per calcolo ristretto. Il codice usa fuel, ma non applica nel percorso esaminato i parametri di memoria e timeout: va completato prima di adottarlo come confine di sicurezza |
| Ottimizzazione da tracce, DSPy/GEPA, training e spec search [OJ-LEARNING] [OJ-SPEC] | Assente; la memoria del proprietario non equivale ad apprendimento del modello | Lavoro sperimentale successivo a raccolta dati, benchmark separato e valutazione delle regressioni |
| Mining Pearl [OJ-MINING] | Assente | Modulo separato dall'assistente; non emerge utilità per il nostro Jarvis |

## 3. Che cosa riutilizzare e come

### Skill: appoggiarsi al framework che abbiamo

Il punto di ingresso è [TaskManager.graph](../src/jarvis/agent.py#L457). La chiamata attuale a create_deep_agent non configura skill o specialisti dedicati. La versione Deep Agents installata contiene già SkillsMiddleware, SubAgentMiddleware e sintesi del contesto.

L'aggiunta utile è quindi un prodotto intorno a queste capacità: catalogo, importazione verificabile, versione, abilitazione per ambito e caricamento su richiesta. Le procedure strutturate di OpenJarvis possono ispirare il formato; i loro strumenti devono essere tradotti nei nostri tool, senza importare un secondo sistema di autorizzazioni.

Un primo risultato verificabile: installare una procedura di analisi riunione, mostrarne origine/versione e farle usare soltanto gli strumenti già concessi. Una skill non deve poter estendere da sola i permessi dell'executor o accedere ai file del computer attraverso il filesystem virtuale del framework.

### Archivi: aggiungere ricerca ai documenti, conservando Second Brain

[Documents](../src/jarvis/documents.py#L59) gestisce estrazione, lettura a parti, confronto, ambito, scadenza e documenti privati. Il modello può già collegare informazioni usando strumenti distinti; il vantaggio nuovo è un indice comune, interrogabile e aggiornabile.

Una prima versione può usare SQLite FTS5 sui documenti autorizzati, con identità della fonte, hash, parte citabile, ambito, versione, scadenza e ultimo aggiornamento. La ricerca semantica e la fusione di classifiche sono un secondo passo da misurare. L'indice va eliminato insieme al documento; i contenuti privati devono conservare la loro scadenza e sessione.

Drive/Notion possono essere server MCP dedicati oppure connettori nativi. Il secondo approccio serve soprattutto quando desideriamo un archivio sincronizzato e ricerche locali. Obsidian e Apple Notes sul computer remoto richiedono acquisizione tramite capacità locali concesse: l'executor attuale non monta né sincronizza automaticamente quelle cartelle.

Second Brain rimane la memoria dei fatti e delle decisioni, con fonti e revisioni. Indicizzare un'email o una nota non significa adottarne automaticamente tutte le affermazioni come fatti sul proprietario.

### Browser e calcolo: servizi separati dietro il gateway

Le azioni browser richiedono una nuova capacità: la lettura HTTP attuale non esegue JavaScript e non interagisce con i moduli. La sessione browser deve appartenere al compito/dispositivo corretto. URL, redirect, download, credenziali e azioni con effetti devono attraversare la policy di Jarvis.

Per il codice, il worker deve avere input e output espliciti, limiti di tempo/memoria/processi, filesystem temporaneo e gestione degli artefatti. Il core remoto non dovrebbe ottenere accesso generale al socket Docker: serve un servizio esecutore circoscritto. Il parser isolato già presente è un precedente architetturale, non un interprete Python riutilizzabile senza nuove regole.

Un test di accettazione significativo è completare un'analisi CSV o un test di codice con artefatti scaricabili, mantenendo inaccessibili credenziali e dati del core e terminando realmente il lavoro alla cancellazione.

### Misurazioni e routing: prima misurare, poi scegliere

[TokenEvents](../src/jarvis/agent.py#L66) e [ModelBudget](../src/jarvis/budget.py#L11) sono i punti di estensione per tempi, esiti e costi. I contatori esistenti non devono essere sostituiti da un secondo libro dei consumi.

Servono casi rappresentativi: richieste in italiano, calendario, memoria, tool calling, ricerca con citazioni e programmazione. Per ciascun modello si misurano correttezza, effetti autorizzati, tempi e costo. La misurazione energetica va abilitata soltanto sull'hardware compatibile, distinguendo misure dirette e stime.

Successivamente il router può scegliere un modello leggero o specializzato all'avvio, nei profili che lo consentono. Il profilo local_strict resta locale; cambiare provider durante un task non deve diventare un invio implicito di dati al cloud. Endpoint e prezzi devono continuare a essere registrati nel task.

Il core remoto oggi impone il provider cloud; usare dal server il modello del Mac richiede un nuovo protocollo di inferenza delegata. Non è una capacità che si ottiene copiando MultiEngine o selezionando Exo.

### Messaggistica: iniziare da un solo canale

Telegram o Slack possono usare il core sempre acceso che abbiamo già. Occorre legare il mittente autorizzato a una conversazione, a un ambito e alle sue facoltà, oltre a gestire richieste duplicate e risposte.

La richiesta di rispondere al proprietario attraverso quel canale non autorizza a contattare altre persone. Invii e altre operazioni esterne continuano a passare dal gateway con i loro argomenti esatti. Le companion restano un'interfaccia già disponibile; la messaggistica è una comodità ulteriore.

## 4. Limiti upstream che cambiano la decisione

- **Documentazione e codice non sono sempre allineati.** La roadmap contiene attività ancora da progettare, mentre alcuni moduli più recenti sono già presenti. Il tag Ready significa lavoro affrontabile, non funzionalità già consegnata [OJ-ROADMAP].
- **WhatsApp:** l'adattatore Cloud API è esplicitamente send-only, ma il server aggiunge un webhook di ricezione con verifica della firma e inoltro al bridge. Esistono quindi componenti sia di invio sia di ricezione; la roadmap è arretrata rispetto a questo codice. Il percorso ufficiale resta da configurare e collaudare integralmente con account Meta. Baileys è un'integrazione distinta, segnalata come bloccata nella roadmap [OJ-WHATSAPP] [OJ-WEBHOOK] [OJ-ROADMAP].
- **A2A:** il documento sui confini dati dichiara che il server jarvis serve non monta A2AServer. Il flag di configurazione non crea da solo le route [OJ-BOUNDARY].
- **Collaborazione local/cloud:** esistono port dei paradigmi sperimentali, ma il loro README distingue le implementazioni di inferenza dalle varianti addestrate descritte negli articoli. I risultati citati non sono misurazioni del nostro Jarvis [OJ-HYBRID].
- **Autoapprendimento:** il tutorial spec search utilizza sostituti per teacher, student e judge; il passaggio a sistemi reali richiede componenti, dati e verifiche ulteriori. I moduli di training presenti non dimostrano un miglioramento automatico nel nostro uso [OJ-SPEC] [OJ-LEARNING].
- **TEE, memoria federata e orchestrazione avanzata:** le voci di roadmap non vanno presentate come garanzie pronte per il prodotto [OJ-ROADMAP].
- **I nomi dei backend non equivalgono a nuove capacità.** MLX, LM Studio, llama.cpp e altri server compatibili possono già rientrare nel provider openai_compatible di Jarvis, se locali e compatibili con il contratto richiesto. Non sono stati collaudati in questa analisi; ogni modello va verificato anche sugli strumenti [OJ-ENGINE].

## 5. Modalità di riuso consigliata

Il codice OpenJarvis ha licenza Apache-2.0 [OJ-LICENSE]. Per eventuali copie vanno conservati licenza e avvisi applicabili, indicati i cambiamenti e controllate separatamente le licenze di dipendenze, skill esterne e pesi dei modelli.

Preferire, in ordine:

1. Configurazione dei protocolli che già supportiamo, quando sufficiente.
2. Adattatori nativi piccoli che riusano gateway, ambiti, budget e persistenza.
3. Worker separati per browser, parsing, calcolo o inferenza specializzata.
4. Riuso selettivo di moduli upstream dopo verifica di dipendenze, sicurezza e contratti.

Installare tutto OpenJarvis nel runtime principale non è un'integrazione immediata: ha propri registri, tipi di strumenti, event bus, storage e scheduler; inoltre entrambi i progetti installano il comando jarvis. La sua dipendenza completa aggiunge componenti anche per ricerca e servizi che non ci servono. Un eventuale processo upstream deve avere ambiente e dati distinti.

## 6. Sequenza proposta

| Ordine | Risultato concreto | Dipendenza/criterio di uscita |
| --- | --- | --- |
| 1 | Catalogo skill locale e un insieme piccolo di procedure revisionate | Nessun nuovo permesso implicito; esecuzione attraverso i tool Jarvis |
| 2 | Ricerca negli allegati e un connettore realmente utile | Fonti, ambiti, scadenze, cancellazione e aggiornamenti verificati |
| 3 | Browser interattivo e worker di calcolo | Sessioni isolate, effetti controllati, cancellazione e artefatti |
| 4 | Metriche e benchmark di compiti Jarvis | Confronto ripetibile, senza dati privati nelle fixture |
| 5 | Routing iniziale fra modelli configurati | Qualità/costo misurati; rispetto del profilo e dello snapshot |
| 6 | Un canale Telegram o Slack, se desiderato | Identità, deduplicazione e autorizzazioni complete |
| Successivo | Workflow più evoluti, obiettivi persistenti, voce locale aggiuntiva | Necessità d'uso dimostrata |
| Sperimentale | Training, ottimizzazione automatica e collaborazione multi-modello | Dataset, hardware, budget e valutazione separata |

Le prime due aggiunte porterebbero il beneficio più diretto: Jarvis potrebbe applicare procedure riutilizzabili e trovare informazioni nei nostri archivi con citazioni, oltre alle capacità quotidiane già implementate.

## Fonti upstream

Tutti i link sono fissati al commit analizzato, per rendere il confronto riproducibile.

[OJ-SKILL]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/docs/user-guide/skills.md
[OJ-RESEARCH]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/docs/user-guide/deep-research.md
[OJ-SEARCH]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/connectors/hybrid_search.py
[OJ-CONNECT]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/docs/user-guide/channels-and-connectors.md
[OJ-BROWSER]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/tools/browser.py
[OJ-DOCKER]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/tools/code_interpreter_docker.py
[OJ-TELEMETRY]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/docs/user-guide/telemetry.md
[OJ-EVAL]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/docs/user-guide/evaluations.md
[OJ-TELEGRAM]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/channels/telegram.py
[OJ-SLACK]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/channels/slack.py
[OJ-DISCORD]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/channels/discord_channel.py
[OJ-ROUTER]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/learning/routing/router.py
[OJ-LEARNED]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/learning/routing/learned_router.py
[OJ-ENGINE]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/docs/architecture/engine.md
[OJ-MULTI]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/engine/multi.py
[OJ-DOCTOR]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/cli/doctor_cmd.py
[OJ-WORKFLOW]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/workflow/engine.py
[OJ-MONITOR]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/agents/monitor_operative.py
[OJ-AGENTS]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/agents/__init__.py
[OJ-KOKORO]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/speech/kokoro_tts.py
[OJ-CONNECTORS]: https://github.com/open-jarvis/OpenJarvis/tree/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/connectors
[OJ-STRAVA]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/connectors/strava.py
[OJ-HEALTH]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/connectors/apple_health.py
[OJ-SPOTIFY]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/connectors/spotify.py
[OJ-IMAGE]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/tools/image_tool.py
[OJ-AUDIO]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/tools/audio_tool.py
[OJ-DB]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/tools/db_query.py
[OJ-GRAPH]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/tools/knowledge_tools.py
[OJ-BOUNDARY]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/docs/user-guide/data-boundary-scan.md
[OJ-SECURITY]: https://github.com/open-jarvis/OpenJarvis/tree/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/security
[OJ-MCP]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/mcp/server.py
[OJ-A2A]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/a2a/server.py
[OJ-LEARNING]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/docs/architecture/learning.md
[OJ-SPEC]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/docs/user-guide/llm-guided-spec-search.md
[OJ-MINING]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/docs/user-guide/mining.md
[OJ-ROADMAP]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/docs/development/roadmap.md
[OJ-WHATSAPP]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/channels/whatsapp.py
[OJ-HYBRID]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/agents/hybrid/README.md
[OJ-LICENSE]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/LICENSE
[OJ-WEBHOOK]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/server/webhook_routes.py
[OJ-API]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/server/routes.py
[OJ-UPDATE]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/cli/self_update_cmd.py
[OJ-FX]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/tools/fx_macro.py
[OJ-WASM]: https://github.com/open-jarvis/OpenJarvis/blob/324c9c3ac61bff07a0d99b715a7511dcd78600c4/src/openjarvis/sandbox/wasm_runner.py
