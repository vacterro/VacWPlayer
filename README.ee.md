🇪🇪 **Eesti** | 🇷🇺 [Русский](README.ru.md) | 🇺🇸 [English](README.md) | 👴 [Дед-Мод](README.ded.md) | 🇯🇵 [日本語](README.ja.md)

# VacWPlayer

**v0.3.9** — [Muudatused](CHANGELOG.md)

Üks vanaaegse teemaga GUI kogu Wild Rifti tööriistakomplektile: pedaalide kombod, meistripõhised rotatsioonid, automaatne minimeerimine surma korral ja automaatne jätkamine pärast mängu – juhitav "super AHK" koos kasutajaliidesega, ilma skriptide käsitsi redigeerimiseta.

## Funktsioonid

- **Vahekaart Main (Peamine)** – globaalsed sisendi lülitid (hiire ümberkaardistamine, tühiku spämm, jõudeoleku ennetamine, peatamise klahv, käsitsi sihtimise paus, sihtmärk exe) pluss General-režiimi kohandatud kombode loend: lisa, kustuta, tühjenda, seo päästik klahvivajutusega, taasta pärandseaded.
- **Vahekaart Champions** – meistripõhised Wave / Jungle / PVP rotatsioonid. Eellaaditud tõelised kombod Ryze'ile, Xin Zhaole, Yasuole, Master Yile jt; ülejäänud Wild Rifti rosterile redigeeritavad kohahoidjad.
- **Vahekaart AFK Farm** – tsüklida läbi minikaardi positsioonide, liigu + kombo, korda.
- **Vahekaardid Death Watch / Auto Continue** – juhivad olemasolevaid mootoreid `deathwatch.py` / `autocontinue.py` (testrežiimi lüliti, reaalajas olek), mis võtavad puhtalt üle käsuga `--replace`.
- **Vahekaardid Buy / Accept / Surrender** – kullapõhine auto-ost pärast tagasikutsumist (`digit_reader`), matši auto-vastuvõtt ja allaandmise hääletus, igaüks oma mootoriga (`deathwatch_config.json`, `accept.py`, `surrender.py`).
- **Vahekaart Minimap** – kliki-ja-liigu kiirklahvid seotud raja positsioonidega, read ümberjärjestatavad.
- **Tšempioni režiim** (rippmenüü valib täpselt ühe aktiivse kombokomplekti), et F13–F15 ei satuks kunagi kangelaste vahel konflikti.
- **Sammupõhised viivitused** – süntaks `klahv:ms`, nt `q,e:120,{Space}:200`.
- **Süsteemisalve ikoon** – X peidab salve, mootor jätkab tööd; Quit peatab kõik.
- **Wiki** – arhitektuur, seadete referents, tabide juhend: `docs/wiki/`.

## Nõuded

- Windows, Python 3.11, projekti virtuaalne keskkond (`../venv`).
- AutoHotkey v1: `AutoHotkeyU64.exe` rakenduse kõrval, kui olemas, muidu standardpaigaldus `C:\Program Files\AutoHotkey\`.
- `pip install -r requirements.txt`.

## Käivitamine

Topeltklõps **`VacWPlayer.vbs`** (varjatud konsool, käivitub vaikselt) või käivita **`VacWPlayer.bat`** käsitsi (nähtavad vead / `--check`). Mõlemad leiavad venv-i ise.
Või käsitsi:

```
..\venv\Scripts\pythonw.exe main.pyw
```

Vaikimisi kombokomplekt (Ryze) käivitub automaatselt. Muuda mis tahes vahekaarti, vali tšempion ja vajuta **Käivita**.

## Vastutusest

See tööriist automatiseerib mängu sisendeid (klahvivajutused, hiireklõpsud, ekraanituvastus).
**Automatiseerimistarkvara kasutamine mängus League of Legends: Wild Rift rikub Riot Games'i
kasutustingimusi.** Funktsioonid nagu Rotating Farm, Idle Prevention, auto-vastuvõtt/allaandmine
ja surmaautomaatika võivad kaasa tuua konto peatamise või jäädava keelu. Kasutad omal vastutusel.

## Testid

```
python -m pytest tests/ -v
```

Vajab pytesti (`pip install pytest` või `pip install -r requirements.txt`).
Testid impordivad ilma GUI-ta mooduleid ja kontrollivad, et kõik .py failid kompileeruvad puhtalt.

## Kuidas see töötab

GUI ise ei püüa kunagi klahvivajutusi – see genereerib `wr_runtime.ahk` failist `config.json` kasutades `ahk_generator.py` ja käivitab AutoHotkey (Event režiim, vajalik BlueStacksi jaoks). Ainult MEIE käivitatud runtime jälgitakse ja tapetakse PID järgi; teised AHK skriptid jäetakse rahule. Vana käsitsi kirjutatud `wr.ahk` eemaldatakse käivitamisel automaatselt.

Viis konfiguratsiooni, igaühel üks töö: `config.json` (kombod, režiim, lülitid), `deathwatch_config.json` (surma tuvastamine), `autocontinue_config.json` (mängujärgsed nupud), `accept_config.json` (matši vastuvõtmine), `surrender_config.json` (allaandmise hääletus). `wr_runtime.ahk` genereeritakse – ära kunagi redigeeri seda käsitsi.

## Kombo süntaks

Komadega eraldatud klahvid. `{Space}`, `f`, tähed. Oskuste tähed q/w/e/r valatakse Shiftiga (enda peale valamine), kui "Shift-cast" pole välja lülitatud. Lisa `:ms` klahvile, et määrata selle sammu viivitus; vastasel juhul rakendub kombo intervall. Hoidke päästikut all, et tsüklit korrata.

<!-- source-digest: README.md sha256:b1c6e5b71595a204 -->
