# Core remoto personale

Questa distribuzione avvia una sola autorità Jarvis con modelli esterni via API.
Il computer personale non deve restare acceso per chat, memoria raggiungibile dal
server, calendari cloud, pianificazioni e integrazioni di rete.

Il progetto include core, parser isolato e proxy HTTPS. Il parser non ha rete,
credenziali o volume dei dati del core. Il Mac/PC usa un esecutore separato con
WebSocket TLS in uscita: non pubblicare porte sul computer.

## Requisiti e avvio

- Linux con Docker Engine e Compose v2; architettura ARM64 o x86_64.
- Dominio con DNS verso il server e porte 80/443 raggiungibili per Caddy.
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
