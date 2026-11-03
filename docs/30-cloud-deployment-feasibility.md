# Jarvis su una piccola VM con modello via API

Analisi del 2 novembre 2026 sul codice presente nel workspace. Prezzi consultati nella stessa data; disponibilità, imposte e condizioni finali dipendono dal contratto e dall'account.

## Valutazione

**Il deploy è fattibile per un solo utente, senza GPU e senza un modello conversazionale locale.** Una VM con 1 vCPU e 2 GB di RAM è un minimo ragionevole per chat e integrazioni leggere. La scelta consigliata è 2 vCPU, 4 GB di RAM e circa 40 GB SSD: lascia margine e può costare poco più di una macchina da 1 GB.

La VM esegue il servizio Python, gli strumenti, lo scheduler e l'archivio; il fornitore API esegue il modello. La velocità delle risposte dipenderà anche da modello, rete e servizi interrogati: aumentare la RAM della VM oltre il necessario non accelera l'inferenza remota.

Il codice supporta già profilo `cloud`, OpenAI, Anthropic e servizi OpenAI-compatible. Il percorso OpenAI usa Responses API. Sono da configurare modello, chiave dedicata, tariffe e budget. La compatibilità del protocollo non garantisce che ogni modello utilizzi correttamente gli strumenti: serve una verifica sul modello scelto.

**Eseguire il servizio in Linux è già possibile; offrire un accesso remoto comodo e sicuro richiede lavoro aggiuntivo.** L'interfaccia e il launcher nativo sono progettati attorno al servizio locale. Il gateway mobile e il collegamento Mac–server descritti nel [progetto companion](28-companion-architecture.md) restano da sviluppare.

## Misure locali e dimensionamento

È stata costruita un'immagine Linux ARM64 con Python 3.12, dipendenze di produzione bloccate da `uv.lock`, sorgente attuale e dashboard già compilata. Dimensione dell'immagine: circa 667 MiB, senza pesi di modelli locali.

Sono state eseguite due prove, ciascuna limitata a 1 CPU, rispettivamente 1 e 2 GiB di memoria, senza swap aggiuntivo. Il processo era non privilegiato, con filesystem radice in sola lettura e senza rete. Il client cloud reale è stato costruito con credenziali sintetiche; le risposte del modello sono state simulate.

| Memoria dell'intero container, inclusa cache | Limite 1 GiB | Limite 2 GiB |
| --- | ---: | ---: |
| Dopo l'avvio | 302 MiB | 301 MiB |
| A riposo, dopo 2 secondi | 303 MiB | 303 MiB |
| Dopo 20 attività dell'agente | 369 MiB | 364 MiB |
| Picco complessivo osservato | 440 MiB | 433 MiB |

Il carico ha attraversato il vero agente, una chiamata allo strumento dell'orario per attività, SQLite, scheduler e API in processo. Le 20 attività erano organizzate in coppie concorrenti. Sono stati inoltre caricati due PDF sintetici da 30 pagine vuote, elaborati in sequenza: il risultato parziale era atteso in assenza di OCR.

**Limiti della prova:** non misura latenza o qualità di un modello remoto, traffico HTTP attraverso Uvicorn/proxy, consumo nel lungo periodo, integrazioni con account reali, OCR di scansioni reali, telefonia o memoria Second Brain. Non include sistema operativo della VM, daemon Docker, VPN, backup e altri servizi dell'host. I PDF vuoti non sono rappresentativi del massimo carico documentale. Il successo con 1 GiB è un'indicazione di fattibilità, non una garanzia di capacità in produzione.

| Configurazione VM | Uso valutato |
| --- | --- |
| 1 vCPU / 1 GB | Laboratorio o uso molto leggero; poco margine per host, aggiornamenti e picchi. |
| 1 vCPU / 2 GB | Minimo ragionevole per un utente, modello via API, documenti contenuti e una sola attività concorrente. |
| 2 vCPU / 4 GB | Configurazione consigliata per l'uso personale e un margine operativo migliore. |
| 4 vCPU / 8 GB | Da valutare per ulteriori servizi, elaborazioni pesanti o carico misurato; non necessario per la sola chat ordinaria. |

Queste raccomandazioni sono stime basate sull'architettura e sulla prova sintetica. Compilazioni, browser automatizzati, trascrizione locale, OCR concorrente o grandi archivi cambiano il dimensionamento. È preferibile compilare frontend e immagine fuori dalla VM piccola.

