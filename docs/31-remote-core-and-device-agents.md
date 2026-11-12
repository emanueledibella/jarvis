# Core remoto e agenti sui dispositivi: analisi originaria e decisioni

Aggiornamento del 3 novembre 2026: lo sviluppo è stato successivamente autorizzato.
Il [capitolo 32](32-remote-implementation.md) raccoglie implementazione, verifiche
e limiti effettivi; questo capitolo conserva l'analisi originaria.

## Stato attuale al 3 novembre

Il core remoto, Electron macOS/Windows, Capacitor iOS/Android, esecutore WSS,
configurazione amministrativa, parser isolato e backup age sono implementati.
L'abbinamento usa codici monouso e token ruotati; la proposta OAuth/OIDC per
l'identità dei dispositivi non è l'implementazione scelta. L'OAuth delle
integrazioni resta distinto. SQLite e scheduler hanno una sola autorità.

L'esecutore supporta workspace/comandi concessi e, su Mac, EventKit e scelta
locale di una finestra. Non comprende Hue Bluetooth, controllo generale di
mouse/tastiera, inferenza locale delegata o un core offline sincronizzato.
Mac spento significa capacità locali indisponibili, non arresto del core remoto.

Le build locali macOS, Android debug e iOS simulatore e le prove Linux sono
registrate nel capitolo 32. Builder Windows, dispositivi fisici, firma,
credenziali push/OAuth reali e deploy pubblico hanno limiti espliciti. La
[matrice corrente](33-current-state-and-verification.md) raccoglie le verifiche
rieseguite e i manuali di [deploy](../deploy/README.md) e
[companion](../companions/README.md) spiegano l'avvio.

## Analisi storica del 2 novembre

I paragrafi seguenti conservano alternative, requisiti e contratti **prima
dello sviluppo**; le espressioni «da sviluppare», «proposto» e «da discutere»
si riferiscono a quel momento. Per API e istruzioni correnti usare i capitoli
03, 12, 29, 32 e 33.

Analisi del 2 novembre 2026. Stato in quella data: proposta architetturale, senza implementazione. Integra l'[analisi di dimensionamento](30-cloud-deployment-feasibility.md) e rivede l'ordine suggerito nel [documento companion](28-companion-architecture.md) alla luce del requisito di disponibilità indipendente dal Mac. Il proprietario ha confermato il supporto a iPhone e Android e la priorità del core remoto; la modalità autonoma sul Mac è rinviata a una fase successiva.

## Obiettivo e raccomandazione

Il requisito prioritario è parlare con Jarvis dal telefono anche quando il Mac è spento, mantenendo la possibilità di comandare dal telefono operazioni su un Mac disponibile, senza un collegamento diretto telefono–Mac. Si vuole inoltre configurare il modello e le proprie API key dalle app.

**Raccomandazione: un core Jarvis sempre attivo, app companion e un agente esecutore sul Mac, con una connessione avviata dal Mac verso il core.** Le app desktop e mobile possono avere interfacce diverse; condividono conversazioni, attività, configurazione e autorizzazioni del medesimo assistente. Una modalità autonoma desktop può restare un'opzione separata, riutilizzando lo stesso motore.

Non è necessario scegliere fra un assistente solo cloud e un assistente capace di agire sul computer. Il coordinamento può essere centrale e l'esecuzione distribuita. Rimane un limite fisico: operare sulle risorse di uno specifico Mac richiede quel Mac acceso e connesso, con permessi validi e capacità disponibili.

## Quattro ruoli distinti

| Ruolo | Responsabilità proposta |
| --- | --- |
| App companion | Interfaccia, microfono e riproduzione sul dispositivo, allegati scelti, notifiche, approvazioni, impostazioni autorizzate. |
| Core o harness | Conversazioni, scelta del modello, ciclo agente/strumenti, memoria, permessi, attività, pianificazioni, budget e instradamento degli esecutori. |
| Modello | Inferenza tramite il provider configurato; può essere esterno via API oppure locale a un esecutore disponibile, con una politica esplicita. |
| Agente del dispositivo | Accesso alle capacità autorizzate di quel dispositivo: workspace, comandi, calendario Apple, schermata selezionata e altri adattatori locali. |

Usare un modello remoto non sposta automaticamente il core dal Mac al server. Analogamente, spostare il core sul server non sposta sul server i file, il microfono o i permessi macOS.

