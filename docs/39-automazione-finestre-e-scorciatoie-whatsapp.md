# Automazione finestre e scorciatoie WhatsApp (Apple Shortcuts)

Documento di riferimento per l'estensione del controllo finestre su desktop e l'automazione dell'invio messaggi WhatsApp tramite Apple Shortcuts ed Esecutore Desktop.

---

## 1. Contesto e Modello di Sicurezza

L'automazione dell'interfaccia grafica e l'invio di messaggi verso l'esterno sono soggette alle regole di sicurezza e isolamento di Jarvis:

1. **Autorizzazione Preventiva Obbligatoria (Gateway & Policy):**
   - I tool di controllo finestre (`device_window_focus`, `device_window_action`) hanno rischio `command`.
   - Il tool di invio WhatsApp (`whatsapp_send_message`) ha rischio `external`.
   - Prima di qualsiasi esecuzione, il Core remoto solleva un `interrupt()` di LangGraph e registra la richiesta nella tabella `approvals` legata all'hash immutabile dei parametri (destinatario, numero normalizzato e testo esatto). L'azione viene eseguita solo dopo che l'utente ha premuto **[Approva questa azione]** nella companion o ha confermato a voce.
2. **Confini di Piattaforma:**
   - **PC Desktop (macOS / Windows):** L'Esecutore Desktop dispone dei permessi per elencare finestre aperte, portare in primo piano applicazioni, nascondere, terminare o lanciare URL e applicazioni.
   - **Dispositivi Mobili (iOS / iPhone):** A causa della sandbox di sistema, un'applicazione di terze parti non può iniettare eventi di tocco o digitazione dentro altre app. L'invio autonomo senza clic manuali su WhatsApp è reso possibile grazie all'integrazione con **Apple Shortcuts (Comandi Rapidi)** e il framework di sistema **SiriKit**.
   - **Dispositivi Mobili (Android):** Supporta deep-link nativi e Intent; l'automazione completa dell'interfaccia richiederebbe un `AccessibilityService` invasivo, rendendo il deep-link o il gateway la scelta più stabile.

---

## 2. Guida: Configurazione della Scorciatoia `JarvisWhatsApp` su Apple (iOS e macOS)

Questa procedura consente a Jarvis di **inviare messaggi WhatsApp al 100% in automatico in background**, senza che l'utente debba aprire la chat di WhatsApp o toccare il pulsante verde di invio.

La scorciatoia è nativa dell'ecosistema Apple e, se sincronizzata con iCloud, funziona sia su **iPhone** che su **iPad** e **Mac**.

### Procedura passo-passo (2 minuti):

1. **Crea il comando rapido:**
   - Apri l'app **Comandi Rapidi (Shortcuts)** sul tuo iPhone (o sul Mac).
   - Tocca o clicca il pulsante **`+`** (in alto a destra) per creare un nuovo comando.
   - Rinomina il comando esattamente in: **`JarvisWhatsApp`** *(rispetta maiuscole e minuscole)*.

2. **Aggiungi le azioni in sequenza:**

   * **Azione 1: Ricezione input**
     - Cerca e aggiungi: **"Ottieni testo da input della scorciatoia"** (*Get text from Shortcut Input*).
   
   * **Azione 2: Divisione del testo**
     - Cerca e aggiungi: **"Dividi testo"** (*Split Text*).
     - Nel campo "Separatore", seleziona **"Personalizzato"** e inserisci esattamente tre due punti: `:::`
   
   * **Azione 3: Estrazione del destinatario**
     - Cerca e aggiungi: **"Ottieni elemento dall'elenco"** (*Get Item from List*).
     - Lascia impostato su **"Primo elemento"** (questo rappresenterà il numero di telefono).
   
   * **Azione 4: Estrazione del messaggio**
     - Cerca e aggiungi nuovamente: **"Ottieni elemento dall'elenco"** (*Get Item from List*).
     - Tocca "Primo elemento" e cambialo in **"Ultimo elemento"** (questo rappresenterà il testo del messaggio).
   
   * **Azione 5: Invio tramite WhatsApp**
     - Cerca **"WhatsApp"** e aggiungi l'azione nativa: **"Invia messaggio con WhatsApp"** (*Send Message via WhatsApp*).
     - Configura i parametri:
       - Nel campo **Messaggio**: inserisci la variabile `[Ultimo elemento]`.
       - Nel campo **Destinatari**: inserisci la variabile `[Primo elemento]`.
     - **👉 PASSAGGIO FONDAMENTALE:** Tocca la freccetta `>` (espandi dettagli) accanto all'azione di WhatsApp e **DISATTIVA l'interruttore "Mostra durante l'esecuzione"** (*Show When Run → OFF*).

