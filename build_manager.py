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
    # Tạo folder 'key' nằm trong project_dir theo sơ đồ
    key_dir = os.path.join(project_dir, "key")
    os.makedirs(key_dir, exist_ok=True)

    # Filename: 3 chữ cái đầu của project + _keystore
    prefix = name[:3]
    path = os.path.join(key_dir, f"{prefix}_keystore.jks")

    # Kiểm tra nếu đã có keystore thì bỏ qua (Đã có -> Build)
    if os.path.exists(path):
        return path

    # Lệnh tạo keystore mới nếu chưa có
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
        await bot.send_message(chat_id, f"🚀 Đang chuẩn bị Build AAB cho: {version}")

        # 1. Kiểm tra project đã có chưa, nếu chưa thì Clone
        if not os.path.isdir(project_dir):
            if not clone_repo(repo, project_dir):
                await bot.send_message(chat_id, "❌ Clone thất bại")
                return

        # 2. Pull code / Fetch branch mới nhất
        async for _ in run_cmd("git fetch --all --prune", project_dir):
            pass

        checkout_cmd = f"git checkout -B {version} origin/{version}"
        async for _ in run_cmd(checkout_cmd, project_dir): pass
        async for _ in run_cmd("git pull origin {version}", project_dir): pass

        # 3. Kiểm tra/Tạo Keystore & local.properties
        create_keystore(project_dir, name)
        create_local_properties(project_dir)

        # 4. Lệnh Build AAB (bundleRelease)
        cmd = "gradlew bundleRelease" if os.name == "nt" else "./gradlew bundleRelease"

        await bot.send_message(chat_id, "🛠 Đang thực thi lệnh Build AAB...")

        success = True
        logs = []
        async for line in run_cmd(cmd, project_dir):
            logs.append(line)
            if len(logs) > 200: logs.pop(0)
            if "FAILURE" in line: success = False

        if not success:
            # Gửi 40 dòng log cuối nếu lỗi
            await bot.send_message(chat_id, "❌ Build thất bại. Chi tiết lỗi:\n" + "\n".join(logs[-40:]))
            return

        # 5. Tìm và gửi file .aab
        aab_path = None
        for root, _, files in os.walk(project_dir):
            for f in files:
                if f.endswith(".aab"):
                    aab_path = os.path.join(root, f)
                    break

        # Trong build_manager.py, hàm build_project
        if aab_path:
            # Mở file để gửi
            with open(aab_path, "rb") as document:
                await bot.send_document(
                    chat_id=chat_id,
                    document=document,
                    caption=f"✅ Build AAB thành công: {version}",
                    read_timeout=900,   # Tăng thời gian chờ lên 10 phút (600s)
                    write_timeout=900,  # Đảm bảo đủ thời gian để upload file lớn
                    connect_timeout=90  # Thời gian kết nối ban đầu
                )
        else:
            await bot.send_message(chat_id, "❌ Build xong nhưng không tìm thấy file .aab")

    except Exception as e:
        await bot.send_message(chat_id, f"⚠️ Có lỗi xảy ra: {str(e)}")