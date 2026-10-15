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
# Chinese apps (10-15, David: on Daijun's OPPO "美团 is food ordering and delivery"): most are not on the US Play
# Store, or come back without a category, so they fell to Other. Their category as on the App Store (China),
# folded into iOS Screen Time's categories like the rest.
CN = {
    # Social
    "com.tencent.mm": "Social", "com.tencent.mobileqq": "Social", "com.tencent.tim": "Social",
    "com.sina.weibo": "Social", "com.sina.weibolite": "Social", "com.xingin.xhs": "Social", "com.zhihu.android": "Social",
    "com.douban.frodo": "Social", "com.immomo.momo": "Social", "com.p1.mobile.putong": "Social",
    # Entertainment: short video, video, music, live streams (抖音 / 快手 as TikTok on the App Store)
    "com.ss.android.ugc.aweme": "Entertainment", "com.ss.android.ugc.aweme.lite": "Entertainment",
    "com.ss.android.ugc.live": "Entertainment", "com.smile.gifmaker": "Entertainment", "com.kuaishou.nebula": "Entertainment",
    "com.tencent.weishi": "Entertainment", "com.ss.android.article.video": "Entertainment",
    "tv.danmaku.bili": "Entertainment", "com.qiyi.video": "Entertainment", "com.tencent.qqlive": "Entertainment",
    "com.youku.phone": "Entertainment", "com.hunantv.imgo.activity": "Entertainment",
    "com.tencent.qqmusic": "Entertainment", "com.netease.cloudmusic": "Entertainment", "com.kugou.android": "Entertainment",
    "cn.kuwo.player": "Entertainment", "com.ximalaya.ting.android": "Entertainment", "com.tencent.karaoke": "Entertainment",
    "com.duowan.kiwi": "Entertainment", "air.tv.douyu.android": "Entertainment",
    # Information & Reading: news, novels, car news
    "com.ss.android.article.news": "Information & Reading", "com.ss.android.article.lite": "Information & Reading",
    "com.tencent.news": "Information & Reading", "com.netease.newsreader.activity": "Information & Reading",
    "com.sohu.newsclient": "Information & Reading", "com.ifeng.news2": "Information & Reading",
    "com.dragon.read": "Information & Reading", "com.qq.reader": "Information & Reading",
    "com.chaozh.iReaderFree": "Information & Reading", "com.ss.android.auto": "Information & Reading",
    "com.cubic.autohome": "Information & Reading", "cn.xuexi.android": "Information & Reading",
    # Browser (David 10-14: a separate category on Android): search apps too
    "com.baidu.searchbox": "Browser", "com.baidu.searchbox.lite": "Browser", "com.tencent.mtt": "Browser",
    "com.UCMobile": "Browser", "com.quark.browser": "Browser", "com.sogou.activity.src": "Browser",
    # Shopping & Food: shopping, food delivery, reviews
    "com.sankuai.meituan": "Shopping & Food", "com.sankuai.meituan.takeoutnew": "Shopping & Food", "me.ele": "Shopping & Food",
    "com.dianping.v1": "Shopping & Food", "com.xunmeng.pinduoduo": "Shopping & Food", "com.taobao.taobao": "Shopping & Food",
    "com.tmall.wireless": "Shopping & Food", "com.jingdong.app.mall": "Shopping & Food", "com.taobao.idlefish": "Shopping & Food",
    "com.achievo.vipshop": "Shopping & Food", "com.wudaokou.hippo": "Shopping & Food",
    # Productivity & Finance: payment, banks, insurance, work, AI assistants, cloud storage
    "com.eg.android.AlipayGphone": "Productivity & Finance", "com.unionpay": "Productivity & Finance",
    "com.icbc": "Productivity & Finance", "com.chinamworld.main": "Productivity & Finance",
    "com.android.bankabc": "Productivity & Finance", "cmb.pb": "Productivity & Finance",
    "com.chinamworld.bocmbci": "Productivity & Finance", "com.pingan.carowner": "Productivity & Finance",
    "com.alibaba.android.rimet": "Productivity & Finance", "com.tencent.wework": "Productivity & Finance",
    "com.ss.android.lark": "Productivity & Finance", "com.tencent.wemeet.app": "Productivity & Finance",
    "cn.wps.moffice_eng": "Productivity & Finance", "com.baidu.netdisk": "Productivity & Finance",
    "com.larus.nova": "Productivity & Finance", "com.deepseek.chat": "Productivity & Finance",
    "com.moonshot.kimichat": "Productivity & Finance",
    # Travel: maps, ride hailing, trains, trips, car apps
    "com.autonavi.minimap": "Travel", "com.baidu.BaiduMap": "Travel", "com.tencent.map": "Travel",
    "com.sdu.didi.psnger": "Travel", "com.MobileTicket": "Travel", "ctrip.android.view": "Travel", "com.Qunar": "Travel",
    "com.changan.uni": "Travel",
    # Health & Fitness
    "com.gotokeep.keep": "Health & Fitness", "com.xiaomi.hm.health": "Health & Fitness", "com.mi.health": "Health & Fitness",
    "com.huawei.health": "Health & Fitness", "com.heytap.health": "Health & Fitness",
    # Education
    "com.youdao.dict": "Education", "com.zhilehuo.sqertongshizi": "Education", "com.fenbi.android.solar": "Education",
    # Utilities: government services, app stores, watch companions
    "com.tmri.app.main": "Utilities", "com.tencent.android.qqdownloader": "Utilities", "com.xtc.watch": "Utilities",
}

OVERRIDES = {
    **CN,
}

# Chinese games and study apps by publisher prefix, and the phone makers' own system apps (ColorOS / HeyTap,
# MIUI / HyperOS, EMUI / HarmonyOS, MagicOS, OriginOS): Utilities, except their music, video and health apps.
VENDOR = r"^com\.(oplus|coloros|heytap|oppo|nearme|miui|xiaomi|mi|huawei|hihonor|honor|vivo|bbk|iqoo|meizu)\."
SYSTEM_CN = [
    (r"^com\.tencent\.tmgp\.|^com\.miHoYo\.|^com\.hypergryph\.|^com\.tencent\.lolm$", "Games"),
    (r"^com\.zuoyebang\.|^com\.yuanfudao\.|^com\.fenbi\.", "Education"),
    (VENDOR + r".*(music|video|player|movie)", "Entertainment"),
    (VENDOR + r".*health", "Health & Fitness"),
    (VENDOR + r".*weather", "Information & Reading"),
    (VENDOR, "Utilities"),
]


def fold_play(c):
    if not c:
        return None
    return "Games" if c.startswith("GAME") else PLAY.get(c, "Other")


def system(pkg):
    for rx, cat in SYSTEM + SYSTEM_CN:
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
