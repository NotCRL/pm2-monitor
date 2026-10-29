# pm2-monitor

[English](README.md) · **Italiano**

[![tests](https://github.com/NotCRL/pm2-monitor/actions/workflows/tests.yml/badge.svg)](https://github.com/NotCRL/pm2-monitor/actions/workflows/tests.yml)

UI web locale per vedere e gestire i processi pm2 di qualsiasi demone presente sul computer.
Linux, macOS e Windows; solo libreria standard Python (3.8+), nessuna dipendenza.
Avvio: `python3 server.py [--port N] [--config PERCORSO] [--version]` → http://127.0.0.1:8440. Il pulsante "aiuto" nell'interfaccia raccoglie guide e risoluzione dei problemi. L'interfaccia è disponibile in italiano e in inglese (selettore nella testata).
Guida passo passo (Node.js, pm2, monitor, avvio automatico, per Linux / macOS / Windows): [docs/INSTALL.it.md](docs/INSTALL.it.md).

## Cosa fa
- **Scopre i demoni pm2** da solo: `PM2_HOME` dell'ambiente, le cartelle `~/.pm2*`, i demoni in esecuzione (il loro titolo in `ps` contiene il `PM2_HOME`; non su Windows) e le cartelle aggiunte a mano dal pulsante "demoni". Ogni demone ha un id stabile (`.pm2` → `default`, `.pm2-work` → `work`) e un'etichetta modificabile; si può nascondere.
- **Recupera la config di pm2**: da `pm2 jlist` a demone vivo, da `dump.pm2` a demone spento. Per ogni processo salva come rilanciarlo (script, cwd, args, interprete, modalità).
- **Domini**: raggruppano processi anche di demoni diversi (es. `backend`). Un processo sta in un solo dominio.
- **Ordine di avvio** per processo, dentro il dominio. "avvia tutti" parte dal numero più basso e, per ogni processo, aspetta che sia online e ci resti 2 s prima di passare al successivo; se uno non parte entro il timeout del dominio (default 30 s, modificabile da ⚙) la sequenza si ferma e lo dice. "ferma tutti" va al contrario; "riavvia" fa stop poi start.
- **Avvio da config**: un processo salvato ma non più nel demone (o con demone spento) riparte da una ecosystem file generata dalla specifica salvata. Anche il demone ripartirà da solo.
- Per ogni processo: stato, cpu, memoria, uptime, restart (in giallo se > 0), pid; restart / stop / start singoli; clic sulla riga → log `out` / `err` (ultime 400 righe, anche a demone spento).

## Configurazione
File `config.json` in:
- Linux `~/.config/pm2-monitor/` (o `$XDG_CONFIG_HOME`)
- macOS `~/Library/Application Support/pm2-monitor/`
- Windows `%APPDATA%\pm2-monitor\`
- ovunque con `--config /percorso/config.json` (o una cartella) oppure `PM2_MONITOR_CONFIG`; la riga di comando ha la precedenza.

Contiene demoni noti, domini, e per ogni processo dominio/ordine/specifica di lancio. Scritto in modo atomico; se è illeggibile viene spostato in `config.json.corrupt-<ts>` e se ne crea una nuova (avviso in testata). Si può modificare a mano, anche `pm2Path` (percorso di pm2 da usare) e `env` dentro una specifica.
La specifica **non salva l'env** del processo (è pieno di variabili di sistema, anche sensibili): se serve a un rilancio da zero va aggiunta a mano come `"env": {...}` nella specifica.

## Scelte e perché
- **Non chiama mai pm2 se il demone è spento**: `pm2 jlist` ne avvierebbe uno nuovo vuoto. Lo stato del demone si legge da `PM2_HOME/pm2.pid`.
- **Controllo del pid portabile**: su Windows `os.kill(pid, 0)` termina il processo, quindi lì si usa l'API di sistema (ctypes).
- **pm2 cercato** nel PATH, poi in nvm, fnm, volta, asdf, Homebrew, npm globale e, su Windows, `%APPDATA%\npm`, nvm-windows. Versioni ordinate numericamente (v18 > v9). La cartella di pm2 va nel PATH dei sottoprocessi perché pm2 è uno script node. Se non lo trova, lo dice a schermo.
- **Le azioni usano pm2 diretto**, non script di orchestrazione propri: per un riavvio completo con sequenza fissa si usa un dominio con l'ordine giusto.
- **Sicurezza**: ascolta solo su 127.0.0.1, rifiuta `Host` non locali (DNS rebinding) e POST senza `Content-Type: application/json` o con `Origin` estraneo, così un sito aperto nel browser non può fermare i tuoi processi. Le azioni accettano solo demoni già registrati, mai percorsi arbitrari.
- **Se il server smette di rispondere** la testata diventa rossa ("NON AGGIORNATO da Ns") invece di mostrare dati vecchi come buoni.
- Un solo job per dominio alla volta; le azioni sullo stesso demone sono serializzate.
- La memoria dei processi avviati via `npm` è quella del wrapper npm, non dei figli: pm2 non somma i figli.

## Segnalazioni e contributi
Bug e richieste di funzione vanno aperti su <https://github.com/NotCRL/pm2-monitor/issues> (ci sono i template; va bene sia l'italiano sia l'inglese).
Versioni e novità in [CHANGELOG.it.md](CHANGELOG.it.md); le versioni seguono il Semantic Versioning.

## Licenza
MIT, vedi [LICENSE](LICENSE).

## Struttura
- `server.py` — HTTP (API: `/api/state`, `/api/logs`, `/api/job`, POST `/api/action`, `/api/domain-action`, `/api/config`)
- `pm2monitor/osenv.py` — differenze tra sistemi operativi
- `pm2monitor/discovery.py` — scoperta demoni, lettura dump, specifica di lancio
- `pm2monitor/store.py` — config persistente
- `pm2monitor/service.py` — stato, azioni, job per dominio
- `index.html` — interfaccia (italiano / inglese), con la sezione "aiuto"
- `tests/` — `python3 -m unittest discover -s tests -t .`

## Limiti noti
- Testato solo su Linux. Su Windows i demoni in esecuzione non si scoprono da `ps`: vengono trovati da `PM2_HOME`, da `%USERPROFILE%\.pm2*` o aggiunti a mano.
- L'identità di un processo è `demone/nome`: due processi con lo stesso nome in demoni diversi sono distinti, nello stesso demone no (come in pm2).
- Il modo cluster è salvato (`exec_mode`, `instances`) ma testato solo in fork.
- L'output della console del server e `--help` sono solo in inglese.
