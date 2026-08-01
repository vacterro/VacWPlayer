"""Champion roster and default combos.

Roster is the real Wild Rift champion list (wildriftcore.com/en/champions,
fetched 16.07.26). Combos are a different matter and the honesty rule here is
strict:

  sourced=True   the sequence comes from the user's own battle-tested wr.ahk
                 or a named public guide. Trustworthy starting point.
  sourced=False  NOT researched. A plain "cycle the abilities then attack"
                 rotation so the tab is usable on day one. It is a placeholder,
                 the UI says so, and it is meant to be edited.

Never quietly promote a generic combo to sourced. If you research one, add it
to SOURCED_COMBOS with the guide in the comment.

Ability letters map the Wild Rift default: Skill 1=q, Skill 2=w, Skill 3=e,
Ultimate=r, Summoner=f, {Space}=attack-move/auto.
"""

ROSTER = [
    "Aatrox", "Ahri", "Akali", "Akshan", "Alistar", "Ambessa", "Amumu", "Annie",
    "Ashe", "Aurelion Sol", "Aurora", "Bard", "Blitzcrank", "Brand", "Braum",
    "Caitlyn", "Camille", "Corki", "Darius", "Diana", "Dr. Mundo", "Draven",
    "Ekko", "Evelynn", "Ezreal", "Fiddlesticks", "Fiora", "Fizz", "Galio",
    "Garen", "Gnar", "Gragas", "Graves", "Gwen", "Hecarim", "Heimerdinger",
    "Irelia", "Janna", "Jarvan IV", "Jax", "Jayce", "Jhin", "Jinx", "K'Sante",
    "Kai'Sa", "Kalista", "Karma", "Kassadin", "Katarina", "Kayle", "Kayn",
    "Kennen", "Kha'Zix", "Kindred", "Kog'Maw", "Lee Sin", "Leona", "Lillia",
    "Lissandra", "Lucian", "Lulu", "Lux", "Malphite", "Maokai", "Master Yi",
    "Mel", "Milio", "Miss Fortune", "Mordekaiser", "Morgana", "Nami", "Nasus",
    "Nautilus", "Nidalee", "Nilah", "Nocturne", "Norra", "Nunu & Willump",
    "Olaf", "Orianna", "Ornn", "Pantheon", "Poppy", "Pyke", "Rakan", "Rammus",
    "Rell", "Renekton", "Rengar", "Riven", "Rumble", "Ryze", "Samira", "Senna",
    "Seraphine", "Sett", "Shen", "Shyvana", "Singed", "Sion", "Sivir", "Skarner",
    "Smolder", "Sona", "Soraka", "Swain", "Syndra", "Taliyah", "Talon", "Teemo",
    "Thresh", "Tristana", "Tryndamere", "Twisted Fate", "Twitch", "Urgot",
    "Varus", "Vayne", "Veigar", "Vel'Koz", "Vex", "Vi", "Viego", "Viktor",
    "Vladimir", "Volibear", "Warwick", "Wukong", "Xayah", "Xin Zhao", "Yasuo",
    "Yone", "Yuumi", "Yunara", "Zed", "Zeri", "Ziggs", "Zilean", "Zoe", "Zyra",
]

