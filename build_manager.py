import os
import asyncio
import subprocess
import json
from config import *

# =========================
# LOAD PROJECTS
# =========================
def load_projects():
    with open("projects.json", "r", encoding="utf-8") as f:
        return json.load(f)


# =========================
# RUN CMD
# =========================
async def run_cmd(cmd, cwd):
    process = await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )

    while True:
        line = await process.stdout.readline()
        if not line:
            break
        yield line.decode(errors="ignore").strip()

    await process.wait()


# =========================
# SDK DETECT
# =========================
def detect_android_sdk():
    if ANDROID_SDK and os.path.exists(ANDROID_SDK):
        return ANDROID_SDK

    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if sdk and os.path.exists(sdk):
        return sdk

    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        default = os.path.join(user_profile, "AppData", "Local", "Android", "Sdk")
        if os.path.exists(default):
            return default

    raise Exception("❌ Không tìm thấy Android SDK")


def create_local_properties(project_dir):
    sdk = detect_android_sdk()
    path = os.path.join(project_dir, "local.properties")

    with open(path, "w") as f:
        f.write(f"sdk.dir={sdk.replace('\\', '\\\\')}\n")


# =========================
# KEYSTORE
# =========================
def create_keystore(project_dir, project_name):
    key_dir = os.path.join(project_dir, "app", "key")
    os.makedirs(key_dir, exist_ok=True)

    prefix = project_name.split("_")[0]
    keystore_name = f"{prefix}_keystore.jks"
    keystore_path = os.path.join(key_dir, keystore_name)

    if os.path.exists(keystore_path):
        return keystore_path

    cmd = (
        f'keytool -genkey -v -keystore "{keystore_path}" '
        f'-storepass {KEYSTORE_PASSWORD} '
        f'-alias {KEY_ALIAS} '
        f'-keypass {KEY_PASSWORD} '
        f'-keyalg RSA -keysize 2048 -validity 10000 '
        f'-dname "CN=Android,O=Dev,C=VN"'
    )

    subprocess.run(cmd, shell=True)
    return keystore_path


# =========================
# GET VERSION
# =========================
async def get_versions(project_dir):
    versions = []

    async for _ in run_cmd("git fetch --all", project_dir):
        pass

    async for line in run_cmd("git tag", project_dir):
        if line:
            versions.append(line)

    return versions


# =========================
# BUILD
# =========================
async def build_project(bot, chat_id, project, version):
    name = project["name"]
    repo = project["repo"]

    project_dir = os.path.join(BASE_DIR, name)

    try:
        await bot.send_message(chat_id, "🚀 Bắt đầu build...")

        # clone nếu chưa có
        if not os.path.exists(project_dir):
            os.system(f"git clone {repo} {project_dir}")

        # checkout
        async for _ in run_cmd(f"git checkout {version}", project_dir):
            pass

        # keystore
        create_keystore(project_dir, name)

        # SDK
        create_local_properties(project_dir)

        # build
        gradle_cmd = "gradlew assembleRelease" if os.name == "nt" else "./gradlew assembleRelease"

        logs = []
        success = True

        async for line in run_cmd(gradle_cmd, project_dir):
            print(line)
            logs.append(line)

            if "FAILURE" in line or "FAILED" in line:
                success = False

        if not success:
            await bot.send_message(chat_id, "❌ Build thất bại\n" + "\n".join(logs[-40:]))
            return

        # tìm APK
        apk_path = None
        for root, _, files in os.walk(project_dir):
            for file in files:
                if file.endswith(".apk"):
                    apk_path = os.path.join(root, file)

        if apk_path:
            await bot.send_document(chat_id, open(apk_path, "rb"))
        else:
            await bot.send_message(chat_id, "⚠️ Không tìm thấy APK")

    except Exception as e:
        await bot.send_message(chat_id, f"❌ Lỗi: {str(e)}")