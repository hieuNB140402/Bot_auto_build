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
        f'-storepass {KEYSTORE_PASSWORD} -alias {target_alias} '
        f'-keypass {KEY_PASSWORD} -keyalg RSA -keysize 2048 -validity 10000 '
        f'-dname "CN=Android,O=Dev,C=VN" -storetype JKS'
    )
    subprocess.run(cmd, shell=True, capture_output=True)

    return path_jks

async def push_key_to_github(project_dir, version, key_path, name):
    """Commit và Push file keystore lên GitHub"""
    try:
        # Lấy tên file tương đối từ project_dir
        rel_key_path = os.path.relpath(key_path, project_dir)

        commands = [
            f'git add "{rel_key_path}"',
            f'git commit -m "chore: auto generate keystore for {name}"',
            f'git push origin {version}'
        ]

        print(f"⬆️ Đang push key lên GitHub branch {version}...")
        for cmd in commands:
            async for line in run_cmd(cmd, project_dir):
                print(f"[Git Push Key] {line}")
        return True
    except Exception as e:
        print(f"❌ Lỗi push key: {e}")
        return False

# =========================
# MAIN BUILD PROCESS
# =========================
def clear_aab_files(folder_path):
    import os

    if not os.path.isdir(folder_path):
        return

    for f in os.listdir(folder_path):
        file_path = os.path.join(folder_path, f)

        try:
            # ❗ chỉ xóa file .aab thật sự
            if os.path.isfile(file_path) and f.lower().endswith(".aab"):
                os.remove(file_path)
                print(f"🗑 Deleted: {file_path}")

        except Exception as e:
            print(f"⚠️ Không xóa được {file_path}: {e}")

def find_best_aab(project_dir):
    bundle_dir = os.path.join(project_dir, "app", "build", "outputs", "bundle")

    if not os.path.isdir(bundle_dir):
        return None

    candidates = []

    for root, _, files in os.walk(bundle_dir):
        for f in files:
            if not f.endswith(".aab"):
                continue

            name = f.lower()
            if any(x in name for x in ["debug", "universal", "test"]):
                continue
            if "release" not in name:
                continue

            full = os.path.join(root, f)
            try:
                mtime = os.path.getmtime(full)
            except:
                mtime = 0

            candidates.append((full, mtime))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


def wait_file_ready(path, timeout=20):
    start = time.time()
    last_size = -1

    while time.time() - start < timeout:
        if not os.path.exists(path):
            time.sleep(1)
            continue

        size = os.path.getsize(path)

        if size > 0 and size == last_size:
            return True

        last_size = size
        time.sleep(1)

    return False


def safe_copy(src, dst, retries=5):
    for i in range(retries):
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            return True
        except Exception as e:
            print(f"⚠️ Copy fail {i+1}: {e}")
            time.sleep(2)
    return False

def find_best_aab(project_dir):
    import os

    bundle_dir = os.path.join(project_dir, "app", "build", "outputs", "bundle")

    if not os.path.isdir(bundle_dir):
        print("❌ Bundle dir không tồn tại:", bundle_dir)
        return None

    valid_files = []

    for root, _, files in os.walk(bundle_dir):
        for f in files:
            if not f.endswith(".aab"):
                continue

            name = f.lower()
            full_path = os.path.join(root, f)

            # ❌ loại file không hợp lệ
            if any(x in name for x in ["debug", "universal", "test"]):
                continue

            # ✅ chỉ lấy release
            if "release" not in name:
                continue

            try:
                mtime = os.path.getmtime(full_path)
            except Exception:
                mtime = 0

            valid_files.append((full_path, mtime))

    if not valid_files:
        print("❌ Không có AAB hợp lệ")
        return None

    # lấy file mới nhất
    valid_files.sort(key=lambda x: x[1], reverse=True)

    best_file = valid_files[0][0]
    print("🎯 Selected AAB:", best_file)

    return best_file


