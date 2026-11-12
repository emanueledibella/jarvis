# Core remoto personale

Manuale aggiornato al 3 novembre 2026 sulla sorgente `6ff2d65`. Per modalità,
contratti, verifiche e limiti di rilascio vedere la
[matrice corrente](../docs/33-current-state-and-verification.md).

Questa distribuzione avvia una sola autorità Jarvis con modelli esterni via API.
Il computer personale non deve restare acceso per chat, memoria raggiungibile dal
server, calendari cloud, pianificazioni e integrazioni di rete.

Il progetto include core, parser isolato e proxy HTTPS. Il parser non ha rete,
credenziali o volume dei dati del core. Il Mac/PC usa un esecutore separato con
WebSocket TLS in uscita: non pubblicare porte sul computer.

## Requisiti e avvio

- Linux con Docker Engine e Compose v2; architettura ARM64 o x86_64.
- Dominio con DNS verso il server, oppure IPv4 pubblico stabile. Le porte
  80/443 devono essere raggiungibili per Caddy.
- Storage persistente e backup esterni. Una sola replica del core per volume SQLite.
- Per iniziare: 2 vCPU, 4 GB RAM, 20–40 GB disco, nessuna GPU. Le soglie Compose
  sommano circa 2,1 GB prima del sistema operativo: una VM da 2 GB richiede limiti
  ridotti e verifiche del proprio carico. Il modello esterno ha un costo distinto.

Dalla radice del repository:

```sh
cp deploy/.env.example deploy/.env
# Modifica JARVIS_PUBLIC_HOST, per esempio jarvis.tuodominio.it.
docker compose --env-file deploy/.env -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
```

Non inserire API key in immagini o app. Crea il primo codice amministratore:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml exec core \
  /app/.venv/bin/jarvis remote-pair --owner
```

Apri `https://jarvis.tuodominio.it` o una companion. Inserisci origine HTTPS,
nome del dispositivo e codice. Il codice dura dieci minuti ed è monouso.
Nel pannello **Modello** configura provider, modello, chiave dedicata, prezzi
dei token e budget. Il test del modello avvia una richiesta API esplicita.
Puoi modificare anche fuso orario, meteo, calendari, Second Brain e voce.
Le impostazioni dell'host, dei volumi e del proxy rimangono amministrazione del server.

Le modifiche amministrative richiedono la revisione corrente delle impostazioni:
se un altro client salva nel frattempo, ricarica dopo il conflitto. L'ambiente
Compose blocca alcuni valori, fra cui una sola attività concorrente. Il core forza
profilo cloud, nessun workspace/comando host e nessun wake/microfono nativo;
l'esecutore desktop è la destinazione esplicita per il lavoro locale.

`deploy/.env` alimenta le sostituzioni Compose, non è il file delle impostazioni
letto automaticamente dall'app. `JARVIS_PUBLIC_HOST` e i nomi push
`JARVIS_APNS_*`/`JARVIS_FCM_SERVICE_ACCOUNT` vengono tradotti in
`JARVIS_REMOTE_*` nel container. Opzioni aggiuntive richiedono una voce esplicita
in `environment`; aggiungerle soltanto al file Compose `.env` non le attiva.
Le dodici opzioni remote e le 99 impostazioni condivise sono documentate nel
[riferimento completo](../docs/12-configurazione-env.md).

### Prova su una VM dedicata da 1 GiB

Il profilo standard sopra mantiene margine per documenti e carichi variabili.
Per una prima prova personale su **1 vCPU / 1 GiB**, usa Compose **2.24.4+**,
immagini costruite e verificate su un altro computer e l'override
`deploy/compose.small.yaml`. Non costruire frontend, Python o proxy sulla VM.

Il profilo limita core, parser e proxy rispettivamente a **448, 192 e 96 MiB**,
disabilita il loro swap e ammette 24 connessioni al core. La singola attività
concorrente resta bloccata dall'ambiente. I limiti non sono consumo fisso o una
garanzia per ogni documento: OCR, conversazioni lunghe e integrazioni numerose
richiedono misure sul server. Un parser che supera il proprio limite può fallire;
non ampliare automaticamente i limiti oltre la RAM disponibile.

Costruisci per l'architettura effettiva della VM (qui `linux/amd64`):