## Cosa può funzionare mentre il Mac è spento

| Funzionalità | Situazione su VM Linux |
| --- | --- |
| Chat testuale, agente, attività, progetti e cronologia | Possono funzionare usando il modello via API e l'archivio persistente sul server. |
| Promemoria, routine, briefing e automazioni | Il server acceso può eseguirli; vanno migrate configurazioni, credenziali e pianificazioni. Un promemoria semplice non richiede necessariamente una chiamata al modello; un briefing generato dall'agente sì. |
| Jira, GitHub, calendari Google/Microsoft e posta | Possibili via API/MCP, con credenziali, OAuth e permessi da verificare dalla nuova macchina. |
| Home Assistant | Possibile se la VM può raggiungere l'istanza domestica attraverso un percorso privato disponibile anche a Mac spento. |
| Documenti | Il parsing Python è disponibile; OCR, strumenti di sistema e isolamento dei worker richiedono configurazione Linux dedicata. |
| Telefonia Twilio e voce cloud telefonica | Possibili con account, consenso del proprietario e ingress HTTPS/webhook/media dedicato. Il costo telefonico si aggiunge al modello. |
| Calendario Apple EventKit, schermata scelta, Bluetooth Hue e workspace del Mac | Restano legati al Mac. La VM vede i propri file e dispositivi. Un satellite Mac richiede sviluppo. |
| Microfono, wake word e riproduzione della voce sul Mac | Richiedono il client locale; il launcher attuale non è un client remoto già pronto. |
| Notifiche e promemoria | La cronologia e la campanella interne restano disponibili. Una VM senza desktop non produce da sola banner sul Mac, voce dagli altoparlanti o push sullo smartphone. Le chiamate configurate sono un canale distinto. |

**Second Brain va considerato separatamente.** La documentazione del servizio esistente descrive Neo4j e Ollama per estrazione/embedding. Cambiare il modello conversazionale di Jarvis non modifica quei modelli. I numeri di RAM e costo di questa analisi riguardano Jarvis, non l'insieme Jarvis + Neo4j + inferenza locale.

Per avere memoria disponibile a Mac spento bisogna mantenere Second Brain su un host sempre acceso e raggiungibile, oppure analizzare una sua migrazione separata. L'eventuale passaggio a embedding esterni richiede anche verifica di compatibilità e reindicizzazione. Vedi il [contratto e le dipendenze della memoria](05-memoria-e-integrazioni.md).

## VM, container e accesso remoto

Un container è un modo di distribuire il servizio e può girare dentro la VM. Per questo scenario propongo una VM Linux europea con una sola istanza di Jarvis, avvio e riavvio supervisionati, disco persistente e backup separato. Un servizio gestito per container è un'alternativa se garantisce processo sempre attivo e storage persistente; sospensione per inattività, istanze effimere e replica automatica sono inadatte all'attuale scheduler e a SQLite.

Non servono inizialmente GPU, Kubernetes, Redis o database gestiti. Non vanno eseguite repliche indipendenti dello scheduler né condiviso un SQLite attivo su filesystem di rete. Anche Mac e VM non devono diventare due autorità autonome delle stesse routine.

L'accesso presenta vincoli concreti nel codice attuale:

- Il validatore `api_host` accetta solo `127.0.0.1` e il comando `serve` usa esplicitamente quell'indirizzo.
- Il middleware ammette Host e Origin locali. La dashboard verifica il servizio con una prova HMAC legata anche alla porta. Il frontend assume inoltre porta 80 quando l'URL non ne dichiara una: HTTPS standard richiede un adattamento deliberato.
- Mail OAuth usa un callback loopback sulla porta dell'API; Home Assistant e gli altri client MCP possono usare ulteriori callback locali e avviare il browser per il consenso. Un server senza browser richiede una procedura di autorizzazione assistita e inoltri delle porte corrette, oppure un flusso remoto progettato appositamente.
- Il proxy di telefonia espone solo i percorsi telefonici autorizzati: non è il gateway della dashboard.

Per una prima prova privata dal computer si può mantenere l'attuale confine locale con un tunnel SSH che inoltri la porta locale 8765 alla 8765 loopback del server. L'istanza locale deve essere ferma per evitare conflitti e duplicazioni. Vanno trasferiti in modo protetto il token proprietario e le credenziali necessarie; i riferimenti al Keychain del Mac non sono segreti utilizzabili automaticamente in Linux. I flussi OAuth e le ulteriori porte MCP vanno collaudati singolarmente.

