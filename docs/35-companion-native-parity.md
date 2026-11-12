# Parità companion e app native

Revisione del 4 novembre 2026. Le companion Electron e Capacitor usano adesso
`Settings.tsx`, lo stesso componente dell'app AppKit, al posto del form remoto
ridotto. Sono presenti tutte le sezioni condivise, compresa Telefonia con SID e
token Twilio, numeri E.164, PIN, ingresso, budget, durata, gestione connessione,
chiamata di prova e riconciliazione delle chiamate dall'esito incerto.

## Impostazioni e confini

L'elenco esplicito `remote_settings.COMPANION_SETTINGS` permette agli
amministratori di configurare i servizi e la voce. Gli altri dispositivi leggono
le preferenze condivise e possono gestire il proprio microfono. Ogni salvataggio,
compresa la lingua, usa la revisione mostrata nel form: una modifica concorrente
richiede **Ricarica impostazioni**. Le chiavi restano cifrate sul core; le risposte
restituiscono soltanto il flag di configurazione. Avvio e arresto della telefonia
richiedono un dispositivo amministratore.

Percorsi, comandi e inferenza locale del server non sono grant del dispositivo.
Le operazioni sul computer passano da **Dispositivi e lavori** e dai grant
dell'esecutore già esistente. La companion non avvia un secondo core. Le vecchie
forzature `voice_enabled=false`/`wake_enabled=false` sono state rimosse anche dal
Dockerfile: impostavano i controlli come bloccati e impedivano l'uso della voce.
Il core non accede al microfono.

## Voce

Il motore Apple `CompanionSpeech.swift` è condiviso fra helper macOS e plugin
iOS: Speech.framework con riconoscimento solo locale, risultati parziali,
rinnovo automatico, recupero con attese crescenti, selezione microfono e sintesi
di sistema. Android usa `createOnDeviceSpeechRecognizer` da API 31, senza
ripiego sul riconoscimento di rete. Le lingue e i servizi locali devono essere
installati. Le piattaforme non compatibili conservano la registrazione manuale.

Il controller comune gestisce attivazione con parola intera, acquisizione del
comando, silenzio di fine turno, invio unico, risposta e continuazione. La scelta
del microfono e il consenso all'ascolto sono separati per core e identità del
dispositivo; non cambiano il microfono di un altro client. Il mute annulla anche
un'abilitazione concorrente o un comando ancora in preparazione.

Con OpenAI Live la nuova connessione `/remote/v1/voice/live` autentica il primo
frame, controlla origine/host, tipo di dispositivo, grant, sessione e privacy;
riutilizza il motore della native e il suo budget. La credenziale non compare
nella URL né viene passata al processo di riconoscimento. Il socket ricontrolla
revoca, scadenza, privacy e stop di emergenza durante la conversazione.
Le riprese vocali appartengono a un solo dispositivo e a una sola sessione.

L'audio Web Audio è ricampionato a PCM16 mono 24 kHz con continuità fra pacchetti.
La riproduzione usa una coda in RAM. Con cancellazione eco disponibile, la voce
durante una risposta apre una ripresa singola, scarta la vecchia riproduzione e
conserva il contesto, senza rinviare la richiesta al vecchio collegamento.
Su dispositivi senza cancellazione eco resta la protezione dell'ingresso durante
la risposta e l'attivazione manuale. Un microfono esplicito che non può essere
identificato nel percorso Live produce un errore; non viene sostituito da un
ingresso diverso.

Su Mac il menu, la scorciatoia globale e l'ascolto restano attivi con la finestra
chiusa. Sospensione/blocco fermano la cattura, salvo il consenso al Mac bloccato.
Su mobile l'ascolto è in primo piano: background e interruzioni audio fermano
microfono, flussi e riproduzione; il ritorno ripristina solo il consenso già dato.

## Verifica

- Suite Python: **646 passati, 2 saltati**, inclusi grant amministrativi, cifratura
  Twilio, revisione concorrente, autorizzazione WSS, revoca durante il collegamento,
  privacy, emergenza e isolamento delle riprese.