```sh
docker buildx build --platform linux/amd64 --target core --load \
  -f deploy/Dockerfile -t jarvis-core:verified .
docker buildx build --platform linux/amd64 --target document-worker --load \
  -f deploy/Dockerfile -t jarvis-document-worker:verified .
docker buildx build --platform linux/amd64 --load \
  -f deploy/Proxy.Dockerfile -t jarvis-proxy:verified .
```

Esegui scansione delle immagini e smoke test prima di trasferirle. Dopo il
caricamento delle immagini sulla VM, aggiungi a `deploy/.env` i riferimenti
verificati `JARVIS_CORE_IMAGE`, `JARVIS_WORKER_IMAGE` e `JARVIS_PROXY_IMAGE`.
Il file non contiene chiavi dei provider. Quindi:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml \
  -f deploy/compose.small.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yaml \
  -f deploy/compose.small.yaml up -d --no-build --pull never --wait
```

Il proxy viene costruito da `deploy/Proxy.Dockerfile` con toolchain Go e
dipendenze aggiornate, funziona come UID 10002 e non abilita l'API amministrativa.
Timeout e dimensioni HTTP sono limitati; i log operativi omettono URI e header
per non conservare codici OAuth o credenziali. La verifica delle CVE deve
includere prerequisiti e raggiungibilità, non solo il numero di segnalazioni.

Puoi impostare `JARVIS_PUBLIC_HOST` direttamente all'IPv4 della VM. Il Caddyfile
richiede esplicitamente a Let's Encrypt il profilo `shortlived`, che supporta
certificati pubblicamente validi per IP, e imposta il nome TLS predefinito anche
per i client che non inviano SNI sugli IP. Non serve installare una CA privata
sulle companion. Il certificato dura 160 ore: il proxy deve restare attivo e
conservare il volume `caddy-data` per il rinnovo automatico. Non chiudere le
porte ACME e controlla la scadenza durante le verifiche operative.

Per collaudare prima l'emissione puoi impostare
`JARVIS_ACME_DIRECTORY=https://acme-staging-v02.api.letsencrypt.org/directory`.
Il certificato di staging non è attendibile dai client: verifica il rilascio,
poi passa alla directory di produzione e verifica HTTPS senza disabilitare
il controllo dei certificati.

Su Ubuntu 24.04 x64 appena predisposto, `deploy/harden-ubuntu.sh` prepara un
amministratore SSH, aggiornamenti automatici, firewall, Docker e swap dell'host.
Richiede root, il percorso di una chiave **pubblica** e l'IPv4 verificato
dell'amministratore. Mantiene l'accesso root a chiave finché il nuovo login non
è stato verificato: disabilitarlo è un passaggio successivo. Il firewall cloud
deve essere controllato separatamente, perché le porte pubblicate da Docker
possono aggirare le sole regole UFW. Non cambiare la configurazione di altri
progetti o cluster e non copiare `.env`, dati o chiavi private nel contesto di build.

Gli entry point `jarvis-compose` e `jarvis-backup` e le relative unità systemd
sono predisposti per `/opt/jarvis/current` (symlink a una directory di rilascio
di proprietà root), `/etc/jarvis/deploy.env` (0600) e il profilo da 1 GiB.
Installa gli script in `/usr/local/sbin` e le unità in `/etc/systemd/system`.
`jarvis.service` avvia soltanto immagini già caricate, senza build o pull.
Il timer backup crea una copia age coerente ogni giorno alle 04:15 UTC, con
un breve arresto del core e riavvio anche in caso di errore. Il recipient
pubblico va in `/etc/jarvis/backup-recipient.txt`; l'identità privata resta
fuori dal server. La conservazione locale è di 14 giorni. Il timer non copia
automaticamente gli archivi fuori dalla VM: configura anche una destinazione
esterna e verifica il ripristino.

Il pannello **Dispositivi** emette altri codici companion o esecutore. Un codice
amministratore conferisce anche la gestione delle connessioni e delle chiavi:
usalo soltanto per i tuoi dispositivi fidati. Revoca dall'elenco un dispositivo perso.

Se trasferisci dati dall'app locale, ferma l'autorità precedente e usa una copia
coerente, mai il suo database attivo condiviso. I riferimenti al Portachiavi del
Mac non sono esportabili copiando i file: su un server Linux vengono indicati
come non disponibili e puoi sostituirli dalle impostazioni della companion.
Reinserisci chiavi e credenziali dedicate al core; i grant delle cartelle e del
calendario Apple vanno concessi nuovamente nell'esecutore desktop. Controlla le
routine prima di attivarle sull'unica autorità remota.