Nel caso Docker, la normale pubblicazione di una porta non rende raggiungibile un processo legato al loopback interno del container. Su una VM Linux una possibile configurazione iniziale usa la rete dell'host mantenendo il listener su loopback; occorre documentare e verificare questa scelta nel packaging di produzione. Il Dockerfile della prova avvia solo il benchmark ed è privo di rete: non è un'immagine di deploy pronta all'uso.

Per l'uso quotidiano da browser remoto o smartphone serve invece un gateway autenticato, con origini esplicite, TLS, sessioni e revoca dei dispositivi, protezione delle approvazioni e API esposte in modo limitato. Una VPN migliora il percorso di rete ma non risolve da sola questi vincoli applicativi. Il [piano Personal di Tailscale](https://tailscale.com/pricing) è gratuito per uso personale non commerciale; per impiego aziendale vanno verificate le condizioni del piano appropriato.

## Prezzi delle VM

| Offerta | Risorse | Prezzo base mensile |
| --- | --- | ---: |
| OVH VPS-1 2027 | 2 vCPU, 4 GB, 40 GB NVMe | Circa 5,48 € IVA italiana inclusa, senza impegno, dal catalogo IT. |
| OVH VPS-1 con anticipo annuale | Stesse risorse | Equivalente a circa 4,65 €/mese IVA inclusa, con 12 mesi anticipati. |
| DigitalOcean Basic | 1 vCPU, 2 GiB, 50 GiB SSD | 12 USD, imposte escluse. |
| DigitalOcean Basic | 2 vCPU, 4 GiB, 80 GiB SSD | 24 USD, imposte escluse. |

