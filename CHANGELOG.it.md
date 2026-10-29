# Changelog

[English](CHANGELOG.md) · **Italiano**

Formato basato su [Keep a Changelog](https://keepachangelog.com/it-IT/1.1.0/);
le versioni seguono il [Semantic Versioning](https://semver.org/lang/it/).

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
