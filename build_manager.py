import os
import asyncio
import subprocess
import json
import shutil
import re
import time
import aiohttp
from config import *

# =========================
# HELPER: UPLOAD DỰ PHÒNG
# =========================
async def upload_to_gofile(file_path):
    """Upload file lên Gofile.io nếu Telegram bị ReadError"""
    try:
        async with aiohttp.ClientSession() as session:
            # 1. Lấy server upload
            async with session.get('https://api.gofile.io/servers') as resp:
                if resp.status != 200: return None
                data = await resp.json()
                server = data['data']['servers'][0]['name']

            # 2. Upload thực tế
            with open(file_path, 'rb') as f:
                form_data = aiohttp.FormData()
                form_data.add_field('file', f)
                async with session.post(f'https://{server}.gofile.io/contents/uploadfile', data=form_data) as resp:
                    result = await resp.json()
                    if result['status'] == 'ok':
                        return result['data']['downloadPage']
    except Exception as e:
        print(f"❌ Lỗi Gofile API: {e}")
    return None

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
# GIT HELPERS
# =========================
def clone_repo(repo, project_dir, retry=3):
    for i in range(retry):
        try:
            result = subprocess.run(
                ["git", "clone", repo, project_dir],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                subprocess.run(["git", "fetch", "--all", "--prune"], cwd=project_dir)
                return True
        except Exception as e:
            print(f"Lỗi clone: {e}")
        shutil.rmtree(project_dir, ignore_errors=True)
    return False

async def get_versions(project_dir):
    versions = set()
    async for _ in run_cmd("git fetch --all --prune", project_dir): pass
    async for line in run_cmd("git branch -r", project_dir):
        line = line.strip()
        if not line or "->" in line: continue
        clean_name = line.replace("origin/", "")
        versions.add(clean_name)
    async for line in run_cmd("git branch", project_dir):
        line = line.strip().replace("*", "").strip()
        if line: versions.add(line)

    sorted_versions = sorted(list(versions))
    return sorted_versions[-3:]

# =========================
# SDK & JDK CONFIG
# =========================
def detect_android_sdk():
    if 'ANDROID_SDK' in globals() and ANDROID_SDK and os.path.exists(ANDROID_SDK):
        return ANDROID_SDK
    user = os.environ.get("USERPROFILE")
    if user:
        sdk = os.path.join(user, "AppData", "Local", "Android", "Sdk")
        if os.path.exists(sdk): return sdk
    raise Exception("Không tìm thấy Android SDK")

def get_required_jdk(project_dir):
    wrapper_path = os.path.join(project_dir, "gradle", "wrapper", "gradle-wrapper.properties")
    target_jdk = JDK_MAP.get("17") # Mặc định
    if os.path.exists(wrapper_path):
        try:
            with open(wrapper_path, "r") as f:
                content = f.read()
                if any(x in content for x in ["gradle-8.10", "gradle-8.11", "gradle-8.13", "gradle-9"]):
                    target_jdk = JDK_MAP.get("21")
                elif "gradle-8" in content:
                    target_jdk = JDK_MAP.get("17")
                elif "gradle-7" in content:
                    target_jdk = JDK_MAP.get("11")
        except: pass
    return target_jdk

def create_local_properties(project_dir):
    sdk = detect_android_sdk()
    jdk_path = get_required_jdk(project_dir)
    sdk_clean = sdk.replace('\\', '/')
    jdk_clean = jdk_path.replace('\\', '/')
    with open(os.path.join(project_dir, "local.properties"), "w", encoding="utf-8") as f:
        f.write(f"sdk.dir={sdk_clean}\n")
        f.write(f"org.gradle.java.home={jdk_clean}\n")

# =========================
# KEYSTORE LOGIC
# =========================
def get_alias_from_gradle(project_dir):
    gradle_path = os.path.join(project_dir, "app", "build.gradle")
    if os.path.exists(gradle_path):
        try:
            with open(gradle_path, "r", encoding="utf-8") as f:
                content = f.read()
                match = re.search(r'keyAlias\s+["\'](.+?)["\']', content)
                if match: return match.group(1).strip()
        except: pass
    return KEY_ALIAS

def create_keystore(project_dir, name):
    key_dir = os.path.join(project_dir, "app", "key")
    os.makedirs(key_dir, exist_ok=True)
    prefix = name[:5]
    path_jks = os.path.join(key_dir, f"{prefix}_keystore.jks")
    path_no_ext = os.path.join(key_dir, f"{prefix}_keystore")

    if os.path.exists(path_jks): return path_jks
    if os.path.exists(path_no_ext): return path_no_ext

    target_alias = get_alias_from_gradle(project_dir)
    jdk_path = get_required_jdk(project_dir)
    keytool_exe = os.path.join(jdk_path, "bin", "keytool.exe") if os.name == "nt" else "keytool"

    cmd = (
        f'"{keytool_exe}" -genkey -v -keystore "{path_jks}" '
        f'-storepass {KEY_STORE_PASSWORD} -alias {target_alias} '
        f'-keypass {KEY_PASSWORD} -keyalg RSA -keysize 2048 -validity 10000 '
        f'-dname "CN=Android,O=Dev,C=VN" -storetype JKS'
    )
    subprocess.run(cmd, shell=True, capture_output=True)
    return path_jks

# =========================
# MAIN BUILD PROCESS
# =========================
async def build_project(bot, chat_id, project, version):
    name = project["name"]
    repo = project["repo"]
    project_dir = os.path.join(BASE_DIR, name)
    prefix = name[:5]

    key_rel_path = f"app/key/{prefix}_keystore.jks"
    key_full_path = os.path.join(project_dir, key_rel_path)

    try:
        await bot.send_message(chat_id, f"🚀 [Server] Bắt đầu Build AAB: {name}\n🌿 Branch: {version}")

        # 1. Clone nếu chưa có
        if not os.path.isdir(project_dir):
            if not clone_repo(repo, project_dir):
                await bot.send_message(chat_id, "❌ Clone thất bại")
                return

        # 2. Checkout + pull
        async for _ in run_cmd("git fetch --all --prune", project_dir): pass
        async for _ in run_cmd(f"git checkout -B {version} origin/{version}", project_dir): pass
        async for _ in run_cmd(f"git pull origin {version}", project_dir): pass

        # 3. Keystore + config
        create_keystore(project_dir, name)
        create_local_properties(project_dir)

        # Xóa build cũ
        app_build_dir = os.path.join(project_dir, "app", "build")
        if os.path.exists(app_build_dir):
            try:
                shutil.rmtree(app_build_dir)
            except:
                pass

        # 4. Build
        jdk_path = get_required_jdk(project_dir).replace('\\', '/')
        gradle_exe = "gradlew" if os.name == "nt" else "./gradlew"

        cmd = (
            f'{gradle_exe} clean bundleRelease '
            f'-Dorg.gradle.java.home="{jdk_path}" '
            f'--no-daemon --max-workers=2 --stacktrace'
        )

        await bot.send_message(chat_id, "🛠 Đang build (15-20 phút)...")

        success = True
        start_time = time.time()
        last_heartbeat = start_time

        async for line in run_cmd(cmd, project_dir):
            print(f"[{name}] {line}")

            now = time.time()
            if now - last_heartbeat > 300:
                try:
                    await bot.send_message(
                        chat_id,
                        f"⏳ Vẫn đang build [{name}]... ({int((now-start_time)/60)} phút)"
                    )
                    last_heartbeat = now
                except:
                    pass

            if "BUILD FAILED" in line.upper() or "FAILURE" in line.upper():
                success = False

        if not success:
            await bot.send_message(chat_id, "❌ Build thất bại!")
            return

        # 5. Tìm file AAB
        aab_path = None
        search_paths = [
            os.path.join(project_dir, "app", "build", "outputs", "bundle", "release"),
            os.path.join(project_dir, "build", "outputs", "bundle", "release")
        ]

        for p in search_paths:
            if os.path.exists(p):
                for f in os.listdir(p):
                    if f.endswith(".aab"):
                        aab_path = os.path.join(p, f)
                        break
            if aab_path:
                break

        if not aab_path or not os.path.exists(aab_path):
            await bot.send_message(chat_id, "❌ Không tìm thấy file AAB")
            return

        # 6. Copy file
        backup_root = "C:/APK Build/SUCCESS_AAB"
        os.makedirs(backup_root, exist_ok=True)

        final_filename = f"{name}_{version}_{int(time.time())}.aab"
        saved_path = os.path.join(backup_root, final_filename)

        try:
            shutil.copy2(aab_path, saved_path)
        except Exception as e:
            await bot.send_message(chat_id, f"⚠️ Lỗi copy file: {e}")
            return

        file_size_mb = os.path.getsize(saved_path) / (1024 * 1024)

        await bot.send_message(chat_id, f"✅ Build xong ({file_size_mb:.2f} MB)")

        # =========================
        # ✅ CHỈ UPLOAD SERVER
        # =========================
        await bot.send_message(chat_id, "☁️ Đang upload lên server...")

        link = await upload_to_gofile(saved_path)

        if link:
            await bot.send_message(chat_id, f"🔗 LINK TẢI:\n{link}")
        else:
            await bot.send_message(chat_id, f"⚠️ Upload server lỗi\n📂 File local:\n`{saved_path}`")

    except Exception as e:
        import traceback
        traceback.print_exc()
        await bot.send_message(chat_id, f"⚠️ Lỗi hệ thống: {str(e)}")