Fonti: [offerta OVH Italia](https://www.ovhcloud.com/it/vps/cheap-vps/), [catalogo pubblico OVH IT](https://eu.api.ovh.com/v1/order/catalog/public/vps?ovhSubsidiary=IT), [DigitalOcean Droplets](https://www.digitalocean.com/pricing/droplets).

Per OVH il sito presenta il backup giornaliero incluso, mentre il catalogo quota anche un'opzione standard da circa 0,43 €/mese IVA inclusa: verificare lo sconto applicato, le opzioni obbligatorie e il totale nel carrello. Il piano annuale è un pagamento anticipato e riporta il rinnovo dell'impegno. Per DigitalOcean il [backup settimanale aggiunge il 20%, quello giornaliero il 30%](https://docs.digitalocean.com/products/backups/details/pricing/): il piano da 12 USD diventa rispettivamente 14,40 o 15,60 USD.

Per la scelta economica da 4 GB prevederei **6–10 €/mese di infrastruttura**, da confermare con il totale dell'ordine e la destinazione dei backup. È una stima di budget, non un preventivo. Conservare anche copie coerenti e protette fuori dalla VM; una sola copia delle 24 ore precedenti non sostituisce una strategia di ripristino.

## Costo del modello via API

Esempi dal [listino OpenAI](https://developers.openai.com/api/docs/pricing), modalità Standard e contesto corto, per milione di token:

| Modello | Input USD | Output USD |
| --- | ---: | ---: |
| GPT-6 Luna | 0,10 | 0,50 |
| GPT-6.1 Terra | 1,00 | 5,00 |
| GPT-6.1 Sol | 2,00 | 10,00 |

Applicando queste tariffe, senza sconti cache:

| Consumo mensile ipotetico | Luna | Terra | Sol |
| --- | ---: | ---: | ---: |
| 2 milioni input + 0,2 milioni output | 0,30 USD | 3 USD | 6 USD |
| 10 milioni input + 1 milione output | 1,50 USD | 15 USD | 30 USD |
| 50 milioni input + 5 milioni output | 7,50 USD | 75 USD | 150 USD |

Sono scenari di calcolo, non consumi misurati dell'utente. Escludono imposte, cambio, voce e altri servizi. GPT-Live 1 costa 0,05 USD/minuto: 300 minuti aggiungono 15 USD, oltre a modello backend e strumenti. Telefonia Twilio separata.

Per Jarvis una richiesta dell'utente può generare più round del modello. Storia della conversazione, descrizioni degli strumenti, risultati MCP, allegati e token di ragionamento contribuiscono al consumo. La prova ha rilevato 63 strumenti e circa 29,7 KB di descrizioni/schemi, prima della conversazione e dei risultati: non è affidabile stimare il costo contando solo le parole scritte dall'utente. Anche briefing e agenti schedulati possono consumare API quando non si sta chattando.

La formula è `milioni_input × tariffa_input + milioni_output × tariffa_output`, applicata a tutte le chiamate. Le tariffe cambiano con modello, modalità e contesto; gli sconti di caching vanno verificati sulla fattura reale. Le impostazioni di costo di Jarvis sono stime configurabili e devono rispecchiare il fornitore. Il budget interno prenota e contabilizza le richieste, ma non costituisce un tetto contrattuale alla fattura né include automaticamente i servizi separati.

Le schede [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) e [Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra) documentano streaming e strumenti compatibili con il percorso usato. Luna è un candidato per la prova economica, Terra per un confronto di costo/qualità. Italiano, affidabilità degli strumenti e accesso dal proprio account restano da provare. L'instradamento automatico fra modello economico e modello più capace non è una funzionalità già verificata di Jarvis.

## Lavoro necessario per un utilizzo affidabile

1. **Confezionare il servizio Linux:** immagine o ambiente Python riproducibile, UI compilata, utente dedicato, avvio automatico, arresto pulito, controllo di salute e limiti di risorse. Per la prima VM partire da una sola attività concorrente; disattivare i componenti desktop inutili.
2. **Configurare il modello cloud:** chiave dedicata sul server, permessi e budget del fornitore, tariffe e soglie Jarvis coerenti. Eseguire una piccola verifica reale di italiano, strumenti, errori e consumo prima di affidargli automazioni continuative.
3. **Migrare una sola autorità:** fermare il servizio precedente, copiare database/checkpoint/documenti/configurazioni in modo coerente, riconfigurare i segreti non trasferibili e verificare calendari, OAuth, routine e fuso Europe/Rome. Conservare un piano di ripristino che eviti azioni duplicate.
4. **Garantire la raggiungibilità:** Second Brain e Home Assistant devono rimanere disponibili indipendentemente dal portatile. Verificare callback OAuth, timeout e comportamento durante disconnessioni.
5. **Scegliere l'accesso:** tunnel privato per il collaudo dal computer; gateway e client per l'esperienza remota quotidiana. Companion, push e satellite Mac sono sviluppi distinti dal semplice deploy.
6. **Proteggere l'host e i dati:** accessi SSH con chiavi, firewall, aggiornamenti, segreti privati, log minimizzati, backup protetti fuori dalla VM con prova di ripristino. Il passaggio al modello API comporta l'invio al fornitore dei contenuti selezionati per le richieste, secondo le impostazioni e i permessi configurati.
7. **Rivedere i confini Linux:** i parser hanno un processo limitato, ma l'isolamento filesystem/rete specifico di macOS non viene applicato in Linux. Prima di abilitare documenti non fidati o comandi, isolare i worker con accessi e rete minimi. Il container dell'intero servizio non separa da solo un parser dai segreti del servizio. Evitare mount ampi e socket Docker.
8. **Collaudare il server reale:** avvio dopo reboot, memoria e disco per più giorni, una sola esecuzione per routine, notifiche effettivamente ricevute sul dispositivo desiderato, autorizzazioni scadute, errori API, ripristino e operatività a Mac spento. Questi controlli non sono stati sostituiti dalla prova sintetica.

## Proposta per l'uso personale

Partirei con **una VM europea da 2 vCPU / 4 GB / 40 GB, modello via API, una sola istanza e accesso privato dal computer**. Prevederei 6–10 €/mese per infrastruttura e un budget API iniziale di 10–20 USD/mese per la chat, misurando il consumo prima di aumentare le automazioni. È un budget di partenza e non una garanzia di costo per qualsiasi utilizzo; voce, telefono e Second Brain possono aggiungere altre voci.

Il server sempre acceso è inoltre una base adatta alla futura companion: il telefono invia richieste e riceve risultati anche a portatile spento. Per avere push, voce e capacità del Mac occorre completare i rispettivi client e collegamenti. L'uso tramite SSH serve a validare il servizio; il gateway è il passaggio necessario per rendere comodo l'accesso quotidiano.

Analisi e prove eseguite localmente, con modello e dati sintetici. Non sono state effettuate chiamate a pagamento né acquistate VM. Non è stato implementato un deploy di produzione in questa attività. Script, Dockerfile di prova, metriche e prezzi OVH estratti sono conservati nella cartella locale ignorata `output/cloud-analysis/`.