async def build_project(bot, chat_id, project, version):
    import os, time

    name = project["name"]
    repo = project["repo"]
    project_dir = os.path.join(BASE_DIR, name)

    try:
        await bot.send_message(chat_id, f"🚀 Build: {name}\n🌿 Branch: {version}")

        # =========================
        # 1. CLONE + GIT
        # =========================
        if not os.path.isdir(project_dir):
            if not clone_repo(repo, project_dir):
                await bot.send_message(chat_id, "❌ Clone fail")
                return

        async for _ in run_cmd("git fetch --all --prune", project_dir): pass
        async for _ in run_cmd(f"git checkout -B {version} origin/{version}", project_dir): pass
        async for _ in run_cmd(f"git pull origin {version}", project_dir): pass

        # =========================
        # 2. CONFIG
        # =========================
        # Bước A: Tạo key nếu chưa có ở máy local
        actual_key_path = create_keystore(project_dir, name)
        create_local_properties(project_dir)

        # Bước B: Kiểm tra xem file key này đã được push lên GitHub chưa
        # Lấy đường dẫn tương đối để check với git (ví dụ: app/key/abc_keystore.jks)
        rel_key_path = os.path.relpath(actual_key_path, project_dir).replace("\\", "/")

        is_on_github = False
        async for line in run_cmd(f'git ls-files "{rel_key_path}"', project_dir):
            if rel_key_path in line:
                is_on_github = True
                break

        # Bước C: Nếu chưa có trên GitHub -> Thực hiện Push
        if not is_on_github:
            await bot.send_message(chat_id, "🔑 Key chưa có trên GitHub. Đang thực hiện Push...")
            success_push = await push_key_to_github(project_dir, version, actual_key_path, name)
            if success_push:
                await bot.send_message(chat_id, "✅ Đã push Key lên GitHub thành công.")
            else:
                await bot.send_message(chat_id, "⚠️ Push Key thất bại (Kiểm tra quyền ghi Repo).")
        else:
            print(f"ℹ️ Key {rel_key_path} đã tồn tại trên GitHub, bỏ qua bước push.")

        # Dọn dẹp build cũ
        build_dir = os.path.join(project_dir, "app", "build")
        if os.path.exists(build_dir):
            try: shutil.rmtree(build_dir)
            except: pass

        # =========================
        # 3. BUILD
        # =========================
        jdk = get_required_jdk(project_dir).replace("\\", "/")
        gradle = "gradlew" if os.name == "nt" else "./gradlew"

        cmd = f'{gradle} clean bundleRelease -Dorg.gradle.java.home="{jdk}" --no-daemon --max-workers=2'

        await bot.send_message(chat_id, "🛠 Building...")

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

        # =========================
        # 4. FIND AAB
        # =========================
        aab_path = find_best_aab(project_dir)

        if not aab_path:
            await bot.send_message(chat_id, "❌ Không tìm thấy AAB")
            return

        print("🎯 AAB:", aab_path)

        # =========================
        # 5. WAIT FILE READY
        # =========================
        if not wait_file_ready(aab_path):
            await bot.send_message(chat_id, "❌ File chưa sẵn sàng")
            return

        # =========================
        # 6. COPY
        # =========================
        backup_root = os.path.abspath("C:/APK_Build/SUCCESS_AAB")
        clear_aab_files(backup_root)
        filename = f"{name}_{version}_{int(time.time())}.aab"
        saved_path = os.path.join(backup_root, filename)

        if not safe_copy(aab_path, saved_path):
            await bot.send_message(chat_id, "❌ Copy fail")
            return

        size = os.path.getsize(saved_path) / (1024 * 1024)
        await bot.send_message(chat_id, f"✅ Done: {size:.2f} MB")

        # =========================
        # 7. UPLOAD SONG SONG 🚀
        # =========================
        await bot.send_message(chat_id, "☁️ Uploading...")

        async def upload_task():
            return await upload_to_gofile(saved_path)

        task = asyncio.create_task(upload_task())

        # vẫn giữ bot responsive
        while not task.done():
            await asyncio.sleep(3)

        link = task.result()

        if link:
            await bot.send_message(chat_id, f"🔗 {link}")
        else:
            await bot.send_message(chat_id, f"⚠️ Upload lỗi\n{saved_path}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        await bot.send_message(chat_id, f"⚠️ {str(e)}")