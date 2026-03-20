import os
import asyncio
import subprocess
import json
import shutil
import re  # Thêm thư viện regex để tìm kiếm Alias
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
    if ANDROID_SDK and os.path.exists(ANDROID_SDK):
        return ANDROID_SDK
    user = os.environ.get("USERPROFILE")
    if user:
        sdk = os.path.join(user, "AppData", "Local", "Android", "Sdk")
        if os.path.exists(sdk): return sdk
    raise Exception("Không tìm thấy Android SDK")

def get_required_jdk(project_dir):
    wrapper_path = os.path.join(project_dir, "gradle", "wrapper", "gradle-wrapper.properties")
    target_jdk = DEFAULT_JDK
    if os.path.exists(wrapper_path):
        try:
            with open(wrapper_path, "r") as f:
                content = f.read()
                if "gradle-8.1" in content or "gradle-9" in content:
                    target_jdk = JDK_MAP.get("21", DEFAULT_JDK)
                elif "gradle-8" in content:
                    target_jdk = JDK_MAP.get("17", DEFAULT_JDK)
                elif "gradle-7" in content:
                    target_jdk = JDK_MAP.get("11", DEFAULT_JDK)
                elif "gradle-5" in content or "gradle-6" in content:
                    target_jdk = JDK_MAP.get("8", DEFAULT_JDK)
        except Exception as e:
            print(f"⚠️ Lỗi khi đọc gradle-wrapper: {e}")

    if not os.path.exists(target_jdk): return DEFAULT_JDK
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
# KEYSTORE LOGIC (CHỐNG GHI ĐÈ & TỰ NHẬN ALIAS)
# =========================
def get_alias_from_gradle(project_dir):
    """Quét build.gradle để lấy keyAlias thực tế (ví dụ: keytore)"""
    gradle_path = os.path.join(project_dir, "app", "build.gradle")
    if os.path.exists(gradle_path):
        try:
            with open(gradle_path, "r", encoding="utf-8") as f:
                content = f.read()
                # Tìm keyAlias "..." hoặc keyAlias '...'
                match = re.search(r'keyAlias\s+["\'](.+?)["\']', content)
                if match:
                    return match.group(1).strip()
        except: pass
    return KEY_ALIAS # Trả về từ config.py nếu không tìm thấy

def create_keystore(project_dir, name):
    key_dir = os.path.join(project_dir, "app", "key")
    os.makedirs(key_dir, exist_ok=True)

    prefix = name[:5]
    path_jks = os.path.join(key_dir, f"{prefix}_keystore.jks")
    path_no_ext = os.path.join(key_dir, f"{prefix}_keystore")

    # 🛑 CƠ CHẾ CHỐNG GHI ĐÈ: Nếu file đã tồn tại (dù có đuôi hay không), dùng luôn
    if os.path.exists(path_jks):
        print(f"✅ Đã có Keystore: {path_jks}. Bỏ qua bước tạo mới để bảo vệ Key cũ.")
        return path_jks
    if os.path.exists(path_no_ext):
        print(f"✅ Đã có Keystore (no ext): {path_no_ext}. Bỏ qua bước tạo mới.")
        return path_no_ext

    # Lấy Alias thực tế từ Gradle để tạo cho chuẩn
    target_alias = get_alias_from_gradle(project_dir)
    print(f"🔑 Đang tạo Keystore mới với Alias: {target_alias}")

    jdk_path = get_required_jdk(project_dir)
    keytool_exe = os.path.join(jdk_path, "bin", "keytool.exe") if os.name == "nt" else "keytool"

    cmd = (
        f'"{keytool_exe}" -genkey -v -keystore "{path_jks}" '
        f'-storepass {KEYSTORE_PASSWORD} '
        f'-alias {target_alias} '
        f'-keypass {KEY_PASSWORD} '
        f'-keyalg RSA -keysize 2048 -validity 10000 '
        f'-dname "CN=Android,O=Dev,C=VN" -storetype JKS'
    )

    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Lỗi keytool: {result.stderr}")
        else:
            print(f"✨ Tạo Keystore thành công!")
    except Exception as e:
        print(f"❌ Exception tạo key: {str(e)}")

    return path_jks

