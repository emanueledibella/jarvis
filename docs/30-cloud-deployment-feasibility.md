# Jarvis su una piccola VM con modello via API

Analisi e benchmark del 2 novembre 2026; architettura aggiornata il 3 novembre.
Prezzi e misure originari mantengono quella data e non sono stati nuovamente
verificati durante la revisione documentale. Per distribuzione e limiti attuali
vedere il [manuale server](../deploy/README.md) e la
[matrice di verifica](33-current-state-and-verification.md).

## Valutazione

**Il deploy è fattibile per un solo utente, senza GPU e senza un modello conversazionale locale.** Il benchmark originario indicava 1 vCPU/2 GB per un carico leggero; i limiti della distribuzione completa richiedono più margine. La scelta consigliata è 2 vCPU, 4 GB di RAM e circa 40 GB SSD: lascia margine e può costare poco più di una macchina da 1 GB.

La VM esegue il servizio Python, gli strumenti, lo scheduler e l'archivio; il fornitore API esegue il modello. La velocità delle risposte dipenderà anche da modello, rete e servizi interrogati: aumentare la RAM della VM oltre il necessario non accelera l'inferenza remota.

Il codice supporta già profilo `cloud`, OpenAI, Anthropic e servizi OpenAI-compatible. Il percorso OpenAI usa Responses API. Sono da configurare modello, chiave dedicata, tariffe e budget. La compatibilità del protocollo non garantisce che ogni modello utilizzi correttamente gli strumenti: serve una verifica sul modello scelto.

**Il core remoto e i client sono ora implementati.** La distribuzione Linux,
le companion Electron/Capacitor e il collegamento WSS al desktop sono descritti
nel [capitolo 32](32-remote-implementation.md). Restano da predisporre la propria
VM, dominio, credenziali, firma e verifiche su dispositivi/servizi reali.

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
| 1 vCPU / 2 GB | Carico leggero del benchmark; per Compose attuale servono limiti ridotti e nuove misure dell'intero host. |
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
| Documenti | Parser isolato senza rete e Tesseract sono inclusi in Compose; permangono limiti di formato/risorse e verifiche OCR sul proprio carico. |
| Telefonia Twilio e voce cloud telefonica | Possibili con account, consenso del proprietario e ingress HTTPS/webhook/media dedicato. Il costo telefonico si aggiunge al modello. |
| Calendario Apple EventKit, schermata scelta e workspace del Mac | Disponibili tramite esecutore con grant locali quando il Mac è online; la finestra richiede scelta locale. Hue Bluetooth resta nella modalità AppKit locale. |
| Microfono, wake word e riproduzione della voce sul Mac | Wake/Live richiedono AppKit locale. La companion Electron usa voce esplicita STT/TTS; non eredita il wake nativo. |
| Notifiche e promemoria | Campanella interna, push APNs/FCM configurate e avvisi della companion desktop attiva. Un core senza audio non parla dagli altoparlanti del Mac; telefonia separata. |

**Second Brain va considerato separatamente.** La documentazione del servizio esistente descrive Neo4j e Ollama per estrazione/embedding. Cambiare il modello conversazionale di Jarvis non modifica quei modelli. I numeri di RAM e costo di questa analisi riguardano Jarvis, non l'insieme Jarvis + Neo4j + inferenza locale.

Per avere memoria disponibile a Mac spento bisogna mantenere Second Brain su un host sempre acceso e raggiungibile, oppure analizzare una sua migrazione separata. L'eventuale passaggio a embedding esterni richiede anche verifica di compatibilità e reindicizzazione. Vedi il [contratto e le dipendenze della memoria](05-memoria-e-integrazioni.md).

## VM, container e accesso remoto

Aggiornamento del 3 novembre: esiste una distribuzione in
[`deploy/`](../deploy/README.md) con un core non root, parser separato e proxy
Caddy HTTPS/WSS. Avvia `jarvis server`; la porta del core rimane interna alla
rete Compose. Non richiede rete host, inoltro SSH o condivisione del bearer locale.

`jarvis serve` e `JARVIS_API_HOST` restano loopback-only per l'installazione
locale. Il comando server aggiunge invece una superficie dedicata con Host/Origin
configurati, codici monouso, token brevi e refresh ruotato, ruoli e revoca.
Le companion usano questo protocollo. L'esecutore Mac/Windows apre WSS in uscita;
non servono porte sul computer. Il proxy telefonico rimane un ingresso distinto.

