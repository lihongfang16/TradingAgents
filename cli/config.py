CLI_CONFIG = {
    # Announcements
    "announcements_url": "https://api.tauric.ai/v1/announcements",
    "announcements_timeout": 1.0,
    "announcements_fallback": "[cyan]For more information, please visit[/cyan] [link=https://github.com/TauricResearch]https://github.com/TauricResearch[/link]",
    
    # A-share Configuration
    "a_share_enabled": True,
    "a_share_data_source": "ashare",  # Options: "ashare", "akshare", "baostock"
    "akshare_timeout": 30,
    "baostock_retry": 3,
    "ashare_preference": "sina",  # Options: "sina", "tencent"
}

# Validation options
A_SHARE_DATA_SOURCE_OPTIONS = ["ashare", "akshare", "baostock"]
ASHARE_PREFERENCE_OPTIONS = ["sina", "tencent"]