# =========================
# MAIN BUILD PROCESS
# =========================
async def build_project(bot, chat_id, project, version):
    name = project["name"]
    repo = project["repo"]
    project_dir = os.path.join(BASE_DIR, name)

    # Đường dẫn tương đối để Git add (quan trọng)
    prefix = name[:5]
    key_rel_path = f"app/key/{prefix}_keystore.jks"
    key_full_path = os.path.join(project_dir, "app", "key", f"{prefix}_keystore.jks")

    # Kiểm tra key tồn tại TRƯỚC khi làm gì cả
    key_existed_before = os.path.exists(key_full_path) or os.path.exists(os.path.join(project_dir, "app", "key", f"{prefix}_keystore"))

    try:
        await bot.send_message(chat_id, f"🚀 Đang chuẩn bị Build AAB cho: {version}")

        if not os.path.isdir(project_dir):
            if not clone_repo(repo, project_dir):
                await bot.send_message(chat_id, "❌ Clone thất bại")
                return

        async for _ in run_cmd("git fetch --all --prune", project_dir): pass
        async for _ in run_cmd(f"git checkout -B {version} origin/{version}", project_dir): pass
        async for _ in run_cmd(f"git pull origin {version}", project_dir): pass

        # Cấu hình môi trường
        create_keystore(project_dir, name)
        create_local_properties(project_dir)

        # Clean build folder thủ công (Fix Windows Lock)
        app_build_dir = os.path.join(project_dir, "app", "build")
        if os.path.exists(app_build_dir):
            try: shutil.rmtree(app_build_dir)
            except: pass

        jdk_path = get_required_jdk(project_dir)
        jdk_clean = jdk_path.replace('\\', '/')
        gradle_exe = "gradlew" if os.name == "nt" else "./gradlew"

        # Lệnh build chính thức
        cmd = f'{gradle_exe} clean bundleRelease -Dorg.gradle.java.home="{jdk_clean}" --no-daemon --stacktrace'

        await bot.send_message(chat_id, f"🛠 Đang thực thi Build...")

        success = True
        logs = []
        async for line in run_cmd(cmd, project_dir):
            logs.append(line)
            print(f"[{name}] {line}")
            if "BUILD FAILED" in line.upper() or "FAILURE" in line.upper(): success = False

        if not success:
            await bot.send_message(chat_id, "❌ Build thất bại:\n\n" + "\n".join(logs[-25:]))
            return

        # --- LOGIC PUSH KEY NẾU MỚI TẠO ---
        if not key_existed_before and os.path.exists(key_full_path):
            print(f"📦 Đang đẩy Key mới lên Git...")
            # Sử dụng dấu / cho Git trên Windows
            git_key_path = key_rel_path.replace('\\', '/')
            git_cmds = [
                f'git add "{git_key_path}"',
                'git commit -m "Push key"',
                f'git push origin {version}'
            ]
            for g_cmd in git_cmds:
                p = await asyncio.create_subprocess_shell(g_cmd, cwd=project_dir)
                await p.wait()
            await bot.send_message(chat_id, f"✅ Đã tự động Push Key mới lên branch {version}")

        # --- GỬI FILE AAB ---
        aab_path = None
        target_output = os.path.join(project_dir, "app", "build", "outputs", "bundle", "release")
        if os.path.exists(target_output):
            for f in os.listdir(target_output):
                if f.endswith(".aab"):
                    aab_path = os.path.join(target_output, f)
                    break

        if aab_path:
            with open(aab_path, "rb") as document:
                await bot.send_document(
                    chat_id=chat_id, document=document,
                    caption=f"✅ Build AAB thành công: {version}\nProject: {name}",
                    read_timeout=1000, write_timeout=1000
                )
        else:
            await bot.send_message(chat_id, "❌ Build xong nhưng không thấy file .aab.")

    except Exception as e:
        await bot.send_message(chat_id, f"⚠️ Lỗi hệ thống: {str(e)}")