- Suite web: **25 passati**, inclusi attivazione e risposta automatiche, invio unico,
  annullamento durante mute/background, continuità PCM a 44,1/48 kHz e ripresa Live
  con rilascio delle tracce audio.
- Bridge desktop: **2 passati**; suite native esistente completata.
- Helper vocale macOS compilato e firmato ad hoc; build iOS simulatore riuscita;
  Android `assembleDebug lintDebug` riuscito.
- Playwright: abbinamento amministratore, pannello condiviso, salvataggio Twilio
  con credenziali sintetiche e resa desktop/mobile. Nessuna chiamata reale avviata.

Log e anteprime sono in `output/companion-parity-*` e `output/playwright/`.
Queste prove non sostituiscono il collaudo acustico di microfono, echo cancellation
e permessi sui dispositivi fisici, né una chiamata reale con credito Twilio.
Per usare le nuove companion va aggiornato anche il core remoto. Le build di
sviluppo locali non costituiscono una pubblicazione App Store/TestFlight.

## Telefonia sul core in uso — 4 novembre

Il core è aggiornato a `jarvis-core:remote-telephony-20261104-r2`. In modalità
gestita usa il proprio indirizzo HTTPS pubblico per webhook e audio Twilio;
non richiede Caddy/cloudflared nel container. La chiusura delle companion non
interrompe il servizio e una configurazione completa e abilitata sopravvive al
riavvio del core. Credenziali e numeri restano nelle impostazioni condivise;
un avvio incompleto non abilita la telefonia e non crea chiamate.

La companion Mac già installata è stata verificata sul core reale: l'attivazione
con i sei requisiti mancanti mostra direttamente le etichette italiane, senza
nascondere il messaggio nei dettagli tecnici o richiedere dipendenze da desktop.
Il pannello con l'elenco dei requisiti e la descrizione del core remoto è stato
aggiunto al sorgente comune e verificato anche a 390 px senza overflow. I
pacchetti Mac/mobile non sono stati ricostruiti per questo aggiornamento del
core; la correzione funzionale è compatibile con quelli già installati.

Verifiche: 75 regressioni Python mirate, 26 test web, build web, Ruff, immagine
Linux isolata e HTTPS reale (health 200, impostazioni anonime 401, webhook senza
firma 403). I tre moduli telefonici sono stati verificati per hash sul server,
con UID 10001 e zero chiamate. Backup cifrato riuscito; proxy, parser, volumi e
abbinamenti conservati. Il primo tentativo ha eseguito il rollback perché
l'avvio delle integrazioni superava l'attesa di 50 secondi; il tentativo finale
ha usato un'attesa di 180 secondi ed è risultato sano. Evidenze in
`output/telephony-core-update/`.

## Correzione voce sul core in uso — 4 novembre

Il primo tentativo nell'app Mac ha mostrato **Abilita voce** e **Attivazione
vocale** disabilitate e bloccate: il server usava ancora l'immagine precedente,
che forzava entrambe a `false`. Il core è stato aggiornato a
`jarvis-core:companion-voice-20261104`, dopo un backup cifrato e la verifica che
non fossero in esecuzione attività o chiamate. Volumi, abbinamenti, credenziali,
parser e proxy sono stati conservati.

Verifiche: 29 regressioni del core passate; test isolato dell'immagine Linux
con entrambi i flag abilitati e modificabili; health HTTPS e autenticazione WSS;
ricaricamento delle impostazioni nella companion reale già aperta. Il controllo
**Ascolta su questo dispositivo** è rimasto selezionato, senza operazioni pendenti,
con stato **In attesa di Jarvis**. `scripts/smoke-remote.py` verifica ora anche che
le immagini non forzino di nuovo voce e wake a disabilitati.

Evidenze locali: `output/companion-voice-core-update/` e
`output/companion-voice-core-before.log` / `companion-voice-core-after.log`.