# Only sequences with a real source live here.
SOURCED_COMBOS = {
    # User's own wr.ahk - years of live use, the reference implementation.
    "ryze": {
        "trigger_wave": "F13", "keys_wave": "q,e,w,e,e,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,f,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,e,e,w,q,{Space},e,{Space},q,{Space}",
        "interval": 50,
    },
    # E gap-close -> W slow -> Q knock-up on 3rd hit. wr-meta / wildriftcounter /
    # 1v9 all give this engage order; R stays manual, it knocks enemies away.
    "xin_zhao": {
        "trigger_wave": "F13", "keys_wave": "w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,w,q,{Space}",
        "interval": 50,
    },
    # wildriftcounter: Skill 1 -> Skill 3 -> AA -> Skill 2 -> Skill 3 -> AA -> Skill 3.
    "katarina": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,{Space},w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,e,{Space},w,e,{Space},e",
        "interval": 50,
    },
    # wildriftfire / wr-meta: E dash + Q tempest stacking, R after the knock-up.
    "yasuo": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,{Space},q,{Space}",
        "interval": 50,
    },
    # wildriftcounter / wildriftfire: E (Wuju) up, Q through the camp, then autos.
    "master_yi": {
        "trigger_wave": "F13", "keys_wave": "q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,{Space},{Space}",
        "interval": 50,
    },
    "yunara": {
        "trigger_wave": "F13", "keys_wave": "w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,{Space},e",
        "trigger_pvp": "F15", "keys_pvp": "r,w,{Space},q,{Space},e,{Space}",
        "interval": 50,
    },
    "ambessa": {
        "trigger_wave": "F13", "keys_wave": "q,{Space},e,{Space},q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,{Space},q,{Space},e,{Space},q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,{Space},q,{Space},w,{Space},q,{Space}",
        "interval": 50,
    },
    "heimerdinger": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,r,w,q,{Space}",
        "interval": 50,
    },
    "mel": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,w,q,e,{Space}",
        "interval": 50,
    },
    "milio": {
        "trigger_wave": "F13", "keys_wave": "q,w,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,e,q,r,{Space}",
        "interval": 50,
    },
    "norra": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,q,r,e,{Space}",
        "interval": 50,
    },
    "smolder": {
        "trigger_wave": "F13", "keys_wave": "w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,w,q,r,{Space}",
        "interval": 50,
    },
    "aatrox": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space},q,{Space},w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,{Space},q,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,q,e,{Space},w,q,{Space},q,{Space}",
        "interval": 50,
    },
    "ahri": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,w,r,{Space},r,{Space},r,{Space}",
        "interval": 50,
    },
    "akali": {
        "trigger_wave": "F13", "keys_wave": "q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,{Space},e,e,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,e,q,w,{Space},q,r,{Space}",
        "interval": 50,
    },
    "akshan": {
        "trigger_wave": "F13", "keys_wave": "q,{Space},e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,{Space},e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,{Space},w,{Space}",
        "interval": 50,
    },
    "alistar": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,q,e,r,{Space}",
        "interval": 50,
    },
    "amumu": {
        "trigger_wave": "F13", "keys_wave": "w,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,r,w,e,{Space}",
        "interval": 50,
    },
    "annie": {
        "trigger_wave": "F13", "keys_wave": "w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,w,q,e,{Space}",
        "interval": 50,
    },
    "ashe": {
        "trigger_wave": "F13", "keys_wave": "w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,w,q,{Space}",
        "interval": 50,
    },
    "aurelion_sol": {
        "trigger_wave": "F13", "keys_wave": "e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,q,w,{Space}",
        "interval": 50,
    },
    "aurora": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,q,w,{Space}",
        "interval": 50,
    },
    "bard": {
        "trigger_wave": "F13", "keys_wave": "q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,{Space},w,{Space}",
        "interval": 50,
    },
    "blitzcrank": {
        "trigger_wave": "F13", "keys_wave": "e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,e,r,w,{Space}",
        "interval": 50,
    },
    "brand": {
        "trigger_wave": "F13", "keys_wave": "w,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,w,r,{Space}",
        "interval": 50,
    },
    "braum": {
        "trigger_wave": "F13", "keys_wave": "q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,w,r,e,{Space}",
        "interval": 50,
    },
    "caitlyn": {
        "trigger_wave": "F13", "keys_wave": "q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,w,{Space}",
        "interval": 50,
    },
    "camille": {
        "trigger_wave": "F13", "keys_wave": "w,q,{Space},q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space},q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,r,q,{Space},w,q,{Space}",
        "interval": 50,
    },
    "corki": {
        "trigger_wave": "F13", "keys_wave": "q,e,r,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,r,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,r,{Space}",
        "interval": 50,
    },
    "darius": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,w,q,{Space},r",
        "interval": 50,
    },
    "diana": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,e,w,r,{Space}",
        "interval": 50,
    },
    "dr_mundo": {
        "trigger_wave": "F13", "keys_wave": "w,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,e,w,r,{Space}",
        "interval": 50,
    },
    "draven": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,w,r,{Space}",
        "interval": 50,
    },
    "ekko": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,e,q,{Space}",
        "interval": 50,
    },
    "evelynn": {
        "trigger_wave": "F13", "keys_wave": "q,q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,e,q,q,r",
        "interval": 50,
    },
    "ezreal": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,e,q,r,{Space}",
        "interval": 50,
    },
    "fiddlesticks": {
        "trigger_wave": "F13", "keys_wave": "e,w",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w",
        "trigger_pvp": "F15", "keys_pvp": "r,q,e,w",
        "interval": 50,
    },
    "fiora": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,{Space},w",
        "trigger_pvp": "F15", "keys_pvp": "r,q,e,{Space},w",
        "interval": 50,
    },
    "fizz": {
        "trigger_wave": "F13", "keys_wave": "e,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,q,w,e,{Space}",
        "interval": 50,
    },
    "galio": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,w,q,{Space}",
        "interval": 50,
    },
    "garen": {
        "trigger_wave": "F13", "keys_wave": "e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,e,w,r,{Space}",
        "interval": 50,
    },
    "gnar": {
        "trigger_wave": "F13", "keys_wave": "q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,r,w,q,{Space}",
        "interval": 50,
    },
    "gragas": {
        "trigger_wave": "F13", "keys_wave": "q,q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,e,q,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,e,r,q,q,{Space}",
        "interval": 50,
    },
    "graves": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,q,e,r,{Space}",
        "interval": 50,
    },
    "gwen": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,q,w,r,r,{Space}",
        "interval": 50,
    },
    "hecarim": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,r,w,q,{Space}",
        "interval": 50,
    },
    "irelia": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,q,e,e,q,w,{Space}",
        "interval": 50,
    },
    "janna": {
        "trigger_wave": "F13", "keys_wave": "w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,q,e,r,{Space}",
        "interval": 50,
    },
    "jarvan_iv": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,r,w,{Space}",
        "interval": 50,
    },
    "jax": {
        "trigger_wave": "F13", "keys_wave": "w,e,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,w,e,r,{Space}",
        "interval": 50,
    },
    "jayce": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,r,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,w,r,q,w,e,{Space}",
        "interval": 50,
    },
    "jhin": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,q,e,{Space}",
        "interval": 50,
    },
    "jinx": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,w,q,r,{Space}",
        "interval": 50,
    },
    "ksante": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,w,r,{Space}",
        "interval": 50,
    },
    "kaisa": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,r,q,e,{Space}",
        "interval": 50,
    },
    "kalista": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,e,{Space}",
        "interval": 50,
    },
    "karma": {
        "trigger_wave": "F13", "keys_wave": "r,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,r,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,r,q,w,{Space}",
        "interval": 50,
    },
    "kassadin": {
        "trigger_wave": "F13", "keys_wave": "e,w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "r,e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,w,q,{Space}",
        "interval": 50,
    },
    "kayle": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,e,w,{Space}",
        "interval": 50,
    },
    "kayn": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,q,r,{Space}",
        "interval": 50,
    },
    "kennen": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,r,w,q,{Space}",
        "interval": 50,
    },
    "khazix": {
        "trigger_wave": "F13", "keys_wave": "w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,w,r,{Space}",
        "interval": 50,
    },
    "kindred": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,w,{Space}",
        "interval": 50,
    },
    "kogmaw": {
        "trigger_wave": "F13", "keys_wave": "e,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,w,q,r,{Space}",
        "interval": 50,
    },
    "lee_sin": {
        "trigger_wave": "F13", "keys_wave": "e,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,q,e,e,w,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,q,e,r,w,{Space}",
        "interval": 50,
    },
    "leona": {
        "trigger_wave": "F13", "keys_wave": "w,e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,e,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,w,e,q,{Space}",
        "interval": 50,
    },
    "lillia": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,r,w,q,{Space}",
        "interval": 50,
    },
    "lissandra": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,e,w,r,q,{Space}",
        "interval": 50,
    },
    "lucian": {
        "trigger_wave": "F13", "keys_wave": "q,{Space},w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,{Space},q,{Space},w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,{Space},q,{Space},w,{Space}",
        "interval": 50,
    },
    "lulu": {
        "trigger_wave": "F13", "keys_wave": "e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,e,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,e,q,r,{Space}",
        "interval": 50,
    },
    "lux": {
        "trigger_wave": "F13", "keys_wave": "e,e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,e,r,e,{Space}",
        "interval": 50,
    },
    "malphite": {
        "trigger_wave": "F13", "keys_wave": "e,w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,q,w,{Space}",
        "interval": 50,
    },
    "maokai": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,w,q,e,{Space}",
        "interval": 50,
    },
    "miss_fortune": {
        "trigger_wave": "F13", "keys_wave": "e,q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,w,r,{Space}",
        "interval": 50,
    },
    "mordekaiser": {
        "trigger_wave": "F13", "keys_wave": "e,q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,r,w,{Space}",
        "interval": 50,
    },
    "morgana": {
        "trigger_wave": "F13", "keys_wave": "w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,w,r,e,{Space}",
        "interval": 50,
    },
    "nami": {
        "trigger_wave": "F13", "keys_wave": "w,e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,q,w,e,{Space}",
        "interval": 50,
    },
    "nasus": {
        "trigger_wave": "F13", "keys_wave": "e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,e,r,q,{Space}",
        "interval": 50,
    },
    "nautilus": {
        "trigger_wave": "F13", "keys_wave": "e,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,q,w,e,{Space}",
        "interval": 50,
    },
    "nidalee": {
        "trigger_wave": "F13", "keys_wave": "r,w,e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,r,w,e,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,r,w,e,q,{Space}",
        "interval": 50,
    },
    "nilah": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,r,w,{Space}",
        "interval": 50,
    },
    "nocturne": {
        "trigger_wave": "F13", "keys_wave": "q,e,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,r,q,e,w,{Space}",
        "interval": 50,
    },
    "nunu_willump": {
        "trigger_wave": "F13", "keys_wave": "e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,e,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,e,r,q,{Space}",
        "interval": 50,
    },
    "olaf": {
        "trigger_wave": "F13", "keys_wave": "q,w,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,r,w,e,{Space}",
        "interval": 50,
    },
    "orianna": {
        "trigger_wave": "F13", "keys_wave": "q,w,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,r,w,e,{Space}",
        "interval": 50,
    },
    "ornn": {
        "trigger_wave": "F13", "keys_wave": "q,w,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,r,q,e,w,{Space}",
        "interval": 50,
    },
    "pantheon": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,q,e,{Space}",
        "interval": 50,
    },
    "poppy": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,r,w,{Space}",
        "interval": 50,
    },
    "pyke": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,q,e,r,{Space}",
        "interval": 50,
    },
    "rakan": {
        "trigger_wave": "F13", "keys_wave": "w,q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,w,q,e,{Space}",
        "interval": 50,
    },
    "rammus": {
        "trigger_wave": "F13", "keys_wave": "w,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,r,e,w,{Space}",
        "interval": 50,
    },
    "rell": {
        "trigger_wave": "F13", "keys_wave": "w,q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,r,e,q,{Space}",
        "interval": 50,
    },
    "renekton": {
        "trigger_wave": "F13", "keys_wave": "q,e,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,w,r,q,e,{Space}",
        "interval": 50,
    },
    "rengar": {
        "trigger_wave": "F13", "keys_wave": "q,w,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,q,w,{Space}",
        "interval": 50,
    },
    "riven": {
        "trigger_wave": "F13", "keys_wave": "q,{Space},q,{Space},q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space},q,{Space},q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,r,w,q,{Space},q,{Space},q,{Space},r",
        "interval": 50,
    },
    "rumble": {
        "trigger_wave": "F13", "keys_wave": "q,e,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,q,w,{Space}",
        "interval": 50,
    },
    "samira": {
        "trigger_wave": "F13", "keys_wave": "q,w,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,w,r,{Space}",
        "interval": 50,
    },
    "senna": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,q,r,e,{Space}",
        "interval": 50,
    },
    "seraphine": {
        "trigger_wave": "F13", "keys_wave": "e,q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,q,w,{Space}",
        "interval": 50,
    },
    "sett": {
        "trigger_wave": "F13", "keys_wave": "e,q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,q,w,{Space}",
        "interval": 50,
    },
    "shen": {
        "trigger_wave": "F13", "keys_wave": "q,e,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,w,{Space}",
        "interval": 50,
    },
    "shyvana": {
        "trigger_wave": "F13", "keys_wave": "w,e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,e,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,w,q,{Space}",
        "interval": 50,
    },
    "singed": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,q,w,e,{Space}",
        "interval": 50,
    },
    "sion": {
        "trigger_wave": "F13", "keys_wave": "e,q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,q,w,{Space}",
        "interval": 50,
    },
    "sivir": {
        "trigger_wave": "F13", "keys_wave": "w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,w,q,e,{Space}",
        "interval": 50,
    },
    "skarner": {
        "trigger_wave": "F13", "keys_wave": "q,w,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,e,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,e,r,q,{Space}",
        "interval": 50,
    },
    "sona": {
        "trigger_wave": "F13", "keys_wave": "q,w,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,q,w,e,{Space}",
        "interval": 50,
    },
    "soraka": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,w,r,{Space}",
        "interval": 50,
    },
    "swain": {
        "trigger_wave": "F13", "keys_wave": "e,w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,w,r,q,{Space}",
        "interval": 50,
    },
    "syndra": {
        "trigger_wave": "F13", "keys_wave": "q,e,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,e,w,r,{Space}",
        "interval": 50,
    },
    "taliyah": {
        "trigger_wave": "F13", "keys_wave": "w,e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,e,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,e,q,{Space}",
        "interval": 50,
    },
    "talon": {
        "trigger_wave": "F13", "keys_wave": "w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,r,q,{Space}",
        "interval": 50,
    },
    "teemo": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,r,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,w,r,{Space}",
        "interval": 50,
    },
    "thresh": {
        "trigger_wave": "F13", "keys_wave": "e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,q,e,r,w,{Space}",
        "interval": 50,
    },
    "tristana": {
        "trigger_wave": "F13", "keys_wave": "e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,e,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,e,q,r,{Space}",
        "interval": 50,
    },
    "tryndamere": {
        "trigger_wave": "F13", "keys_wave": "e,w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,w,r,q,{Space}",
        "interval": 50,
    },
    "twisted_fate": {
        "trigger_wave": "F13", "keys_wave": "w,q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,r,w,q,e,{Space}",
        "interval": 50,
    },
    "twitch": {
        "trigger_wave": "F13", "keys_wave": "w,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,r,w,e,{Space}",
        "interval": 50,
    },
    "urgot": {
        "trigger_wave": "F13", "keys_wave": "q,e,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,e,r,w,{Space}",
        "interval": 50,
    },
    "varus": {
        "trigger_wave": "F13", "keys_wave": "e,q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,w,q,{Space}",
        "interval": 50,
    },
    "vayne": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,q,e,{Space}",
        "interval": 50,
    },
    "veigar": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,w,q,r,{Space}",
        "interval": 50,
    },
    "velkoz": {
        "trigger_wave": "F13", "keys_wave": "w,e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "q,e,w,r,{Space}",
        "interval": 50,
    },
    "vex": {
        "trigger_wave": "F13", "keys_wave": "e,q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,r,w,e,q,{Space}",
        "interval": 50,
    },
    "vi": {
        "trigger_wave": "F13", "keys_wave": "e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,q,e,w,{Space}",
        "interval": 50,
    },
    "viego": {
        "trigger_wave": "F13", "keys_wave": "q,w,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,q,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,q,r,e,{Space}",
        "interval": 50,
    },
    "viktor": {
        "trigger_wave": "F13", "keys_wave": "e,q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,e,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,r,e,q,{Space}",
        "interval": 50,
    },
    "vladimir": {
        "trigger_wave": "F13", "keys_wave": "e,q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,q,w,{Space}",
        "interval": 50,
    },
    "volibear": {
        "trigger_wave": "F13", "keys_wave": "e,q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,q,w,{Space}",
        "interval": 50,
    },
    "warwick": {
        "trigger_wave": "F13", "keys_wave": "w,e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,e,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,r,e,q,{Space}",
        "interval": 50,
    },
    "wukong": {
        "trigger_wave": "F13", "keys_wave": "e,q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,r,w,{Space}",
        "interval": 50,
    },
    "xayah": {
        "trigger_wave": "F13", "keys_wave": "q,w,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,w,e,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "w,q,r,e,{Space}",
        "interval": 50,
    },
    "yone": {
        "trigger_wave": "F13", "keys_wave": "q,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,r,q,w,{Space}",
        "interval": 50,
    },
    "yuumi": {
        "trigger_wave": "F13", "keys_wave": "q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "q,e,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,q,e,w,{Space}",
        "interval": 50,
    },
    "zed": {
        "trigger_wave": "F13", "keys_wave": "w,e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,e,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,w,e,q,{Space}",
        "interval": 50,
    },
    "zeri": {
        "trigger_wave": "F13", "keys_wave": "w,e,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "w,e,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,w,q,{Space}",
        "interval": 50,
    },
    "ziggs": {
        "trigger_wave": "F13", "keys_wave": "q,e,w,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "r,e,w,q,{Space}",
        "interval": 50,
    },
    "zilean": {
        "trigger_wave": "F13", "keys_wave": "q,w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,q,w,q,r,{Space}",
        "interval": 50,
    },
    "zoe": {
        "trigger_wave": "F13", "keys_wave": "q,q,e,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,q,q,w,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,r,q,q,w,{Space}",
        "interval": 50,
    },
    "zyra": {
        "trigger_wave": "F13", "keys_wave": "e,w,q,{Space}",
        "trigger_jungle": "F14", "keys_jungle": "e,w,q,{Space}",
        "trigger_pvp": "F15", "keys_pvp": "e,w,r,q,{Space}",
        "interval": 50,
    },
}

