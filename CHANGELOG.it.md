# Changelog

[English](CHANGELOG.md) · **Italiano**

Formato basato su [Keep a Changelog](https://keepachangelog.com/it-IT/1.1.0/);
le versioni seguono il [Semantic Versioning](https://semver.org/lang/it/).

## [1.7.0] - 2026-11-04

### Aggiunto
- **Scansione della cartella molto più intelligente.** Oltre a npm, node e script Python ora riconosce: il **wrapper Maven/Gradle** del progetto (`mvnw`, `gradlew`; `mvnw.cmd` su Windows) prima di un `mvn` globale; i progetti **Spring** con i profili di sviluppo (`dev`, più `swagger` per JHipster); le app **FastAPI/Flask** (`python -m uvicorn modulo:app --app-dir src`), anche nello stile `app = create_app()`; i pacchetti con `__main__.py` (`python -m nome`); i comandi di avvio del **Makefile** (`start`, `run`, `dev`, `serve`, `avvia`...); e usa l'**ambiente virtuale** del progetto (`.venv`, `venv`).
- **Il Java giusto.** Legge la versione di Java richiesta dal progetto (pom.xml, Gradle, `.java-version`, o le informazioni di compilazione dentro il `.jar`/`.war`), cerca i Java installati dove ogni sistema li tiene (JAVA_HOME, PATH, `~/.jdks`, SDKMAN, `/usr/lib/jvm`, Program Files, Adoptium, Corretto, Zulu, macOS...) e avvia il programma con il `JAVA_HOME` giusto. Se esiste solo un Java più nuovo lo dice; se non ne esiste nessuno ti dice di installarlo.
- I comandi il cui strumento non è installato sul computer vanno in fondo, sono segnati e non vengono mai provati in automatico.
- Quando un progetto usa servizi Docker (un database...), la guida mostra il comando per avviarli prima (`docker compose up -d`) e non avvia il programma da sola; non avvia mai i servizi.

### Corretto
- Programmi come `java`, `npm`, `mvnw` o `make` venivano passati a pm2 come se fossero file JavaScript e fallivano. Ora girano come programmi.
- Su Windows i file `.cmd`/`.bat`, `npm` e `mvn` partono tramite `cmd /c` (scritto in base al comportamento documentato di pm2, non provato su Windows).

## [1.6.0] - 2026-11-04

### Aggiunto
- **Avvia il programma da solo.** Appena scegli la cartella, il monitor la scansiona, prova i comandi probabili uno dopo l'altro finché uno resta acceso, e lo tiene in esecuzione sotto pm2. Un nome già in uso riceve un numero. Se niente funziona vedi ogni comando provato con il suo log, e puoi sceglierne o scriverne uno tu.

## [1.5.0] - 2026-11-04

### Aggiunto
- **Cartella di ogni processo.** Una colonna "cartella" mostra dove gira un processo (la parte finale del percorso resta sempre visibile). Un clic apre la cartella nel gestore dei file del sistema: è il monitor a chiederlo al sistema, perché una pagina web non può, e apre solo la cartella di un processo che conosce, mai un percorso arrivato da una richiesta. Un piccolo pulsante copia il percorso. Su Linux serve `xdg-open` (pacchetto `xdg-utils`); macOS usa `open` e Windows Esplora risorse (è stato provato solo Linux).
- **Configurazione guidata riscritta per chi parte da zero (passo 3).** Dice chiaramente che stai aggiungendo UN programma (un sito, un'API...) da tenere acceso; guarda nella cartella e propone tutti i modi trovati per avviarlo (npm, node, Python, Django, archivi Java, Maven, Gradle, script di avvio) come scelte da selezionare invece di una casella vuota; e dice cosa sta per fare ("Eseguirò ... nella cartella ... e lo chiamerò ...") prima del pulsante Avvia. Gestiti i nomi di file con spazi.
- **Riquadro "La prossima volta"** dopo l'avvio del primo programma: come riaprire il monitor (il file da cliccare due volte, o il comando da scrivere, e l'indirizzo).
- **Scegli le colonne:** Impostazioni > Colonne nasconde quelle che non ti servono (con memoria).

## [1.4.0] - 2026-11-04

### Aggiunto
- **Colonna del tipo (backend / frontend / i tuoi).** Il tipo viene indovinato da ciò che il processo esegue (un programma `java` o un progetto Express è un backend; un progetto `react-scripts`, `vite` o Angular è un frontend) e mostrato come "auto: …" finché non ne scegli uno. Cambialo dalla colonna, oppure scegli "+ nuovo tipo…" per crearne uno tuo (database, worker, ...).
- **Etichette.** Quante etichette colorate vuoi per ogni processo, mostrate accanto al nome. Assegnale o creale dal pulsante "+", rinominale, cambiane il colore o eliminale (insieme ai tuoi tipi) in "Tipi ed etichette…" (menu Impostazioni, o la barra sopra l'elenco), e **filtra l'elenco** per tipo e per etichette.

### Modificato
- I menu a tendina restano sempre dentro lo schermo, ovunque sia il loro pulsante: si allineano al bordo sinistro del pulsante se è sul lato sinistro, e si aprono verso l'alto quando sotto c'è poco spazio.

## [1.3.0] - 2026-10-30

### Aggiunto
- **Notifiche per dominio.** Un controllo in background ti avvisa quando un'app va in errore, si ferma, viene rimossa, si riavvia da sola o usa troppa memoria, quando un demone si ferma o torna, e quando finisce un avvio / arresto di un intero dominio. Ogni dominio (e i processi senza dominio) sceglie quali gravità (errori, avvisi, buone notizie) e quali tipi di evento vuole, un limite di memoria facoltativo, e come essere avvisato: il menu della campanella (gli avvisi stanno lì, mai come popup sopra la pagina; la campanella si scuote e mostra un contatore), notifiche del browser, un suono, e notifiche del sistema operativo che funzionano anche a pagina chiusa. Una campanella nella testata apre storico e impostazioni; i cambiamenti fatti dal monitor stesso non vengono segnalati come sorprese, e un'app che si riavvia in continuazione produce un solo avviso al minuto.
- La lingua dell'interfaccia è ricordata dal server, così anche le notifiche del desktop parlano la stessa lingua.
- I log si possono mostrare a destra o sotto l'elenco (pulsante nella testata dei log, ricordato).
- Le finestre aperte da dentro un'altra (aiuto, notifiche) ora si sovrappongono con un link "Torna a: …", invece di chiuderla: la configurazione guidata mantiene il suo passo e le impostazioni del dominio mantengono quello che hai scritto.
- **Spegnere pm2 monitor** dalla pagina (pulsante di accensione nella testata) o con `python3 server.py --stop`. Le tue app continuano a funzionare sotto pm2.
- **Lanciatori con doppio clic per ogni sistema:** `Start pm2-monitor.bat` (Windows), `Start pm2-monitor.command` (macOS) e `start-pm2-monitor.sh` (Linux) eseguono tutti `launch.py`, che avvia il monitor staccato (senza finestra di console, log nella cartella di configurazione), riconosce quando è già acceso o quando la porta è occupata, e apre il browser. `launch.py --stop` lo spegne; `launch.py --install-shortcut` lo aggiunge al menu delle applicazioni di Linux.
- **Due log affiancati** (⧉ in un pannello dei log, al massimo due) e **log ridimensionabili**: trascina la barra tra l'elenco e i log e quella tra i due log; le misure vengono ricordate, il doppio clic le ripristina.
- **Una testata più ordinata:** azioni raggruppate, indicatori di stato per ogni demone, un menu "Impostazioni" (ingranaggio) con dimensione e lingua, etichette che diventano icone nelle finestre strette.
- **Link alle app in esecuzione:** una colonna "link" mostra l'indirizzo su cui risponde ogni app (`localhost:3000`, ...), cliccabile, anche per il programma che un'app avvia (il server dietro `npm start`). Sono elencate solo le porte che rispondono come una pagina web: pm2 monitor invia una richiesta `HEAD /` innocua (user agent `pm2-monitor-link-check`) a ogni porta in ascolto, una volta per processo, così database e porte interne non diventano link morti. Il controllo si può disattivare nelle Impostazioni, e allora vengono elencate tutte le porte in ascolto. Linux legge `/proc`; macOS usa `lsof` e Windows `netstat` (solo Linux è stato provato).
- **Comprimere ed espandere** i gruppi dell'elenco (con memoria; "Comprimi tutto" / "Espandi tutto"); un gruppo compresso mostra comunque quanti dei suoi processi sono online.
- **Sfoglia per scegliere la cartella di pm2** invece di scriverne il percorso, nella finestra dei demoni e nella configurazione guidata: il selettore può mostrare le cartelle nascoste, segna quelle che sono cartelle dati di pm2, le propone come posti rapidi e accetta solo una vera cartella di pm2.
- **Dimensione del testo dentro i log** (A− / A+ nella barra dei log), separata dallo zoom di tutta la pagina.
- **Filtri dei log:** ricerca (senza distinguere maiuscole, con le parole evidenziate), pulsanti di livello ERROR / WARN / INFO / DEBUG con i colori (gli stack trace restano con il loro errore), 0 / ±2 / ±5 righe di contesto attorno a ogni risultato, scelta di 200 / 400 / 1000 / 2000 righe, unione delle righe ripetute con un contatore (orari ignorati), e Copia / Salva di esattamente le righe visibili.
- Pulsanti nel pannello dei log per andare alla prima riga e all'ultima (che riprende anche a seguire le nuove righe).

### Modificato
- **Le notifiche si aprono come menu a tendina sotto la campanella** invece che in una finestra modale, così la pagina resta utilizzabile; le impostazioni di un dominio stanno anche nella finestra delle impostazioni di quel dominio.
- **La configurazione guidata è stata ridisegnata per chi parte davvero da zero:** una barra dei passi chiara con segni di spunta e "Passo N di 3", una spiegazione in parole semplici per ogni passo, un grande pulsante per passo, rilevamento automatico (non serve cliccare "controlla": si accorge da solo di un nuovo Node.js o pm2), un selettore di cartelle con posti rapidi, convalida in diretta, un aiuto "non so qual è il comando", una schermata di festa quando la prima app parte, ed extra facoltativi (domini, notifiche). "Avanti" resta disattivato finché un passo obbligatorio non è davvero completato.
- Il monitor condivide una sola lettura di pm2 tra la pagina e il controllo, così la sorveglianza in più non aggiunge carico.

## [1.2.0] - 2026-10-30

### Aggiunto
- Pulsanti nella testata per rimpicciolire o ingrandire tutta l'interfaccia (dall'80% al 200%) e per tornare al 100%. Testo, tabelle, finestre, log e configurazione guidata scalano insieme, e la dimensione scelta viene ricordata nel browser.

### Modificato
- Tutte le misure sono ora relative (`rem`), quindi seguono la dimensione scelta; con dimensioni grandi la testata va a capo e la tabella scorre di lato invece di schiacciarsi. La colonna "stato" è più larga.

## [1.1.0] - 2026-10-30

### Aggiunto
- Configurazione guidata per chi parte da zero: una procedura controlla Node.js e pm2, può installare pm2 al posto tuo (ripiegando sulla tua cartella personale se quella di sistema è protetta), ti fa scegliere la cartella del progetto con un selettore integrato, suggerisce il comando di avvio, avvia la tua prima app e salva l'elenco. Spiega anche come mantenere le app dopo un riavvio e come creare i domini.
- Se non trova pm2 o nessun demone, la procedura si apre da sola una volta per sessione del browser, il pulsante "configurazione guidata" pulsa e una scheda in evidenza sostituisce l'elenco vuoto.
- Gli strumenti (Node.js, npm, pm2) vengono cercati di nuovo su richiesta, così una nuova installazione viene trovata senza riavviare il monitor.

### Corretto
- I dettagli di errore che contengono un campo `status` (per esempio una prima app che si ferma subito) ora arrivano correttamente all'interfaccia.

## [1.0.0] - 2026-10-29

### Aggiunto
- Scoperta automatica dei demoni pm2 (`PM2_HOME`, `~/.pm2*`, demoni in esecuzione, cartelle aggiunte a mano).
- Recupero della configurazione da `pm2 jlist` e da `dump.pm2` a demone spento, e rilancio dei processi dalla specifica salvata.
- Domini per raggruppare i processi, con ordine di avvio configurabile e azioni avvia / riavvia / ferma per dominio.
- Configurazione persistente con percorso scelto da `--config` o `PM2_MONITOR_CONFIG`.
- Sezione "aiuto" nell'interfaccia e opzione `--version`.
- Interfaccia e documentazione in italiano e in inglese (selettore di lingua nella testata).
- Guida di installazione e configurazione per Linux, macOS e Windows (`docs/INSTALL.it.md`).
- Supporto previsto per Linux, macOS e Windows (testato solo su Linux).
- Controlli su `Host`, `Origin` e `Content-Type` per proteggere il server locale.

### Modificato
- Il codice è diviso in moduli (`pm2monitor/`); l'interfaccia mostra i processi raggruppati per dominio.
