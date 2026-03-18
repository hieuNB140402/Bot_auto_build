import os
# Telegram Bot Token
TOKEN = "8669206541:AAEiaaMWWpKHi2sdgV07zq84MK4Deiaf1hs"

# Thư mục chứa source build
BASE_DIR = "builds"

# Keystore config
KEYSTORE_PASSWORD = "lvtapp@123"
KEY_ALIAS = "keystore"
KEY_PASSWORD = "lvtapp@123"

# Android SDK (optional - nếu muốn fix cứng thì set ở đây)
ANDROID_SDK = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")