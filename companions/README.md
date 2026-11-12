# Jarvis Companion

Stato verificato al 3 novembre 2026, sorgente `6ff2d65`. La
[matrice corrente](../docs/33-current-state-and-verification.md) distingue test
rieseguiti, build di sviluppo e verifiche su servizi/dispositivi ancora necessarie.

Due applicazioni condividono la UI e i contratti del core: **desktop Electron
per macOS/Windows** e **mobile Capacitor per iOS/Android**. Sono client del core
remoto; non avviano un secondo modello o scheduler. L'esecutore desktop è un
processo distinto, senza porte in ingresso. L'app locale AppKit esistente resta
disponibile come modalità separata.

## Funzioni

- Chat e continuazione delle conversazioni, Today, attività, documenti, posta,
  routine, automazioni, memoria, Jira/GitHub e Home Assistant tramite il core.
- Approvazioni e stato durevole delle attività, privacy e ambito per sessione.
- Le stesse schermate Impostazioni dell'app native: interfaccia, modelli, voce,
  memoria, produttività, luci, privacy e telefonia. Configurazione amministratore
  di Twilio, numeri, PIN, ingresso chiamate, limiti e chiamata di prova.
- Dispositivi abbinati, revoca e selezione dell'esecutore per conversazione.
- Attivazione dicendo «Jarvis», richiesta e risposta parlate e ritorno all'ascolto;
  voce di sistema oppure OpenAI Live con voce e stile condivisi con la native.
  Restano disponibili registrazione manuale e revisione della trascrizione.
- Push APNs/FCM con dettaglio autenticato; nessuna approvazione dal solo payload push.
- Notifiche generiche macOS/Windows quando la finestra è in background, con
  deduplicazione delle ricevute; l'app deve essere attiva e il sistema deve consentirle.
- Condivisione Android e share extension iOS: fonti locali in attesa per quindici
  minuti, massimo cinque elementi da 3 MB; revisione e invio esplicito nell'app.
  Il contenuto condiviso diventa un allegato, non un'istruzione da eseguire.
- Browser interattivo e Python isolato sul core, con file temporanei e controlli
  condivisi. Il core remoto richiede i worker e il broker descritti nel
  [capitolo 37](../docs/37-browser-python-apple-health.md).
- Apple Salute su iOS tramite HealthKit: categorie e periodo scelti, permesso di
  sola lettura, anteprima locale e invio esplicito dei soli riepiloghi al core.
  L'uso con modelli cloud ha un consenso separato, inizialmente disabilitato.
  Su tutti i client resta disponibile l'importazione XML/ZIP.
- Controllo finestre ed esecuzione su Mac/PC (focus, minimizza, avvia) ed invio messaggi
  WhatsApp via deep link o scorciatoia nativa Apple Shortcuts descritto nel
  [capitolo 39](../docs/39-automazione-finestre-e-scorciatoie-whatsapp.md).

La credenziale companion finisce in Keychain su iOS, Keystore AES-GCM su Android
e safeStorage del sistema su desktop. Il refresh ruota; l'access token rimane in
RAM. Il browser usa un cookie HttpOnly sullo stesso dominio e Web Locks fra tab.
L'esecutore ha identità, deposito credenziali e registro degli effetti separati.

## Primo collegamento

1. Avvia il core seguendo [deploy](../deploy/README.md) e genera il primo codice
   con `jarvis remote-pair --owner` sul server. Non usare il bearer dell'app locale.
2. Apri la companion o il dominio del core e inserisci l'origine HTTPS senza path,
   il nome del dispositivo e il codice. I codici sono monouso e durano dieci minuti.
3. Dal dispositivo amministratore configura provider, modello, chiave dedicata,
   tariffe e budget. La chiave rimane sul server. Un dispositivo companion senza
   grant amministrativo non può cambiare credenziali o connessioni.