## Companion ed esecutore desktop

Vedi [build delle companion](../companions/README.md). Nell'app desktop seleziona
le cartelle locali autorizzate, il relativo ambito e i permessi. Letture,
scritture e comandi sono grant distinti; i comandi richiedono anche prefissi
consentiti e un riconoscimento locale dell'esecuzione di codice con i tuoi permessi.
L'approvazione sul core non amplia questi grant locali.

Su macOS puoi concedere calendario e scelta di una finestra. Il consenso al
calendario appare sul Mac; ogni acquisizione richiede la selezione locale della
finestra. Da telefono scegli l'esecutore nella conversazione. Se più Mac sono
disponibili, Jarvis richiede una scelta esplicita.

L'esecutore vive nella tray/menu bar e può partire al login. Chiudere la finestra
non lo termina; **Ferma esecutore** o **Esci** lo arrestano. Mac sospeso, PC spento
o utente non collegato rendono indisponibili le rispettive capacità. Non esiste
un risveglio remoto automatico. Un lavoro può attendere al massimo dieci minuti
solo con una richiesta esplicita; le operazioni private richiedono un esecutore online.

## OAuth e servizi di casa

Avvia il collegamento delle integrazioni da una companion amministratore. Le
richieste di consenso MCP appaiono in **Autorizzazioni**; il browser torna a
`https://<dominio>/oauth/mcp/<nome>/callback`. L'SDK gestisce PKCE e scambio dei
token. Per posta registra anche `https://<dominio>/oauth/mail/callback` nel client
OAuth del provider. Non usare redirect su `localhost` per il core remoto.

Il core accetta server MCP HTTP autenticati. I processi MCP stdio sull'host del
server sono disabilitati. Credenziali MCP e cache OAuth sono cifrate nei dati
privati. Se cambi un endpoint con bearer, inserisci un nuovo token dedicato.

Home Assistant e Second Brain devono essere raggiungibili dalla VM senza
dipendere dal Mac. Per una rete domestica privata serve una connessione di rete
configurata, per esempio una VPN fra server e casa. Non esporre Home Assistant
anonimamente. L'adattatore conserva allowlist, ambiti e approvazioni già previsti
nel [manuale Home Assistant](../docs/29-assistant-setup.md).

## Voce e notifiche

La voce companion è esplicita: registra fino a sessanta secondi, rivedi la
trascrizione, invia la richiesta e scegli se ascoltare la risposta. STT/TTS usano
una chiave OpenAI dedicata, oppure la chiave del provider testuale solo se è
OpenAI sul suo endpoint ufficiale. Una chiave Anthropic o di un endpoint
compatibile non viene inoltrata a OpenAI. Costi e prenotazioni rientrano nel budget.

I promemoria possono produrre notifiche dell'app. Le push richiedono APNs su iOS
e Firebase Cloud Messaging su Android. Sono generiche: titolo Jarvis, un avviso
e un ID; dettaglio e approvazioni vengono recuperati con autenticazione. Non
attivano chiamate telefoniche. La telefonia resta una capacità separata, con le
proprie credenziali e autorizzazioni.

Per push reali:

1. Configura firma, bundle ID e capability Push Notifications/App Groups del
   progetto iOS; genera una chiave APNs `.p8` nel tuo account sviluppatore.
2. Registra l'app Android in Firebase e metti il suo `google-services.json` in
   `companions/android/app/`. La chiave privata del service account resta sul server.
3. Colloca `.p8` e JSON del service account in `deploy/secrets/`, leggibili da UID
   10001, e imposta i percorsi `/run/secrets/...` nelle variabili di `deploy/.env`.
4. Imposta team/key ID, topic APNs uguale al bundle ID e ambiente APNs coerente
   con la firma; ricrea il core e abilita le notifiche dalla companion.

Non serve esporre ulteriori porte. La consegna dipende anche da rete, permessi e
politiche del sistema mobile; una risposta del provider non prova la visualizzazione.

## Telefonia e capacità dell'host

