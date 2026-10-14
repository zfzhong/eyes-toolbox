"""App categories: iOS Screen Time's 12, for Android packages (David 10-13: "can we borrow ios's
categorization? 12 categories."). The same rules as the EYES server (serveraws eyes/categories.py):
  1. OVERRIDES  fixed entries (apps not on the US Play Store)
  2. SYSTEM     system apps by package; browsers get their own category, Browser (Android only,
                David 10-14); email to Productivity (App Store genre, as iOS Screen Time)
  3. Play       the app's Google Play category, folded into the 12 by PLAY. Looked up on the server
                and kept in eyeslib/data/play_categories.csv (package,play; play empty = no US page)
  4. Android    the developer's own ApplicationInfo.category (EyesApp only), folded by ANDROID
  5. Other
The home screen is kept apart elsewhere and not categorized here.
"""
import csv
import os
import re

DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "play_categories.csv")

IOS = ["Social", "Games", "Entertainment", "Creativity", "Education", "Health & Fitness",
       "Information & Reading", "Productivity & Finance", "Shopping & Food", "Travel", "Utilities", "Other",
       "Browser"]   # Browser: EYES's own 13th (David 10-14: "Browser is such a major APP ... put Browser as a separate category")

# Google Play category -> iOS Screen Time category. GAME_* are all Games.
PLAY = {
    "SOCIAL": "Social", "COMMUNICATION": "Social", "DATING": "Social",
    "ENTERTAINMENT": "Entertainment", "VIDEO_PLAYERS": "Entertainment", "MUSIC_AND_AUDIO": "Entertainment",
    "COMICS": "Entertainment", "EVENTS": "Entertainment",
    "PHOTOGRAPHY": "Creativity", "ART_AND_DESIGN": "Creativity",
    "EDUCATION": "Education", "PARENTING": "Education",
    "HEALTH_AND_FITNESS": "Health & Fitness", "MEDICAL": "Health & Fitness", "SPORTS": "Health & Fitness",
    "NEWS_AND_MAGAZINES": "Information & Reading", "BOOKS_AND_REFERENCE": "Information & Reading",
    "WEATHER": "Information & Reading", "LIBRARIES_AND_DEMO": "Information & Reading",
    "PRODUCTIVITY": "Productivity & Finance", "BUSINESS": "Productivity & Finance", "FINANCE": "Productivity & Finance",
    "SHOPPING": "Shopping & Food", "FOOD_AND_DRINK": "Shopping & Food",
    "TRAVEL_AND_LOCAL": "Travel", "MAPS_AND_NAVIGATION": "Travel", "AUTO_AND_VEHICLES": "Travel",
    "TOOLS": "Utilities", "PERSONALIZATION": "Utilities",
    "LIFESTYLE": "Other", "HOUSE_AND_HOME": "Other", "BEAUTY": "Other",
}
ANDROID = {"game": "Games", "audio": "Entertainment", "video": "Entertainment", "image": "Creativity",
           "social": "Social", "news": "Information & Reading", "maps": "Travel", "productivity": "Productivity & Finance"}

# System apps: not on the Play Store, or their Play page is a different app. (pattern, category)
SYSTEM = [
    (r"dialer|incallui|\.telecom$|telephonyui|contacts|unifiedwfc|\.phone$|mms|messaging|\.messages", "Social"),
    (r"camera|gallery|photos", "Creativity"),
    (r"projection\.gearhead", "Travel"),
    (r"clock|calendar|calculator|notes|memo|reminder", "Productivity & Finance"),
    (r"\.chrome(\.(beta|dev|canary))?$|browser|firefox|^org\.mozilla\.|\.emmx$|^com\.opera\.|duckduckgo|^com\.brave\.|vivaldi|ucmobile|\.silk$", "Browser"),  # David 10-14
    (r"\.gm$|outlook|mail", "Productivity & Finance"),                              # email: App Store Productivity
    (r"^com\.amazon\.(settings|venezia|kindle\.unifiedSearch)|^com\.android\.settings|systemui|permissioncontroller|credentialmanager|aodservice|\.lool$|packageinstaller"
     r"|\.vending$|\.gms$|^com\.example\.eyesapp|keyguard|bixby|smartcapture|filemanager|myfiles|oneconnect", "Utilities"),
]
OVERRIDES = {
    "tv.danmaku.bili": "Entertainment",          # Bilibili (not on the US Play Store)
    "com.tencent.android.qqdownloader": "Utilities",   # 应用宝, an app store
}

def fold_play(c):
    if not c:
        return None
    return "Games" if c.startswith("GAME") else PLAY.get(c, "Other")


def system(pkg):
    for rx, cat in SYSTEM:
        if re.search(rx, pkg or ""):
            return cat
    return None


def resolve(pkg, play=None, android=None):
    """(iOS category, source)."""
    if pkg in OVERRIDES:
        return OVERRIDES[pkg], "fixed"
    s = system(pkg)
    if s:
        return s, "system"
    f = fold_play(play)
    if f:
        return f, "play"
    if android in ANDROID:
        return ANDROID[android], "android"
    return "Other", "none"


_play = None


def play_table(path=DATA):
    """{package: Play category} from the cache file ("" = no US store page)."""
    global _play
    if _play is None:
        _play = {}
        if os.path.exists(path):
            with open(path, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    _play[r["package"]] = r["play"]
    return _play


def category(pkg, android=None):
    """The iOS category of a package."""
    return resolve(pkg, play_table().get(pkg), android)[0]
