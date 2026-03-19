import os
# Telegram Bot Token
TOKEN = "8669206541:AAEiaaMWWpKHi2sdgV07zq84MK4Deiaf1hs"

# Thư mục chứa source build
BASE_DIR = r"C:\APK Build"

# Keystore config
KEYSTORE_PASSWORD = "lvtapp@123"
KEY_ALIAS = "keystore"
KEY_PASSWORD = "lvtapp@123"

JDK_MAP = {
    "8": r"C:\Program Files\Java\jdk1.8.0_481",
    "11": r"C:\Program Files\Java\jdk-11.0.30",
    "17": r"C:\Program Files\Java\jdk-17.0.18",
    "21": r"C:\Program Files\Java\jdk-21.0.10",
    "25": r"C:\Program Files\Java\jdk-25",
    "26": r"C:\Program Files\Java\jdk-26"
}
DEFAULT_JDK = r"C:\Program Files\Android\Android Studio\jbr"

# Android SDK (optional - nếu muốn fix cứng thì set ở đây)
ANDROID_SDK = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")