4. Abbina gli altri client con nuovi codici companion. Per lavorare sul computer,
   genera invece un codice esecutore e configura separatamente i grant locali.
5. Apri/continua una conversazione nel relativo ambito. La selezione dell'esecutore,
   scope e privacy sono per sessione; una chat privata richiede la sessione che
   l'ha iniziata. Il cambio di ambito non modifica il microfono di un altro client.

L'access token dura cinque minuti e resta in RAM; il refresh dura trenta giorni
e ruota a ogni uso. Un refresh riutilizzato invalida la sua famiglia. **Esci**
tenta la revoca e dimentica la credenziale locale; senza rete la revoca sul server
può non riuscire: revoca quel dispositivo da un'altra app amministratore online.
L'app standalone AppKit non subentra quando il core è irraggiungibile.

In **Impostazioni → Memoria → Collega Second Brain**, il consenso OAuth compare
in una finestra dentro Jarvis, anche se sei in un'altra sezione. Premi **Apri
consenso nel browser**, accedi a Second Brain e verifica i permessi prima di
autorizzare. Torna poi a Jarvis: solo la conferma **Connessione e strumenti
verificati** indica un collegamento riuscito. La finestra scade dopo tre minuti;
se necessario avvia di nuovo il collegamento. Se la chiudi, puoi riaprirla dal
pulsante **Apri autorizzazione**. I permessi per correzioni e ritrattazioni
richiedono ancora il consenso separato previsto dalla configurazione.

Se Second Brain rifiuta la registrazione con `invalid_redirect_uri`, aggiungi
alla sua configurazione privata `SB_OAUTH_REDIRECT_URIS` il callback esatto
`https://<origine-del-core>/oauth/mcp/second_brain/callback`, mantenendo le altre
destinazioni già autorizzate. Riavvia soltanto il servizio MCP di Second Brain e
riprova il collegamento. Non servono wildcard o modifiche ai permessi sui dati.

Le impostazioni amministrative usano una revisione condivisa: se un'altra app
le modifica mentre il pannello è aperto, il salvataggio viene rifiutato. Usa
**Ricarica impostazioni**, rivedi i valori e reinserisci le modifiche desiderate.

In **Impostazioni → Voce e presenza**, abilita **Ascolta su questo dispositivo**
e concedi microfono e riconoscimento vocale. Il consenso e il microfono selezionato
restano locali; lingua, nome di attivazione, voce, tempi e modello sono preferenze
condivise sul core. Il riconoscimento ambientale resta sul dispositivo e non
ripiega su un servizio cloud. Su Android richiede Android 12/API 31 e un servizio
di riconoscimento locale installato; sui dispositivi non compatibili resta la
registrazione manuale. Anche su Apple serve una lingua con risorse locali.

Sul Mac l'ascolto continua con la finestra chiusa, nel menu di sistema; **⌘⇧J**
avvia un turno. Sospensione e blocco schermo lo interrompono, salvo il consenso
esplicito all'ascolto sul Mac bloccato. Su iOS/Android funziona con l'app in primo
piano e si sospende in background, al blocco o durante un'interruzione audio.

La richiesta iniziata con «Jarvis» resta in ascolto durante le revisioni della
trascrizione e viene inviata dopo la pausa configurata. Su iOS e Mac, OpenAI Live
riceve l'audio dopo il nome dalla stessa cattura, conservato per pochi secondi
in RAM. Se l'inizio audio non è disponibile, o su Android quando l'attivazione
avviene per nome, la companion invia la trascrizione completa. Se è selezionato
OpenAI Live, la stessa voce configurata legge la risposta senza riaprire il
microfono. Il pulsante **Parla con Jarvis** può aprire Live direttamente.