Il confronto con gli altri prodotti va fatto su questi ruoli. La [documentazione Codex CLI](https://learn.chatgpt.com/docs/codex/cli) descrive lavoro sul repository e strumenti locali. La documentazione OpenAI degli [esecutori self-hosted](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted) descrive invece un harness remoto con un esecutore nell'ambiente dell'utente, con connessioni WebSocket in uscita. È un riferimento per il modello di connessione; non dimostra che quell'esecutore sostituisca già gli adattatori macOS di Jarvis o che ogni funzionalità sia disponibile sul proprio account.

## Confronto delle alternative

| Alternativa | Telefono utilizzabile a Mac spento | Operazioni sul Mac dal telefono | Conseguenze |
| --- | --- | --- | --- |
| Core sul Mac e companion mobile | No, per le operazioni del core. | Quando il Mac è disponibile. | Minore infrastruttura iniziale, ma non soddisfa la disponibilità richiesta. |
| Due app autonome che chiamano il modello | Sì, per le richieste eseguite dal telefono. | Richiedono comunque un collegamento o un servizio intermediario. | Configurazioni e stati distinti; continuità, sincronizzazione e automazioni distribuite sono ulteriore lavoro. |
| Core centrale e agente Mac | Sì, per capacità e dipendenze disponibili al server. | Sì, tramite il core, quando l'agente è disponibile. | Una fonte autorevole per attività e permessi; vanno sviluppati gateway, identità dei dispositivi e dispatch remoto affidabile. |
| Harness gestito da un fornitore e propri client/esecutori | Dipende dal servizio scelto. | Dipende da esecutore, piattaforme e permessi supportati. | Riduce parte delle operazioni infrastrutturali, ma richiede verifiche di integrazione e può vincolare modelli, contratti e migrazione. |

Due app autonome sono una scelta valida per due assistenti personali separati, o per chat in primo piano con le proprie chiavi. Non assicurano automaticamente una sola cronologia, un solo scheduler o l'esecuzione continuativa di attività quando entrambe le app non sono attive. I sistemi mobili concedono tempi e modalità di esecuzione in background controllati dal sistema operativo: non sono equivalenti a un servizio sempre acceso. I promemoria locali del sistema operativo possono invece funzionare anche senza tenere attivo un agente AI. Fonte: [strategie background Apple](https://developer.apple.com/documentation/BackgroundTasks/choosing-background-strategies-for-your-app).

Per comandare il Mac senza collegamento diretto dal telefono serve comunque un intermediario raggiungibile. Usare un servizio gestito al posto di una VM cambia chi lo amministra; non elimina quella funzione architetturale.

Un piccolo server domestico/NAS sempre acceso è un'altra sede possibile del core. Riduce alcune dipendenze dalla rete domestica per Home Assistant, ma dipende dall'alimentazione e dalla connettività di casa. Una VM esterna è più indipendente dal portatile e dalla rete domestica. Il core e i client dovrebbero dipendere dallo stesso contratto, indipendentemente dalla sede del server.

## Come si lavora dal telefono sul Mac

Flusso proposto per «esegui i test del progetto sul mio Mac e dimmi il risultato»:

1. Il telefono invia la richiesta al core e ottiene l'identità dell'attività.
2. Il core consulta contesto e capacità disponibili, individua Mac e workspace autorizzati e prepara l'operazione.
3. Se necessaria, l'app mostra l'approvazione degli argomenti e della destinazione esatti. L'approvazione viene verificata dal server.
4. Il core consegna il lavoro sul canale aperto dall'agente Mac. Non apre una connessione dal telefono al Mac.
5. L'agente verifica nuovamente identità, grant, scadenza, workspace e vincoli locali; esegue il comando e conserva lo stato necessario alla riconciliazione.
6. L'esito ritorna al core, che prosegue l'attività e lo rende disponibile sulle app. Il telefono può chiudere la schermata dopo l'accettazione del lavoro; la consegna della notifica dipende anche dal servizio push e dallo stato del dispositivo.

Il Mac apre una connessione autenticata TLS verso il server, per esempio WebSocket su porta 443, con riconnessione e ripresa del protocollo. Non servono porte pubbliche sul Mac né presenza nella stessa rete del telefono. Sono comunque necessari rete in uscita e server raggiungibile. Il protocollo remoto di Jarvis è da sviluppare: l'attuale polling locale non è già questo collegamento.

App desktop e agente possono essere distribuiti nello stesso pacchetto ma avere cicli di vita separati. Chiudere la finestra non dovrebbe obbligatoriamente interrompere l'agente autorizzato. Sospensione del Mac, logout, riavvio e permessi OS possono rendere indisponibili alcune o tutte le capacità: lo stato va rilevato per capacità, non dedotto dal solo processo connesso.

I lavori del Mac non devono bloccare altre conversazioni: mentre un test gira sul Mac, il server può gestire una richiesta diversa, rispettando i limiti di concorrenza. Sulla stessa cartella servono lock o controlli di versione per evitare modifiche concorrenti incompatibili.

Un esecutore tipizzato è sufficiente come prima versione. Un secondo agente AI autonomo sul Mac, a cui delegare interi obiettivi, aggiunge coordinamento, contesto, credenziali e budget: può essere valutato dopo. Gli adattatori locali possono riutilizzare MCP dove utile, ma MCP da solo non fornisce pianificazione, coda durevole e riconciliazione degli effetti distribuiti.

## Comportamento con dispositivi assenti e interruzioni

| Situazione | Comportamento desiderato |
| --- | --- |
| Mac spento; domanda generale, posta o Jira | Il server prosegue se modello e servizi necessari sono disponibili. |
| Mac spento; richiesta sui file del suo disco | Indicare l'indisponibilità. Offrire un'attesa esplicita con scadenza, senza fingere accesso ai file. |
| Telefono chiuso dopo richiesta accettata | L'attività del core continua; risultato persistente e notifica quando possibile. |
| Mac disconnesso prima di accettare il lavoro | Il lavoro resta non eseguito/in attesa e può scadere; nessun successo inventato. |
| Mac disconnesso dopo un possibile effetto | Riconciliare con il registro locale. Non rieseguire alla cieca operazioni dall'esito sconosciuto. |
| Server riavviato | Recuperare stato e checkpoint; riprendere solo dove la politica di sicurezza lo permette. Le attività private non devono acquisire una persistenza inattesa. |
| Provider modello non disponibile | Errore o attesa controllata; niente trasferimento implicito dei dati a un provider diverso. |
| Server non disponibile | I client centrali non eseguono nuove attività del core. L'eventuale modalità autonoma desktop è distinta ed esplicita. |

La coda deve conservare identità, destinazione, versione degli argomenti, scadenza, stato di consegna ed esito. Occorrono identità stabili anche dopo una riconnessione. Doppia consegna o doppia pressione del pulsante non devono produrre un secondo effetto. Non si può promettere genericamente esecuzione «exactly once» di ogni comando o API esterna: un esito incerto va reso visibile e riconciliato.

Un lavoro rimasto in attesa non va eseguito ore dopo con approvazione o file superati. L'accodamento delle operazioni Mac non è un'impostazione da abilitare implicitamente per tutto. Il risveglio remoto del Mac è una capacità ulteriore, non una garanzia di questa architettura.

Se si vuole lavorare sul codice anche a Mac spento, si può predisporre un clone del repository in un ambiente server separato, produrre un branch/patch e sincronizzarlo successivamente. È un'altra destinazione di esecuzione, con propri costi e isolamento; non equivale ad aver modificato i file del Mac spento.

## Modelli, API key e impostazioni dalle app

La configurazione può essere disponibile sia nell'app Mac sia nella companion. Nella modalità centrale entrambe amministrano **la configurazione del server**. Il telefono non deve possedere permanentemente tutte le chiavi per visualizzare le impostazioni o usare Jarvis.

Proposta:

- Provider, modello, endpoint, parametri, limiti e budget sono profili centrali autorizzati dal proprietario. Si può iniziare con un profilo predefinito, lasciando eventuali scelte per conversazione a un passaggio successivo.
- L'app autenticata invia una nuova chiave al server attraverso il canale protetto. Successivamente mostra soltanto stato/configurazione mascherata; permette sostituzione e revoca, non il download ordinario del segreto.
- Le chiavi sono gestite sul server, protette a riposo e nei backup, separate da log e artefatti. Il server che le usa resta un soggetto fidato: la cifratura a riposo non lo rende incapace di utilizzarle o leggerle durante l'esecuzione.
- Ogni dispositivo possiede credenziali proprie per Jarvis, revocabili singolarmente. Non riceve la stessa chiave amministrativa di tutti gli altri client. Il token del dispositivo è distinto dalle API key dei modelli.
- Una chiave va associata al provider/endpoint autorizzato. Cambiare endpoint non deve trasferire implicitamente un vecchio segreto al nuovo destinatario.
- Ogni attività conserva una versione esplicita del profilo scelto. La modifica delle impostazioni governa i lavori nuovi; i lavori in corso non cambiano provider silenziosamente e una revoca deve avere un comportamento definito.

Questa impostazione segue anche la [raccomandazione OpenAI di mantenere le chiavi applicative sul server](https://developers.openai.com/api/reference/overview#authentication). Per un'app standalone con una chiave inserita direttamente dal suo unico proprietario si può progettare un deposito locale protetto; è però un'altra modalità, con gestione e rischi differenti da una companion centrale. Non va inserita una chiave condivisa nel pacchetto dell'app.

**Modello ed esecutore sono scelte indipendenti.** Un modello via API può decidere un'operazione eseguita sul Mac. Viceversa, se si sceglie un modello locale sul Mac, le richieste che lo richiedono dipendono dalla sua disponibilità. Per il requisito «Jarvis disponibile a Mac spento» il modello predefinito del core deve essere raggiungibile senza il Mac. Una richiesta esplicitamente privata/locale non può passare al cloud come fallback non autorizzato.

La voce della companion comprende acquisizione e riproduzione sul telefono, con elaborazione del dialogo coordinata dal core. Trasporto audio e provider vocale sono un contratto separato dal modello testuale. Microfono, mute e privacy non devono essere un interruttore globale condiviso involontariamente fra dispositivi.

## Confini di sicurezza essenziali

Il core propone e autorizza secondo la propria policy; l'agente applica comunque i vincoli locali. Il semplice possesso di una connessione autenticata non autorizza ogni comando sul computer.

L'abbinamento iniziale deve registrare un dispositivo preciso, grant revocabili e capacità consentite. Sul Mac restano da concedere i permessi richiesti da macOS. Dopo quel setup, un'operazione compatibile con i grant può essere richiesta e approvata dal telefono senza un'ulteriore presenza davanti al Mac, quando la policy e lo stato OS lo consentono. Il server non aggira consenso OS, blocco schermo o limiti delle API native.

Le operazioni devono legare proprietario, dispositivo, workspace, capacità, argomenti, scadenza e approvazione. File/cartelle autorizzati non sono un accesso generico al disco; schermata scelta non è accesso indiscriminato a tutte le finestre. Il controllo generale di mouse e tastiera è una capacità ulteriore rispetto alle integrazioni attuali e non è incluso automaticamente nel primo agente remoto.

Richieste, risultati e file letti su Mac possono attraversare il server e il modello API: vanno minimizzati e governati da scope/privacy espliciti. Per dati che non devono lasciare il Mac serve un percorso locale distinto, con disponibilità conseguentemente legata al Mac.

Gateway companion e canale esecutori devono avere identità e permessi distinti. Per client nativi OAuth/OIDC con browser esterno e PKCE è una base standard, da realizzare con componenti supportati; riferimento: [RFC 8252](https://www.rfc-editor.org/rfc/rfc8252.html). Una VPN può aggiungere protezione di rete ma non sostituisce questi controlli. Push e deep link notificano; l'esecuzione richiede sempre una decisione valida sul server, non il solo testo della notifica.

## Cosa riutilizzare e cosa cambiare nel Jarvis attuale

| Evidenza nel codice | Riutilizzo e conseguenza |
| --- | --- |
| `TaskManager.model` e `TaskManager.graph` | Provider cloud e motore agente sono già presenti. Il motore può restare comune alle modalità server e standalone. |
| `Gateway`, approvazioni e registro `effects` | Base utile per policy e stati incerti; identità del dispositivo e destinazione dell'effetto devono entrare nei contratti e nei controlli. |
| SQLite, checkpoint e scheduler | Possono restare sul singolo core per uso personale. Occorre una sola autorità; non condividere il database attivo con gli agenti e non duplicare scheduler. |
| `build_tools` costruisce un `Workspace` dal filesystem del servizio | Sul server opererebbe sui file del server. Serve dispatch esplicito verso workspace/esecutori, mantenendo autorizzazioni e risultati verificabili. |
| `NativeBridge` mantiene stato unico e future in RAM con timeout | Riutilizzabili adattatori e logica locale; il bridge non è un protocollo durevole per molteplici dispositivi e disconnessioni lunghe. |
| `Runtime.voice_session`, `owner_write` e `/api/chat` | Scope/privacy sono in parte legati a stato globale. Vanno separati per sessione/conversazione e dispositivo; un telefono non deve modificare involontariamente la sessione dell'altro client. |
| API con bearer locale, Host/Origin loopback e prova di servizio locale | Servono una superficie remota e autenticazione dedicate. Pubblicare la porta locale non soddisfa il requisito. |
| Launcher AppKit/WebKit | Oggi avvia/verifica il servizio locale. Servono modalità companion remota e ciclo di vita dell'agente indipendente dalla finestra. |
| Impostazioni modello e segreti mascherati | Interfaccia concettualmente riutilizzabile; il server richiede autorizzazione amministrativa, deposito segreti e flussi OAuth appropriati al nuovo host. |

Punti di riscontro: `Runtime` e `set_voice_session`; `TaskManager.model/graph`; `Gateway.invoke/decide`; `build_tools`; `NativeBridge.invoke`; route settings/chat/native; validazione API e servizio di fiducia frontend. L'analisi ha letto questi contratti; non ha modificato o collaudato un protocollo remoto inesistente.

## Perimetro iniziale e sequenza proposta

1. **Core server e client web:** un proprietario, modello via API configurabile dall'interfaccia autenticata, conversazioni/attività, stati persistenti, sicurezza gateway e setup dei servizi indipendenti dal Mac. Una sola VM e un servizio modulare; database e coda possono restare locali al core senza aggiungere inizialmente una piattaforma distribuita.
2. **Agente Mac remoto:** abbinamento, grant e revoca; capacità e disponibilità; lettura di un workspace autorizzato; successivamente scritture e comandi approvati, registro locale degli esiti, riconnessione e scadenze. Percorso completo telefono/browser → core → Mac → core → client.
3. **Companion iPhone, Android e desktop:** login, chat e continuazione delle attività, impostazioni modello, approvazioni, voce esplicita, push, condivisione di fonti e stato dei dispositivi. Il contratto API e la logica condivisa devono supportare entrambe le piattaforme mobili; framework, integrazioni native e distribuzione restano da valutare. Audio, notifiche, autenticazione e conservazione delle credenziali richiedono verifica su dispositivi reali di entrambe le piattaforme.
4. **Estensioni facoltative:** esecutori server isolati per lavoro a Mac spento, modello locale sul Mac, modalità autonoma desktop e delega di obiettivi completi ad agenti locali.

Le prime versioni non richiedono un harness completo anche nel telefono. La priorità confermata è il core remoto: l'uso autonomo del Mac quando server o Internet sono indisponibili non è un requisito della prima consegna. Per quella modalità successiva è preferibile lo stesso motore con configurazione locale, con passaggio esplicito e confini di sincronizzazione. Due scheduler indipendenti non devono assumere la proprietà della stessa routine. Non serve che la prima consegna comprenda failover automatico o sincronizzazione bidirezionale di ogni dato.

Second Brain deve essere disponibile al core anche a Mac spento; i suoi modelli e dati hanno un ciclo di vita distinto. Home Assistant richiede un percorso di rete sempre disponibile oppure un connettore domestico su un host sempre acceso: affidare quel collegamento al solo Mac riproporrebbe la dipendenza che si vuole eliminare.

Il lavoro pesante svolto sul Mac non impone necessariamente una VM più grande: il server coordina, il Mac usa la propria CPU. Al contrario, compilazioni/browser e documenti pesanti eseguiti sul server richiedono un dimensionamento distinto e isolamento dai segreti del core. Le prove e le ipotesi economiche precedenti restano riferite al solo Jarvis leggero, non a un'intera piattaforma di esecuzione del codice.

## Verifiche necessarie prima di considerare il sistema pronto

- Richiesta e risultato dal telefono con Mac spento, inclusi i servizi realmente necessari a memoria e integrazioni.
- Richiesta su Mac, chiusura dell'app mobile, avanzamento e consultazione dell'esito da un altro client.
- Disconnessione prima/dopo l'effetto, riavvio di server/agente, doppia consegna, scadenza e cancellazione senza replay pericoloso.
- Revoca di telefono/Mac, pairing non riproducibile, tentativo di usare una capacità o un workspace non concessi.
- Due conversazioni concorrenti con scope e privacy differenti, senza interferenze di audio, allegati, approvazioni o memoria.
- Modifica/revoca delle credenziali del provider, nuovo endpoint e task già avviati; assenza di segreti nei risultati o log.
- Permessi macOS mancanti, Mac bloccato/in riposo e capacità GUI indisponibili, senza promesse false di esecuzione.
- Backup/ripristino coerente, un solo scheduler autorevole e notifiche provate su dispositivi reali.

## Decisioni da discutere

Sono confermati il supporto a iPhone e Android e la priorità del core remoto rispetto alla modalità autonoma desktop. La scelta architetturale proposta è core remoto + companion + esecutore Mac. Restano da discutere il primo insieme di operazioni Mac, la politica di attesa/approvazione dei lavori quando il dispositivo non è disponibile e le scelte di implementazione dei client. Questo documento non autorizza né descrive uno sviluppo già eseguito.
