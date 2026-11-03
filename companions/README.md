# Jarvis Companion

Due applicazioni condividono la UI e i contratti del core: **desktop Electron
per macOS/Windows** e **mobile Capacitor per iOS/Android**. Sono client del core
remoto; non avviano un secondo modello o scheduler. L'esecutore desktop è un
processo distinto, senza porte in ingresso. L'app locale AppKit esistente resta
disponibile come modalità separata.

## Funzioni

- Chat e continuazione delle conversazioni, Today, attività, documenti, posta,
  routine, automazioni, memoria, Jira/GitHub e Home Assistant tramite il core.
- Approvazioni e stato durevole delle attività, privacy e ambito per sessione.
- Configurazione amministratore di modello, API key, budget, voce e servizi.
- Dispositivi abbinati, revoca e selezione dell'esecutore per conversazione.
- Registrazione esplicita, revisione della trascrizione e riproduzione opzionale.
- Push APNs/FCM con dettaglio autenticato; nessuna approvazione dal solo payload push.
- Notifiche generiche macOS/Windows quando la finestra è in background, con
  deduplicazione delle ricevute; l'app deve essere attiva e il sistema deve consentirle.
- Condivisione Android e share extension iOS: fonti locali in attesa per quindici
  minuti, massimo cinque elementi da 3 MB; revisione e invio esplicito nell'app.
  Il contenuto condiviso diventa un allegato, non un'istruzione da eseguire.

La credenziale companion finisce in Keychain su iOS, Keystore AES-GCM su Android
e safeStorage del sistema su desktop. Il refresh ruota; l'access token rimane in
RAM. Il browser usa un cookie HttpOnly sullo stesso dominio e Web Locks fra tab.
L'esecutore ha identità, deposito credenziali e registro degli effetti separati.

Le impostazioni amministrative usano una revisione condivisa: se un'altra app
le modifica mentre il pannello è aperto, il salvataggio viene rifiutato. Usa
**Ricarica impostazioni**, rivedi i valori e reinserisci le modifiche desiderate.

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

Il bundle contiene UI, esecutore e adattatore nativo opzionale. Non contiene i
dati del core, chiavi di modelli o credenziali di un dispositivo. I risultati
vanno in `dist/companions/`. Per una build di sviluppo senza selezionare
certificati macOS usa `CSC_IDENTITY_AUTO_DISCOVERY=false`.

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

Per push reali segui il [manuale del server](../deploy/README.md). Il JSON client
Firebase Android, le firme e le chiavi private non vengono generati dal repository.
La companion funziona in chat anche senza configurazione push.

## Esecutore e permessi

Abbina prima la companion al tuo server HTTPS. Da un dispositivo amministratore
genera un codice **esecutore**; sul desktop scegli una cartella specifica e i
grant di lettura, scrittura e comandi. La GUI consente una cartella per
configurazione; l'interfaccia CLI JSON supporta fino a 32 workspace distinti.
Non sono consentite la home intera, la radice del filesystem o la cartella dei
dati dell'esecutore. Le scritture usano il confronto dell'hash letto in precedenza.

I comandi sono disabilitati senza consenso locale e prefissi autorizzati.
Possono eseguire codice del progetto con i tuoi permessi utente: non costituiscono
una sandbox del codice. Catene e sostituzioni della shell sono rifiutate.
Il core conserva le proprie approvazioni, anche quando il grant locale è presente.

Su Mac puoi concedere separatamente lettura calendario, modifiche approvate e
scelta di una finestra per richiesta. Sono funzioni Apple; su Windows calendario
e servizi cloud vengono gestiti dal core, mentre file e comandi usano l'esecutore.
Un aggiornamento che cambia l'adattatore nativo richiede di concedere nuovamente
quei permessi locali. Revoca la vecchia identità dopo un nuovo abbinamento.

L'agente apre WSS verso il server, autentica il dispositivo, pubblica capacità
senza percorsi assoluti e riceve lavori con ID, hash e scadenza. Il registro locale
impedisce la seconda esecuzione dello stesso ID. Dopo un'interruzione gli effetti
incerti richiedono verifica; il trasporto può ritrasmettere una ricevuta, senza
rieseguire il lavoro. Schermate e risultati privati non sono salvati nel registro.

**Ferma esecutore** chiude il collegamento e interrompe il lavoro locale; un
effetto già iniziato può rimanere incerto. Chiudere soltanto la finestra mantiene
tray e processo. Per l'avvio automatico serve una sessione utente collegata.

## Verifiche e limiti osservati

La CI `remote-companions.yml` costruisce server Linux, desktop macOS/Windows,
Android e simulatore iOS senza credenziali di firma o provider. La regressione
conserva anche i test dell'app locale. I test non valgono come verifica di
microfono, Keychain/TCC, push o share sheet su ogni dispositivo fisico.

Le build verificate in questa sessione sono macOS ARM64, Android debug con lint e
iOS simulatore ARM64 con share extension. Il builder Windows è predisposto in CI;
non è stato eseguito su questo host macOS. APK debug e app simulatore non sono
release per gli store. Vedi il [registro completo](../docs/32-remote-implementation.md).
