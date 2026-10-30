# Installazione e configurazione

[English](INSTALL.md) · **Italiano**

Guida per installare **pm2**, configurarlo per i tuoi processi e usare **pm2-monitor** per controllarli. Vale per Linux, macOS e Windows: dove i comandi cambiano, trovi una voce per sistema.

> **Preferisci essere guidato?** Installa Python (sezione 1), avvia il monitor (sezione 7) e clicca **configurazione guidata** in alto nella pagina: controlla Node.js e pm2, può installare pm2 al posto tuo, ti aiuta a scegliere la cartella del progetto e avvia la tua prima app. Questo documento è la versione manuale.

Indice
1. [Cosa serve](#1-cosa-serve)
2. [Installare Node.js](#2-installare-nodejs)
3. [Installare pm2](#3-installare-pm2)
4. [Configurare pm2 per i tuoi processi](#4-configurare-pm2-per-i-tuoi-processi)
5. [Più demoni pm2 separati](#5-più-demoni-pm2-separati)
6. [Avvio automatico di pm2 al login o al boot](#6-avvio-automatico-di-pm2-al-login-o-al-boot)
7. [Installare e avviare pm2-monitor](#7-installare-e-avviare-pm2-monitor)
8. [Configurare pm2-monitor](#8-configurare-pm2-monitor)
9. [Avvio automatico di pm2-monitor](#9-avvio-automatico-di-pm2-monitor)
10. [Problemi comuni](#10-problemi-comuni)

---

## 1. Cosa serve

| Per | Serve | Verifica |
|---|---|---|
| pm2 | Node.js (una versione LTS recente) e npm | `node -v` · `npm -v` |
| pm2-monitor | Python 3.8 o più recente. Nessun pacchetto da installare | `python3 --version` (su Windows `python --version` o `py --version`) |

Su Windows, i comandi di questa guida vanno nel **PowerShell** salvo dove indicato.

## 2. Installare Node.js

Salta questo passo se `node -v` risponde già con una versione.

**Per tutti i sistemi:** scarica l'installer LTS da <https://nodejs.org> e seguilo.

Alternative da terminale:

- **Linux / macOS, con nvm** (consigliato: nessun `sudo`, più versioni affiancate). Installa nvm seguendo le istruzioni di <https://github.com/nvm-sh/nvm>, riapri il terminale e poi:
  ```bash
  nvm install --lts
  nvm use --lts
  ```
- **macOS, con Homebrew:** `brew install node`
- **Windows, con winget:** `winget install OpenJS.NodeJS.LTS`
- **Windows, con nvm-windows:** installa da <https://github.com/coreybutler/nvm-windows>, poi `nvm install lts` e `nvm use lts`
- **Linux, dal gestore pacchetti** (versioni spesso datate): `sudo apt install nodejs npm` · `sudo dnf install nodejs npm` · `sudo pacman -S nodejs npm`

Chiudi e riapri il terminale, poi controlla `node -v` e `npm -v`.

## 3. Installare pm2

```bash
npm install -g pm2
pm2 --version
```

- **Linux con Node di sistema** (non nvm): se `npm install -g` dà `EACCES`, non usare `sudo`; imposta una cartella globale tua:
  ```bash
  mkdir -p ~/.npm-global
  npm config set prefix ~/.npm-global
  ```
  e aggiungi `~/.npm-global/bin` al `PATH` (nel `~/.bashrc` o `~/.zshrc`: `export PATH="$HOME/.npm-global/bin:$PATH"`).
- **Windows:** se PowerShell risponde che l'esecuzione di script è disabilitata (`pm2.ps1 cannot be loaded`), puoi usare `pm2.cmd` al posto di `pm2`, oppure consentire gli script solo a te con
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
- **Dove viene installato** (utile per `pm2Path`, vedi sezione 8): `npm root -g` indica la cartella dei pacchetti, e il comando `pm2` sta nella cartella `bin` accanto (su Windows direttamente nella cartella indicata da `npm prefix -g`).

## 4. Configurare pm2 per i tuoi processi

### Avviare un processo

```bash
pm2 start app.js --name mia-app            # uno script node
pm2 start npm --name mio-frontend -- start # un comando npm (npm start)
pm2 start /percorso/server.py --interpreter python3 --name mio-script   # uno script Python
pm2 start /percorso/bin/mio-programma --name mio-binario                # un eseguibile
```
Su Windows lo script Python si avvia con `--interpreter python` e i percorsi usano `\`. Per avviare dalla cartella giusta, spostati lì prima, o usa `--cwd <cartella>`.

### Comandi di uso quotidiano

| Comando | Cosa fa |
|---|---|
| `pm2 list` | elenca i processi e il loro stato |
| `pm2 logs [nome]` | segue i log (Ctrl+C per uscire) |
| `pm2 stop <nome>` / `pm2 start <nome>` | ferma / riavvia un processo già registrato |
| `pm2 restart <nome>` | riavvia |
| `pm2 delete <nome>` | lo toglie da pm2 (non cancella i file) |
| `pm2 save` | salva l'elenco attuale in `dump.pm2` |
| `pm2 resurrect` | ripristina l'elenco salvato con `pm2 save` |
| `pm2 kill` | spegne il demone pm2 e tutti i suoi processi |

pm2 lavora con un **demone** in background: il primo comando lo avvia, e i processi restano vivi anche chiudendo il terminale.

### File di configurazione (consigliato per più processi)

Crea `ecosystem.config.js` nella cartella del progetto:

```js
module.exports = {
  apps: [
    {
      name: 'database',
      script: '/percorso/db/avvio.sh',
      cwd: '/percorso/db',
    },
    {
      name: 'backend',
      script: 'npm',
      args: 'start',
      cwd: '/percorso/backend',
      env: { NODE_ENV: 'development', PORT: 3000 },
    },
  ],
};
```
Poi:
```bash
pm2 start ecosystem.config.js            # tutti
pm2 start ecosystem.config.js --only backend
pm2 save
```
Su Windows scrivi i percorsi con `/` o con `\\` doppio nel file JS.

**Salvare** con `pm2 save` è importante: pm2-monitor ricostruisce la configurazione dei processi anche a demone spento proprio da `dump.pm2`.

## 5. Più demoni pm2 separati

Di norma ne basta uno (cartella `~/.pm2`). Se vuoi tenere separati gruppi di processi (per esempio due progetti che non devono influenzarsi), usa una cartella `PM2_HOME` diversa per ciascuno. pm2-monitor trova da solo le cartelle chiamate `.pm2*` nella tua home.

| Shell | Comando |
|---|---|
| Linux / macOS (bash, zsh) | `PM2_HOME=~/.pm2-progetto pm2 start ecosystem.config.js` |
| Windows PowerShell | `$env:PM2_HOME="$HOME\.pm2-progetto"; pm2 start ecosystem.config.js` |
| Windows cmd | `set PM2_HOME=%USERPROFILE%\.pm2-progetto` e poi `pm2 start ecosystem.config.js` |

Ricordati di impostare la stessa `PM2_HOME` per **ogni** comando pm2 successivo su quel demone (`pm2 list`, `pm2 stop`, ...), altrimenti parli con il demone predefinito. Per una cartella con un nome diverso da `.pm2*`, aggiungila a mano da "demoni" nell'interfaccia di pm2-monitor.

## 6. Avvio automatico di pm2 al login o al boot

Serve se vuoi ritrovare i processi dopo un riavvio del computer. Prima `pm2 save` per fissare l'elenco, poi:

- **Linux e macOS:**
  ```bash
  pm2 startup
  ```
  pm2 stampa **un comando da copiare ed eseguire** (di solito con `sudo`): eseguilo, poi `pm2 save`. Funziona con systemd su Linux e launchd su macOS.
- **Windows:** `pm2 startup` non è supportato. Opzioni:
  - Utilità della comunità come [pm2-installer](https://github.com/jessety/pm2-installer), che registra pm2 come servizio.
  - Un'attività pianificata che al login esegue `pm2 resurrect` (Utilità di pianificazione → "Crea attività"; azione: avvia `pm2.cmd` con argomento `resurrect`).

Con più demoni (sezione 5) il comando di avvio automatico va ripetuto per ciascuna `PM2_HOME`; in alternativa un piccolo script di login che esegue `pm2 resurrect` per ognuno.

## 7. Installare e avviare pm2-monitor

1. Scarica l'ultima versione dalla [pagina **Releases**](https://github.com/NotCRL/pm2-monitor/releases) della repository (file `.zip` o `.tar.gz`) e decomprimila in una cartella fissa, per esempio `~/pm2-monitor` (su Windows `C:\Users\<tu>\pm2-monitor`). In alternativa `git clone` della repository.
2. Controlla Python: `python3 --version` (Windows: `python --version`). Su Windows, se manca: `winget install Python.Python.3.12`. Su macOS: `brew install python` oppure l'installer da <https://www.python.org>. Su Linux di solito c'è già; altrimenti `sudo apt install python3` (o l'equivalente della tua distribuzione).
3. Avvia, dalla cartella decompressa:
   ```bash
   python3 server.py          # Windows: python server.py
   ```
4. Apri **http://127.0.0.1:8440** nel browser. Il server resta in ascolto finché non chiudi il terminale (per tenerlo sempre attivo vedi la sezione 9).

Opzioni: `--port N` (porta diversa), `--config PERCORSO` (config altrove, vedi sezione 8), `--version`.

Nessun pacchetto da installare: usa solo la libreria standard di Python. Il server ascolta **solo** su `127.0.0.1`, quindi non è raggiungibile dalla rete. L'interfaccia è disponibile in italiano e in inglese (selettore nella testata).

## 8. Configurare pm2-monitor

Al primo avvio il monitor cerca da solo i demoni pm2 del computer. Poi, dall'interfaccia:

- **scansiona**: rifà la ricerca dei demoni.
- **demoni**: rinomina un demone, nascondilo, aggiungine uno a mano (cartella `PM2_HOME`).
- **domini** (`+ dominio`): raggruppa i processi, anche di demoni diversi. Assegna un processo a un dominio dal menu a tendina della riga.
- **ord**: ordine di avvio nel dominio (numero più basso = parte prima). "avvia tutti" aspetta che ognuno sia online prima del successivo. ⚙ accanto al dominio imposta il tempo massimo di attesa.

### Dove sta il file di configurazione

| Sistema | Posizione predefinita |
|---|---|
| Linux | `~/.config/pm2-monitor/config.json` (o sotto `$XDG_CONFIG_HOME`) |
| macOS | `~/Library/Application Support/pm2-monitor/config.json` |
| Windows | `%APPDATA%\pm2-monitor\config.json` |

Per cambiarla:
```bash
python3 server.py --config /percorso/mia-config.json     # un file, oppure una cartella
```
oppure con la variabile d'ambiente `PM2_MONITOR_CONFIG` (Linux/macOS: `export PM2_MONITOR_CONFIG=...`; PowerShell: `$env:PM2_MONITOR_CONFIG="..."`). La riga di comando ha la precedenza. Il percorso attuale è sempre visibile nell'interfaccia, in **aiuto**.

Per usare le stesse impostazioni su un altro computer, copia il file.

### Cosa contiene e cosa puoi modificare a mano (a server fermo)

- `pm2Path`: percorso di un pm2 preciso da usare, se il monitor non lo trova da solo o ne hai più di uno. Esempio: `"pm2Path": "/home/tu/.nvm/versions/node/v20.11.0/bin/pm2"` o su Windows `"pm2Path": "C:\\Users\\tu\\AppData\\Roaming\\npm\\pm2.cmd"`.
- `extraHomes`: cartelle `PM2_HOME` da cercare oltre a quelle trovate da sole.
- `processes`: per ogni processo dominio, ordine e specifica di lancio (script, cartella, argomenti, interprete). Se un processo ha bisogno di variabili d'ambiente per ripartire da zero, aggiungi `"env": { "NOME": "valore" }` nella sua `spec`: l'ambiente non viene salvato in automatico perché può contenere dati riservati.

## 9. Avvio automatico di pm2-monitor

Sostituisci `/percorso/pm2-monitor` con la cartella reale.

### Linux (systemd, a livello utente)

Crea `~/.config/systemd/user/pm2-monitor.service`:
```ini
[Unit]
Description=pm2-monitor

[Service]
ExecStart=/usr/bin/python3 /percorso/pm2-monitor/server.py
Restart=on-failure

[Install]
WantedBy=default.target
```
Poi:
```bash
systemctl --user daemon-reload
systemctl --user enable --now pm2-monitor
```
(`which python3` ti dice il percorso giusto di Python. Per farlo partire anche senza login: `loginctl enable-linger $USER`.)

### macOS (launchd)

Crea `~/Library/LaunchAgents/pm2-monitor.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>pm2-monitor</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/percorso/pm2-monitor/server.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
```
Poi `launchctl load ~/Library/LaunchAgents/pm2-monitor.plist` (per fermarlo: `launchctl unload ...`). Con Python di Homebrew sostituisci `/usr/bin/python3` col risultato di `which python3`.

### Windows (Utilità di pianificazione)

Da PowerShell, per avviarlo a ogni login senza finestra di console:
```powershell
schtasks /Create /SC ONLOGON /TN "pm2-monitor" /TR "pythonw C:\percorso\pm2-monitor\server.py"
```
Per rimuoverlo: `schtasks /Delete /TN "pm2-monitor" /F`.

In tutti i casi, se il monitor parte fuori dal tuo terminale e non trova pm2, imposta `pm2Path` nella config (sezione 8).

## 10. Problemi comuni

| Sintomo | Causa probabile e rimedio |
|---|---|
| `pm2: command not found` / `non riconosciuto` | La cartella globale di npm non è nel `PATH`. Riapri il terminale; verifica con `npm prefix -g` e aggiungi quella cartella (Linux/macOS: la sua `bin`) al `PATH`. |
| `EACCES` installando pm2 | Non usare `sudo`: vedi sezione 3 (cartella globale personale) o usa nvm. |
| PowerShell: "script disabilitati" | Usa `pm2.cmd` oppure `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. |
| Il monitor dice "pm2 non trovato" | Succede spesso se parte da un servizio o da un'attività pianificata, che non hanno il tuo `PATH`. Imposta `pm2Path` nella config. |
| Un demone non compare | Aggiungi la sua cartella da "demoni". Su Windows i demoni in esecuzione non vengono scoperti da soli: servono `PM2_HOME` o le cartelle `.pm2*` nella home. |
| "demone spento" | Il demone di quel gruppo non gira. I processi sono mostrati dalla config salvata e "start" fa ripartire anche il demone. |
| Un processo "non avviato" non parte | Guarda l'errore mostrato; controlla che script e cartella nella specifica esistano ancora, e se serve aggiungi `env` (sezione 8). |
| La porta 8440 è occupata | Avvia con `--port 8450` (o un'altra libera). |
| `SyntaxError` all'avvio del monitor | Python troppo vecchio: serve 3.8 o più recente. |

Per altro, nella finestra del monitor c'è **aiuto**; per bug e richieste apri una Issue sulla repository.