OAuth sul core remoto usa callback pubblici
`https://<dominio>/oauth/mail/callback` e
`https://<dominio>/oauth/mcp/<nome>/callback`. Il consenso parte dal dispositivo
amministratore e le credenziali restano cifrate sul server. I riferimenti al
Keychain del Mac richiedono nuove chiavi dedicate; copiarli non esporta il segreto.

Il parser comunica via socket Unix, non ha rete né il volume/credenziali del core,
e include Tesseract. Il suo isolamento non deriva dal solo container del servizio.
Il core remoto disabilita workspace/comandi dell'host e MCP stdio; le operazioni
sul computer usano grant dell'esecutore. Non è una sandbox server per compilazioni.

Una sola autorità possiede SQLite e scheduler. Non servono GPU, Kubernetes,
Redis o database gestiti per il carico personale previsto, né si devono
sincronizzare database attivi fra server e Mac. L'app standalone resta separata,
senza failover automatico. Backup age e ripristino conservativo sono implementati:
il restore revoca vecchi dispositivi/codici, disattiva routine e abilita lo stop.

Le soglie Compose sono 1536 MiB per il core, 512 MiB per il parser e 128 MiB per
Caddy, circa 2,125 GiB prima dell'host. Per questi limiti il punto di partenza è
2 vCPU/4 GB RAM; i precedenti test da 1–2 GiB riguardavano il solo benchmark
leggero, non un collaudo completo della distribuzione attuale.
Un host da 2 GB richiede adattare i limiti e misurare il carico, soprattutto OCR.
Second Brain e servizi aggiuntivi vanno dimensionati separatamente.

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

Il codice e il packaging sono disponibili; restano configurazione e collaudo della
propria installazione:

1. **Preparare host/dominio:** Docker/Compose, DNS, porte 80/443, volume privato e
   riavvio supervisionato; seguire il [manuale di deploy](../deploy/README.md).
2. **Abbinare l'amministratore e configurare il modello:** chiave dedicata,
   tariffe/budget coerenti e una verifica reale di lingua, strumenti e consumi.
3. **Trasferire una sola autorità:** fermare l'istanza precedente, usare una copia
   coerente e riconfigurare segreti non esportabili; controllare routine e fuso.
4. **Connettere le dipendenze indipendenti dal Mac:** Second Brain, calendari cloud,
   posta e percorso privato verso Home Assistant, con callback pubblici corretti.
5. **Installare le companion e concedere il desktop:** pairing separati, cartelle,
   prefissi di comando e permessi EventKit/finestra sul Mac; nessuna porta in ingresso.
6. **Configurare i canali reali:** APNs/FCM e relative identità/progetti, oppure
   telefonia esterna con credenziali e ingress propri. La voce companion usa STT/TTS,
   non il percorso Live dei prezzi storici riportati sopra.
7. **Proteggere e ripristinare:** accesso host, aggiornamenti, backup age fuori VM,
   copia separata delle chiavi push e del servizio Second Brain, prova di restore
   con credenziali revocate e routine da rivedere.
8. **Collaudare il sistema reale:** giorni di memoria/disco/carico, una sola
   esecuzione per routine, Mac spento, revoca e disconnessioni, notifiche ricevute,
   OAuth scaduto ed effetti incerti senza replay.

## Indicazione operativa e limiti economici

Per la distribuzione attuale usare il dimensionamento e i comandi del
[manuale server](../deploy/README.md). Le cifre infrastrutturali/API del 2 novembre
sopra sono scenari storici: non sono un preventivo aggiornato, né una misura
dell'utilizzo personale. Prima di ordinare verificare il totale effettivo e
misurare il consumo dopo aver scelto modello, voce, telefono e servizi.

Il core, le companion, il collegamento esecutore, il parser isolato e il backup
sono stati sviluppati dopo il benchmark. Le verifiche locali sono in
[capitolo 32](32-remote-implementation.md) e nella
[matrice corrente](33-current-state-and-verification.md). Nessuna VM è stata
acquistata o pubblicata per questo lavoro. Gli script e le metriche del benchmark
originario restano nella cartella ignorata `output/cloud-analysis/`.
