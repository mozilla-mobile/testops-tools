"""Feature taxonomy shared by Android and iOS TestRail cases.

A case maps to the first feature whose substrings appear in its section name
or title (case-insensitive), so order matters: put more specific features
first. Anything that matches nothing is "Uncategorised".

Only these feature names ever leave the collector. Section names and titles
stay in memory, so this list is also the allow-list of what the dashboard can
show.
"""

UNCATEGORISED = "Uncategorised"

# (feature_label, list of case-insensitive substrings that map to this feature)
FEATURES = [
    ("Onboarding",                 ["onboarding", "brand refresh", "continuous onboarding",
                                    "terms of use", "make default browser", "welcome", "juno"]),
    ("Search & Address bar",        ["search", "url toolbar", "url bar", "address bar", "autocomplete",
                                    "trending", "zero search", "suggest"]),
    ("Toolbar",                     ["toolbar", "navigation toolbar", "url toolbar", "menu bar"]),
    ("Homepage",                    ["homepage", "home screen", "top sites", "shortcuts", "jump back",
                                    "pocket", "sponsored", "recent", "wallpapers"]),
    ("Tabs · general",              ["tabbed browsing", "top tabs", "adding a new tab",
                                    "normal browsing", "tab tray", "tab counter", "tab drawer",
                                    "swipe tabs", "recently closed", "tab groups", "collections",
                                    "task continuity"]),
    ("Tabs · private",              ["private browsing", "private tab"]),
    ("Bookmarks",                   ["bookmark"]),
    ("History",                     ["history"]),
    ("Reading List",                ["reading list"]),
    ("Downloads",                   ["download"]),
    ("Passwords / Logins",          ["password", "login", "autofill password"]),
    ("Autofill · Addresses",        ["address autofill", "addresses"]),
    ("Autofill · Credit Cards",     ["credit card", "credit cards"]),
    ("Sharing",                     ["share", "sharing"]),
    ("Settings",                    ["setting"]),
    ("Site permissions",            ["permission", "site setting", "cookie banner",
                                    "fingerprinting"]),
    ("Tracking Protection / Privacy", ["tracking protection", "etp", "global privacy",
                                        "unified trust", "https-only"]),
    ("Extensions / Add-ons",        ["extension", "add-on", "addon"]),
    ("Translations",                ["translation"]),
    ("Nimbus / Experiments / Messaging", ["nimbus", "microsurvey", "experiment", "messaging",
                                            "engagement notification", "cfr"]),
    ("Notifications",               ["notification"]),
    ("Widgets",                     ["widget"]),
    ("Custom tabs / PWA",           ["custom tab", "pwa", "web app"]),
    ("PDF / Reader mode",           ["pdf", "reader"]),
    ("Deep links / URI handling",   ["deep link", "deeplink", "uri", "abouturi"]),
    ("Sync / FxA",                  ["sync", "fxa", "firefox account", "ff desktop app-> ff ios app",
                                    "dau ping"]),
    ("Web content / Text",          ["text selection", "text fragment", "web control", "webpage",
                                    "website", "layout", "long tap"]),
    ("Crashes / Error pages",       ["crash", "error page", "browsing error"]),
    ("Media",                       ["media", "3d model"]),
    ("Web compat / Reporting",      ["report broken site", "webcompat", "broken site"]),
    ("Search engines",              ["search engine", "third party search"]),
    ("Accessibility",               ["accessibility", "voiceover"]),
    ("Zoom / Text size",            ["zoom", "text size"]),
    ("Find in page",                ["find in page", "find in"]),
    ("Firefox Suggest / Merino",    ["firefox suggest", "merino"]),
    ("Multi-window / iPad",         ["multi-window", "multiwindow", "portrait mode",
                                    "landscape mode", "ipad"]),
    ("Screenshots / Widget",        ["screenshot"]),
    ("Sponsored / Ads",             ["sponsored", "ads"]),
    ("Keyboard shortcuts",          ["keyboard shortcut"]),
    ("Site view / Rendering",       ["website view", "layout & rendering"]),
    ("Password generator",          ["password generator"]),
    ("Contextual hints (CFR)",      ["contextual", "cfr"]),
    ("Nightmode / Themes",          ["nightmode", "night mode", "dark mode", "theme", "appearance"]),
    ("Clipboard / Copied links",    ["clipboard", "copied link"]),
    ("Data management / Storage",   ["data management", "storage", "clear private data",
                                     "clear browsing", "cookie persistence"]),
    ("Desktop mode",                ["desktop mode", "desktop site", "request desktop"]),
    ("Long press / Context menu",   ["long press", "long-press", "context menu", "photon"]),
    ("Print",                       ["print"]),
    ("Firefox account push",        ["push", "fxa account"]),
    ("Delete browsing data",        ["delete browsing"]),
    ("Debug / dev settings",        ["debug", "developer"]),
    # additions after first review of uncategorised sections
    ("Menu / three-dot menu",       ["three-dot", "menu button", "main menu", "more sub-list",
                                    "menu persistency", "about firefox"]),
    ("Send tab / Pairing",          ["send tab", "send tabs", "pairing"]),
    ("Splash / App icon",           ["splash", "app icon", "homescreen launcher"]),
    ("Inactive tabs",               ["inactive tab"]),
    ("Open links in apps",          ["open links in apps", "external link", "open link"]),
    ("Homepage · Stories / Discover", ["stories", "story card", "discover more", "all stories"]),
    ("Autoplay",                    ["autoplay"]),
    ("Summarizer / AI",             ["summariz", "shake to", "ai enhancement", "block ai"]),
    ("Account management",          ["account management", "acoount management", "user not logged"]),
    ("Load / Rendering / UI misc",  ["load bar", "loading", "swiping between", "layout & rendering",
                                     "general ui", "ui/animation"]),
    ("Set as default browser",      ["set as default"]),
    ("Relay (out of scope)",        ["relay"]),
]

FEATURE_NAMES = [name for name, _ in FEATURES]


def classify(section, title=""):
    """Return the first matching feature, or UNCATEGORISED."""
    text = f"{section} {title}".lower()
    for name, patterns in FEATURES:
        if any(p in text for p in patterns):
            return name
    return UNCATEGORISED
