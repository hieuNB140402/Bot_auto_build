import os
import asyncio
import subprocess
import json
import shutil
from config import *


def load_projects():
    with open("projects.json", "r", encoding="utf-8") as f:
        return json.load(f)


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
# CLONE FULL
# =========================
# Trong build_manager.py
def clone_repo(repo, project_dir, retry=3):
    for i in range(retry):
        try:
            # Clone repo
            result = subprocess.run(
                ["git", "clone", repo, project_dir],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                # Ép fetch toàn bộ branch từ remote về local tracking
                subprocess.run([
                    "git", "fetch", "--all", "--prune"
                ], cwd=project_dir)
                return True

        except Exception as e:
            print(f"Lỗi clone: {e}")

        shutil.rmtree(project_dir, ignore_errors=True)
    return False


# =========================
# SDK
# =========================
def detect_android_sdk():
    if ANDROID_SDK and os.path.exists(ANDROID_SDK):
        return ANDROID_SDK

    user = os.environ.get("USERPROFILE")
    if user:
        sdk = os.path.join(user, "AppData", "Local", "Android", "Sdk")
        if os.path.exists(sdk):
            return sdk

    raise Exception("Không tìm thấy Android SDK")


def create_local_properties(project_dir):
    sdk = detect_android_sdk()
    with open(os.path.join(project_dir, "local.properties"), "w") as f:
        f.write(f"sdk.dir={sdk.replace('\\', '\\\\')}\n")


# =========================
# KEYSTORE
# =========================
def create_keystore(project_dir, name):
    key_dir = os.path.join(project_dir, "app", "key")
    os.makedirs(key_dir, exist_ok=True)

    prefix = name.split("_")[0]
    path = os.path.join(key_dir, f"{prefix}_keystore.jks")

    if os.path.exists(path):
        return path

    cmd = f'''
    keytool -genkey -v -keystore "{path}"
    -storepass {KEYSTORE_PASSWORD}
    -alias {KEY_ALIAS}
    -keypass {KEY_PASSWORD}
    -keyalg RSA -keysize 2048 -validity 10000
    -dname "CN=Android,O=Dev,C=VN"
    '''

    subprocess.run(cmd, shell=True)
    return path


# =========================
# GET ALL BRANCH (git branch -a)
# =========================
# Trong build_manager.py
async def get_versions(project_dir):
    versions = set() # Dùng set để tránh trùng lặp

    # Cập nhật danh sách branch mới nhất từ server
    async for _ in run_cmd("git fetch --all --prune", project_dir):
        pass

    # Lấy danh sách branch từ remote (origin)
    async for line in run_cmd("git branch -r", project_dir):
        line = line.strip()

        # Bỏ qua các dòng trống hoặc con trỏ HEAD
        if not line or "->" in line:
            continue

        # Xóa tiền tố 'origin/' để lấy tên branch thuần túy
        clean_name = line.replace("origin/", "")
        versions.add(clean_name)

    # Lấy cả các branch đã có ở local (nếu có)
    async for line in run_cmd("git branch", project_dir):
        line = line.strip().replace("*", "").strip()
        if line:
            versions.add(line)

    sorted_versions = sorted(list(versions))
    return sorted_versions


# =========================
# BUILD
# =========================
async def build_project(bot, chat_id, project, version):
    name = project["name"]
    repo = project["repo"]
    project_dir = os.path.join(BASE_DIR, name)

    try:
        await bot.send_message(chat_id, f"🚀 Build: {version}")

        if not os.path.isdir(project_dir):
            if not clone_repo(repo, project_dir):
                await bot.send_message(chat_id, "❌ Clone fail")
                return

        # fetch latest
        async for _ in run_cmd("git fetch --all --prune", project_dir):
            pass

        # checkout từ remote
        checkout_cmd = f"git checkout -B {version} origin/{version}"

        async for line in run_cmd(checkout_cmd, project_dir):
            print(line)

        # pull
        async for line in run_cmd("git pull", project_dir):
            print(line)

        create_keystore(project_dir, name)
        create_local_properties(project_dir)

        cmd = "gradlew assembleRelease" if os.name == "nt" else "./gradlew assembleRelease"

        success = True
        logs = []

        async for line in run_cmd(cmd, project_dir):
            print(line)
            logs.append(line)

            if len(logs) > 200:
                logs.pop(0)

            if "FAILURE" in line:
                success = False

        if not success:
            await bot.send_message(chat_id, "\n".join(logs[-40:]))
            return

        apk = None
        for root, _, files in os.walk(project_dir):
            for f in files:
                if f.endswith(".apk"):
                    apk = os.path.join(root, f)

        if apk:
            await bot.send_document(chat_id, open(apk, "rb"))
        else:
            await bot.send_message(chat_id, "❌ Không tìm thấy APK")

    except Exception as e:
        await bot.send_message(chat_id, str(e))