3. **Salva:**
   - Premi **Fine** in alto a destra.

---

## 3. Protocollo di Chiamata di Jarvis

Quando l'utente richiede l'invio di un messaggio WhatsApp (es. *"Manda un messaggio a Mario: sto arrivando"*):

1. **Validazione e Normalizzazione:**
   Il tool [`whatsapp_send_message`](../src/jarvis/tools.py) verifica che messaggio e destinatario non siano vuoti e ripulisce il numero di telefono nel formato internazionale standard (senza spazi, trattini o prefissi `00`).
2. **Generazione dei Link di Esecuzione:**
   Il tool genera tre canali pronti all'uso:
   - **`shortcut_link`**:
     ```
     shortcuts://run-shortcut?name=JarvisWhatsApp&input=text&text=<NUMERO>:::<MESSAGGIO>
     ```
     Utilizzato su iOS/macOS per l'invio autonomo silenzioso.
   - **`deep_link`**:
     ```
     whatsapp://send?phone=<NUMERO>&text=<MESSAGGIO>
     ```
     Utilizzato come fallback nativo su mobile (apre la chat con testo precompilato).
   - **`web_link`**:
     ```
     https://wa.me/<NUMERO>?text=<MESSAGGIO>
     ```
     Utilizzabile da qualsiasi browser web.
3. **Dispatch Automatico Diretto su Esecutore Desktop (Zero Clic):**
   - Il tool ricerca automaticamente gli esecutori Mac connessi nello scope dell'utente (`runtime.remote.jobs.devices`).
   - Se un esecutore macOS con capacità `window.action` è connesso (ad es. il Mac dell'utente con `Jarvis Companion`), Jarvis inoltra direttamente il comando di esecuzione della scorciatoia Apple:
     ```json
     {"action": "open_url", "url": shortcut_link}
     ```
   - L'esecutore locale sul Mac riceve il comando ed esegue `NSWorkspace.shared.open(...)` per lanciare la scorciatoia `JarvisWhatsApp`.
   - Se l'opzione "Mostra durante l'esecuzione" della scorciatoia è disattivata, **il messaggio WhatsApp viene inviato immediatamente in background in modo 100% automatico, senza alcun pop-up o clic manuale**.
   - Jarvis conferma all'utente che il messaggio è stato inviato con successo, senza mostrare link di azione.
   - Solo se nessun esecutore desktop è attivo o connesso (ad es. uso standalone da iPhone con Mac spento), Jarvis genera i link pronti con un tocco come fallback.

---

## 4. Controllo Finestre Desktop: Tool e Capacità Native

Su computer con Esecutore Desktop (macOS tramite [`WindowBridge.swift`](../native/WindowBridge.swift) integrato nel binario `JarvisNativeHelper`, e Windows tramite chiamate Win32 in [`executor.py`](../src/jarvis/executor.py)), sono disponibili i seguenti tool:

### `device_windows_list`
- **Rischio:** `read` (nessun effetto collaterale).
- **Ritorna:** Elenco delle applicazioni utente attive (`apps`), l'applicazione correntemente in primo piano (`frontmost`), e l'elenco delle finestre a schermo con coordinate e dimensioni (`windows`).

### `device_window_focus`
- **Rischio:** `command` (richiede approvazione).
- **Argomenti:** `device_id`, `app_name`, `window_id` (opzionale).
- **Azione:** Riporta in primo piano l'applicazione specificata (avviandola se necessario) e toglie lo stato di minimizzazione/nascondimento.

### `device_window_action`
- **Rischio:** `command` (richiede approvazione).
- **Argomenti:** `device_id`, `action`, `app_name` (opzionale), `url` (opzionale), `window_id` (opzionale).
- **Azioni supportate:**
  - `focus`: porta in primo piano.
  - `hide`: nasconde l'applicazione.
  - `unhide`: ripristina l'applicazione nascosta.
  - `launch`: avvia una nuova istanza dell'app.
  - `close`: termina o chiude l'app/finestra.
  - `open_url`: apre URL, protocolli personalizzati (`whatsapp://`, `shortcuts://`) e deep link.