La voce esplicita della companion e le push non usano Twilio. Per chiamate carrier
sul core remoto configura credenziali e impostazioni telefoniche sull'host del
server, con `telephony_tunnel_mode=external` e URL pubblico coerente. Le modifiche
telefoniche non rientrano nell'allowlist delle impostazioni companion. Il proxy
del core lascia i percorsi `/telephony/` ai controlli di firma/PIN/media esistenti;
il modello cloud e i limiti carrier restano da configurare e verificare.

L'immagine core non include Caddy/cloudflared come processi figli: il proxy è il
servizio Compose separato. **Managed by Jarvis** del
[manuale telefonico](../docs/26-managed-telephony.md) riguarda le installazioni
locali con quei binari, non l'avvio automatico di un secondo tunnel nel container.

Le regole directory e `document_read_workspace` usano filesystem e grant del core.
La modalità remota standard non concede workspace host. Una cartella abbinata
nell'esecutore non diventa un mount o watcher sul server; usa strumenti dispositivo
per file/comandi e upload/condivisione per i documenti da estrarre nel parser.
Hue Bluetooth rimane nell'app locale AppKit; per dispositivi domestici indipendenti
dal Mac serve l'adattatore di rete/Home Assistant con i propri grant.

## Backup e ripristino

`jarvis-backup` usa **age**. Genera e conserva l'identità privata fuori dal
server; per il backup serve soltanto il recipient pubblico `age1...`. Il backup
include database coerenti, configurazioni, token cifrati e chiave master. Non
include l'esecutore sul computer, le chiavi APNs/FCM montate o l'identità age.

Prepara una directory `backups/` scrivibile dal container UID 10001, poi:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml stop core
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm --no-deps \
  -v "$PWD/backups:/backups" --entrypoint /app/.venv/bin/jarvis-backup core \
  backup --data-dir /data --output /backups/jarvis-backup.age --recipient "$AGE_RECIPIENT"
docker compose --env-file deploy/.env -f deploy/compose.yaml start core
```

Il comando rifiuta un core che detiene il lock attivo e non sovrascrive backup
esistenti. Copia il file cifrato fuori dalla VM e prova periodicamente il ripristino.

Su una macchina fidata con `age` e il progetto installato:

```sh
uv run --locked jarvis-backup restore --archive jarvis-backup.age \
  --destination /percorso/nuovi-dati-jarvis --identity /percorso/identita-age.txt
```

La destinazione deve essere nuova o vuota; non usare la radice di un volume già
montato. Verificato il risultato, arresta il core e usa la directory ripristinata
come suo volume `/data`, con proprietario UID/GID 10001. Conserva i permessi privati.

Il ripristino **revoca credenziali dei dispositivi e codici di abbinamento precedenti**, marca incerti i lavori
pendenti, disattiva le routine e mantiene lo stop di emergenza. Genera un nuovo
codice amministratore dalla CLI; controlla integrazioni, attività, spese effettive
del provider e routine prima di riabilitare il servizio. Questo evita che uno
snapshot storico ripristini accessi revocati o ripeta operazioni già avvenute.

## Verifica locale della distribuzione

```sh
docker build --target core -f deploy/Dockerfile -t jarvis-remote-core:dev .
docker build --target document-worker -f deploy/Dockerfile -t jarvis-document-worker:dev .
python3 scripts/smoke-remote.py
```

Lo smoke test crea volumi temporanei e container senza rete, usa dati sintetici
e li rimuove al termine. Controlla autenticazione, caricamento attraverso il
parser isolato e revoca. Non acquista una VM, non richiede certificati pubblici
e non contatta modelli, operatori telefonici o account reali.

## Browser, Python e Apple Salute

Per abilitare i worker isolati costruisci le immagini con `./scripts/build-lab.sh`
e aggiungi `-f deploy/compose.lab.yaml` al comando Compose. Il core usa soltanto
il socket del broker; il socket Docker resta nel servizio broker dedicato.
Imposta `JARVIS_DOCKER_GID` al gruppo numerico del socket Docker sul server
(`stat -c %g /var/run/docker.sock`): il broker usa UID 10001 e quel solo gruppo
supplementare, con tutte le capability rimosse. Sulla VM da 1 GiB aggiungi infine
`-f deploy/compose.lab.small.yaml`: una sandbox alla volta con 384 MB di RAM.
Configurazione, limiti, importazione manuale e condivisione HealthKit iOS sono nel
[capitolo 37](../docs/37-browser-python-apple-health.md).
