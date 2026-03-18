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
# CLONE
# =========================
def clone_repo(repo, project_dir, retry=3):
    for i in range(retry):
        print(f"🔄 Clone lần {i+1}")

        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", repo, project_dir],
                capture_output=True,
                text=True
            )

            print(result.stdout)
            print(result.stderr)

            if result.returncode == 0:
                subprocess.run(["git", "fetch", "--tags"], cwd=project_dir)
                return True

        except Exception as e:
            print(e)

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
# GET VERSION (FULL)
# =========================
async def get_versions(project):
    project_dir = project["dir"]

    if not os.path.exists(project_dir):
        return []

    branches = []
    tags = []

    async for line in run_cmd("git branch -r", project_dir):
        if "origin/" in line:
            branches.append(line.replace("origin/", "").strip())

    async for line in run_cmd("git tag", project_dir):
        if line:
            tags.append(line.strip())

    versions = list(set(branches + tags))
    return versions[:20]


# =========================
# BUILD
# =========================
async def build_project(bot, chat_id, project, version):
    name = project["name"]
    repo = project["repo"]
    project_dir = os.path.join(BASE_DIR, name)

    try:
        await bot.send_message(chat_id, "🚀 Start build")

        if not os.path.isdir(project_dir):
            if not clone_repo(repo, project_dir):
                await bot.send_message(chat_id, "❌ Clone fail")
                return

        async for _ in run_cmd(f"git checkout {version}", project_dir):
            pass

        create_keystore(project_dir, name)
        create_local_properties(project_dir)

        cmd = "gradlew assembleRelease" if os.name == "nt" else "./gradlew assembleRelease"

        logs = []
        success = True

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

        # tìm apk
        apk = None
        for root, _, files in os.walk(project_dir):
            for f in files:
                if f.endswith(".apk"):
                    apk = os.path.join(root, f)

        if apk:
            await bot.send_document(chat_id, open(apk, "rb"))
        else:
            await bot.send_message(chat_id, "Không tìm thấy APK")

    except Exception as e:
        await bot.send_message(chat_id, str(e))
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
# CLONE
# =========================
def clone_repo(repo, project_dir, retry=3):
    for i in range(retry):
        print(f"🔄 Clone lần {i+1}")

        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", repo, project_dir],
                capture_output=True,
                text=True
            )

            print(result.stdout)
            print(result.stderr)

            if result.returncode == 0:
                subprocess.run(["git", "fetch", "--tags"], cwd=project_dir)
                return True

        except Exception as e:
            print(e)

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
# GET VERSION (FULL)
# =========================
async def get_versions(project_dir):
    versions = []

    # ✅ fetch full data
    async for _ in run_cmd("git fetch --all --tags --prune", project_dir):
        pass

    # =====================
    # TAG
    # =====================
    async for line in run_cmd("git tag", project_dir):
        if line:
            versions.append(line)

    # =====================
    # BRANCH
    # =====================
    async for line in run_cmd("git branch -r", project_dir):
        line = line.strip()

        if "origin/" in line:
            b = line.replace("origin/", "")

            # ❌ bỏ HEAD
            if "HEAD" in b:
                continue

            versions.append(b)

    # ❗ remove duplicate
    versions = list(set(versions))

    # sort đẹp
    versions.sort(reverse=True)

    return versions


# =========================
# BUILD
# =========================
async def build_project(bot, chat_id, project, version):
    name = project["name"]
    repo = project["repo"]
    project_dir = os.path.join(BASE_DIR, name)

    try:
        await bot.send_message(chat_id, "🚀 Start build")

        if not os.path.isdir(project_dir):
            if not clone_repo(repo, project_dir):
                await bot.send_message(chat_id, "❌ Clone fail")
                return

        async for _ in run_cmd(f"git checkout {version}", project_dir):
            pass

        create_keystore(project_dir, name)
        create_local_properties(project_dir)

        cmd = "gradlew assembleRelease" if os.name == "nt" else "./gradlew assembleRelease"

        logs = []
        success = True

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

        # tìm apk
        apk = None
        for root, _, files in os.walk(project_dir):
            for f in files:
                if f.endswith(".apk"):
                    apk = os.path.join(root, f)

        if apk:
            await bot.send_document(chat_id, open(apk, "rb"))
        else:
            await bot.send_message(chat_id, "Không tìm thấy APK")

    except Exception as e:
        await bot.send_message(chat_id, str(e))