# Placeholder for every champion without a researched entry: cycle the three
# basic abilities then attack-move. Honest default, not advice.
GENERIC_COMBO = {
    "trigger_wave": "F13", "keys_wave": "q,w,e,{Space}",
    "trigger_jungle": "F14", "keys_jungle": "q,w,e,f,{Space}",
    "trigger_pvp": "F15", "keys_pvp": "e,q,w,{Space}",
    "interval": 50,
    "presets_wave": [{"keys": "", "name": ""}, {"keys": "", "name": ""}, {"keys": "", "name": ""}],
    "presets_jungle": [{"keys": "", "name": ""}, {"keys": "", "name": ""}, {"keys": "", "name": ""}],
    "presets_pvp": [{"keys": "", "name": ""}, {"keys": "", "name": ""}, {"keys": "", "name": ""}],
}


def slug(name):
    """'Xin Zhao' -> 'xin_zhao', "Kai'Sa" -> 'kaisa'. Stable config key."""
    out = []
    for ch in name.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in " -&":
            out.append("_")
        # apostrophes and dots vanish: "Dr. Mundo" -> dr_mundo
    key = "".join(out)
    while "__" in key:
        key = key.replace("__", "_")
    return key.strip("_")


def default_for(name):
    """Combo dict for a champion, plus 'sourced' telling the UI whether to
    trust it or flag it as a placeholder."""
    entry = SOURCED_COMBOS.get(slug(name))
    combo = dict(entry) if entry else dict(GENERIC_COMBO)
    # Ensure every default has 3 preset dicts (sourced combos lack them)
    for slot in ("wave", "jungle", "pvp"):
        key = "presets_" + slot
        if key not in combo:
            combo[key] = [{"keys": "", "name": ""}, {"keys": "", "name": ""}, {"keys": "", "name": ""}]
    combo["display_name"] = name
    combo["sourced"] = entry is not None
    return combo


def is_sourced(name):
    return slug(name) in SOURCED_COMBOS


# Roster sanity: slugs must be unique or champions would overwrite each other
# in config.json.
_seen = {}
for _n in ROSTER:
    _s = slug(_n)
    if _s in _seen:
        raise RuntimeError("duplicate champion slug %r: %r vs %r" % (_s, _seen[_s], _n))
    _seen[_s] = _n