OpenAI Live usa il protocollo vocale della native, attraverso WSS autenticato
sul core, PCM16 mono a 24 kHz, stesso modello, voce (anche `voice_…`), stile,
budget e limiti. Nelle sessioni Live aperte dal pulsante, l'interruzione parlata
richiede la cancellazione dell'eco del dispositivo o cuffie. Con il percorso
nativo aperto dal nome, l'ingresso viene sospeso mentre Jarvis parla. Stop,
mute, logout e cambio sessione rilasciano
il microfono e scartano l'audio pendente. Il cambio di sessione impedisce la lettura
di una risposta privata nella conversazione successiva.

La registrazione manuale conserva il percorso WAV mono 16 kHz, da 0,1 a 60 secondi,
con revisione prima dell'invio. Per questo percorso valgono `phone_stt_model`,
`phone_tts_model` e `phone_tts_voice`; i relativi costi sono nel
[riferimento env](../docs/12-configurazione-env.md#remote-server-options).
Aggiornare anche il core: le versioni precedenti non espongono il nuovo WSS e
non consentono il salvataggio delle impostazioni Twilio dalle companion.
Il [registro di parità](../docs/35-companion-native-parity.md) descrive le verifiche.

## Toolchain e sviluppo

Node 22.23 o successivo della serie supportata, npm e Python 3.12 con `uv`.
Android richiede JDK 21, SDK 36 e Android 8/API 26 o successivo sul dispositivo.
iOS richiede macOS, Xcode e iOS 15 o successivo. Il piccolo adattatore EventKit/
ScreenCaptureKit richiede macOS 14 o successivo. Per Windows usa il builder sul
Windows di destinazione; PyInstaller non genera un eseguibile Windows da macOS.

Dalla radice del repository:

```sh
uv sync --locked --extra dev --extra build
npm --prefix web ci
npm --prefix companions ci
uv run --no-sync python scripts/build-executor.py
uv run --no-sync python scripts/build-native-helper.py
npm --prefix companions run build
npm --prefix companions run desktop
```

Per i pacchetti desktop:

```sh
npm --prefix companions run build:desktop
```

Per una build Mac locale senza usare un certificato personale:

```sh
CSC_IDENTITY_AUTO_DISCOVERY=false npm --prefix companions run build:desktop:adhoc
```

La firma ad hoc usa gli entitlement di sviluppo necessari a caricare i framework
Electron su Apple Silicon; gli entitlement di distribuzione restano separati.
Questa build non è notarizzata e non è una release pubblica.

Il bundle contiene UI, esecutore e adattatore nativo opzionale. Non contiene i
dati del core, chiavi di modelli o credenziali di un dispositivo. I risultati
vanno in `dist/companions/`. `CSC_IDENTITY_AUTO_DISCOVERY=false` impedisce la
selezione automatica di certificati, ma da solo non produce un bundle Mac con
firma completa. Non considerare il solo esito del packaging una verifica di
installabilità su Apple Silicon.

Per una prova personale con un certificato **Apple Development** già presente,
leggi la sua impronta con `security find-identity -v -p codesigning`, imposta
`JARVIS_MAC_SIGN_IDENTITY` all'impronta SHA-1 di 40 caratteri ed esegui:

```sh
CSC_IDENTITY_AUTO_DISCOVERY=false npm --prefix companions run build:desktop:dev
codesign --verify --deep --strict "dist/companions/mac-arm64/Jarvis Companion.app"
```

Lo script firma app, framework e binari inclusi con l'identità scelta, mantiene
hardened runtime e verifica il risultato. Non crea certificati, profili Mac o
notarizzazioni. Usa il percorso `mac` al posto di `mac-arm64` se costruisci x64.

I pacchetti pubblici richiedono firma della propria identità sviluppatore e,
su macOS, notarizzazione. Il processo di build locale non cerca automaticamente
di pubblicare o notarizzare con un account personale.

Per le app mobili:

```sh
npm --prefix companions run sync
npm --prefix companions run android
npm --prefix companions run ios
```

Oppure costruisci Android con `./gradlew assembleDebug lintDebug` dalla directory
`companions/android`, con `JAVA_HOME` su JDK 21 e `ANDROID_HOME` sul proprio SDK.
Per il simulatore iOS:

```sh
xcodebuild -project companions/ios/App/App.xcodeproj -scheme App \
  -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build/ios CODE_SIGNING_ALLOWED=NO build
```

Per dispositivi iOS reali imposta il tuo team per App e JarvisShare. Entrambi
devono usare `group.it.jarvis.companion`; se cambi bundle ID, aggiorna gruppo,
codice dei due target e topic APNs. Il progetto include manifest delle API
privacy per i metadati dei file: i dettagli da dichiarare negli store dipendono
anche da dove ospiti il core e dai provider configurati.

L'App ID principale richiede anche HealthKit; rigenera il relativo profilo dopo
aver aggiunto la capability. L'estensione JarvisShare non usa HealthKit. La
lettura avviene soltanto dal pulsante nella schermata Apple Salute e non scrive
campioni, non invia dati in background e non abilita automaticamente i modelli cloud.

Registra l'App Group nel portale Apple Developer e associalo **a entrambi**
gli ID App ed estensione. La capability abilitata da sola, senza un gruppo
assegnato, produce profili incompatibili con gli entitlement. Dopo aver salvato
l'associazione, lascia rigenerare a Xcode i profili di provisioning automatici.
Per una build di sviluppo su iPhone, usa `-destination 'generic/platform=iOS'`
e `DEVELOPMENT_TEAM=<tuo-team>` con `-allowProvisioningUpdates`; verifica firma
e profilo dell'app e dell'estensione prima dell'installazione. Una build per
simulatore non è installabile sul telefono e una build Development non è una
distribuzione TestFlight/App Store.

Per push reali segui il [manuale del server](../deploy/README.md). Il JSON client
Firebase Android, le firme e le chiavi private non vengono generati dal repository.
La companion funziona in chat anche senza configurazione push.

## Esecutore e permessi

Abbina prima la companion al tuo server HTTPS. Sul desktop, in **Dispositivi e
lavori → Esecutore su questo computer**, scegli una cartella e i permessi. Premi
**Abbina e avvia esecutore**. Su una companion con ruolo di amministratore, il
codice viene generato durante l’abbinamento. Altrimenti chiedi a un amministratore
un **Codice esecutore per un altro computer** e inseriscilo nella sezione di
abbinamento. Una volta abbinato, usa **Avvia esecutore** o **Ferma esecutore** in
base allo stato.

La GUI consente una cartella per configurazione. L'interfaccia CLI JSON supporta
fino a 32 workspace distinti.
Non sono consentite la home intera, la radice del filesystem o la cartella dei
dati dell'esecutore. Le scritture usano il confronto dell'hash letto in precedenza.

I comandi sono disabilitati senza consenso locale e prefissi autorizzati.
Possono eseguire codice del progetto con i tuoi permessi utente: non costituiscono
una sandbox del codice. Catene e sostituzioni della shell sono rifiutate.
Il core conserva le proprie approvazioni, anche quando il grant locale è presente.

Per configurazione CLI, passa il JSON via stdin senza pubblicarlo. Esempio con
sola lettura, dalla radice del repository dopo `uv sync`:

```sh
.venv/bin/jarvis-executor --data-dir /percorso/privato/esecutore --configure <<'JSON'
{
  "server_url": "https://jarvis.example.com",
  "code": "<codice-esecutore-monouso>",
  "name": "Computer di sviluppo",
  "workspaces": [{
    "path": "/percorso/progetto",
    "label": "Progetto",
    "scope": "work",
    "read": true,
    "write": false,
    "command": false
  }]
}
JSON
.venv/bin/jarvis-executor --data-dir /percorso/privato/esecutore
```

Usa percorsi reali e un nuovo codice; `--configure` abbina il dispositivo e poi
termina. Su Windows avvia lo stesso entry point da `.venv\Scripts\jarvis-executor.exe`
fornendo JSON su stdin. Non occorre installare Python per l'esecutore già incluso
nel pacchetto desktop. La configurazione non deve usare la directory dati del core.

Su Mac puoi concedere separatamente lettura calendario, modifiche approvate e
scelta di una finestra per richiesta. Sono funzioni Apple; su Windows calendario
e servizi cloud vengono gestiti dal core, mentre file e comandi usano l'esecutore.
Per acquisire una finestra, usa **Chat → Aggiungi allegati → Scegli una finestra**.
Con l'esecutore Mac connesso, sbloccato e autorizzato, basta la Companion.
Controlla l'anteprima, poi allega la finestra al messaggio. Se il selettore non è
disponibile, puoi allegare uno screenshot dalla stessa finestra di dialogo.
Un aggiornamento che cambia l'adattatore nativo richiede di concedere nuovamente
quei permessi locali. Revoca la vecchia identità dopo un nuovo abbinamento.

La scelta della finestra richiede presenza sul Mac anche se la richiesta parte
dal telefono. Hue Bluetooth, wake/Live nativo, controllo generale di mouse/tastiera
e inferenza di un modello locale non sono capacità dell'esecutore remoto.
Le regole directory e il lettore documenti workspace operano sull'host del core,
non osservano automaticamente le cartelle abbinate: usa strumenti dispositivo
per file/comandi e condivisione/upload per documenti da analizzare sul server.

L'agente apre WSS verso il server, autentica il dispositivo, pubblica capacità
senza percorsi assoluti e riceve lavori con ID, hash e scadenza. Il registro locale
impedisce la seconda esecuzione dello stesso ID. Dopo un'interruzione gli effetti
incerti richiedono verifica; il trasporto può ritrasmettere una ricevuta, senza
rieseguire il lavoro. Schermate e risultati privati non sono salvati nel registro.

**Ferma esecutore** chiude il collegamento e interrompe il lavoro locale; un
effetto già iniziato può rimanere incerto. Chiudere soltanto la finestra mantiene
tray e processo. Per l'avvio automatico serve una sessione utente collegata.

## Verifiche e limiti osservati

La correzione iOS del 4 novembre usa UUID crittografici compatibili con lo schema
locale della WebView e raggruppa gli invii di abbinamento sovrapposti. La sessione
viene preparata prima di consumare il codice monouso. La build iPhone aggiornata
è la 3; il controller della scena conserva la registrazione del plugin nativo
del Portachiavi e una sola WebView, evitando rotazioni concorrenti del refresh.
I payload del bridge Capacitor non sono registrati nei log. Le regressioni del
trasporto e della generazione degli ID sono nella
suite web (19 test). Il controllo HTTP del core da solo non verifica queste
API della WebView: collaudare anche abbinamento e salvataggio su dispositivo.

La CI `remote-companions.yml` costruisce server Linux, desktop macOS/Windows,
Android e simulatore iOS senza credenziali di firma o provider. La regressione
conserva anche i test dell'app locale. I test non valgono come verifica di
microfono, Keychain/TCC, push o share sheet su ogni dispositivo fisico.

Le build verificate in questa sessione sono macOS ARM64, Android debug con lint e
iOS simulatore ARM64 con share extension. Il builder Windows è predisposto in CI;
non è stato eseguito su questo host macOS. APK debug e app simulatore non sono
release per gli store. Vedi il [registro completo](../docs/32-remote-implementation.md).
`dist/companions/verification.json` descrive lo snapshot di sviluppo e gli hash
dei pacchetti precedenti alla revisione documentale, non una release firmata di
questa revisione. I test Python/web/bridge/nativi sono stati rieseguiti come
riportato nel capitolo 33; le build native complete non sono state ripetute per
modificare i manuali. Non è inclusa una companion Electron Linux.
