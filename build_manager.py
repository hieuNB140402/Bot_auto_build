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


def get_required_jdk(project_dir):
    wrapper_path = os.path.join(project_dir, "gradle", "wrapper", "gradle-wrapper.properties")
    target_jdk = DEFAULT_JDK  # Mặc định sử dụng JBR của Android Studio

    if os.path.exists(wrapper_path):
        try:
            with open(wrapper_path, "r") as f:
                content = f.read()

                # Phân loại Gradle Version để mapping JDK
                # Gradle 8.10+ hỗ trợ Java 21/25/26 (Cần cẩn thận với lỗi Major version 69)
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

    # Kiểm tra thực tế thư mục JDK có tồn tại trên ổ đĩa không
    if not os.path.exists(target_jdk):
        print(f"⚠️ Cảnh báo: Không tìm thấy JDK tại {target_jdk}. Chuyển về DEFAULT_JDK.")
        return DEFAULT_JDK

    return target_jdk

def create_local_properties(project_dir):
    sdk = detect_android_sdk()
    jdk_path = get_required_jdk(project_dir)

    # Chuyển đổi đường dẫn để Gradle đọc được (Windows)
    sdk_clean = sdk.replace('\\', '/')
    jdk_clean = jdk_path.replace('\\', '/')

    with open(os.path.join(project_dir, "local.properties"), "w", encoding="utf-8") as f:
        f.write(f"sdk.dir={sdk_clean}\n")
        f.write(f"org.gradle.java.home={jdk_clean}\n")


# =========================
# KEYSTORE
# =========================
def create_keystore(project_dir, name):
    # Tạo folder 'key' nằm trong project_dir theo sơ đồ
    key_dir = os.path.join(project_dir, "key")
    os.makedirs(key_dir, exist_ok=True)

    # Filename: 5 chữ cái đầu của project + _keystore
    prefix = name[:5]
    path_jks = os.path.join(key_dir, f"{prefix}_keystore.jks")
    path_no_ext = os.path.join(key_dir, f"{prefix}_keystore")

    # ✅ Nếu tồn tại file .jks -> dùng luôn
    if os.path.exists(path_jks):
        return path_jks

    # ✅ Nếu tồn tại file không có extension -> dùng luôn
    if os.path.exists(path_no_ext):
        return path_no_ext

    # Lệnh tạo keystore mới nếu chưa có
    cmd = f'''
    keytool -genkey -v -keystore "{path_jks}"
    -storepass {KEYSTORE_PASSWORD}
    -alias {KEY_ALIAS}
    -keypass {KEY_PASSWORD}
    -keyalg RSA -keysize 2048 -validity 10000
    -dname "CN=Android,O=Dev,C=VN"
    '''

    subprocess.run(cmd, shell=True)
    return path_jks

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
    last_versions = sorted_versions[-3:]
    return last_versions


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
        # Lưu ý: Sửa f-string cho lệnh git pull để nhận diện đúng version
        async for _ in run_cmd("git fetch --all --prune", project_dir): pass

        checkout_cmd = f"git checkout -B {version} origin/{version}"
        async for _ in run_cmd(checkout_cmd, project_dir): pass

        pull_cmd = f"git pull origin {version}"
        async for _ in run_cmd(pull_cmd, project_dir): pass

        # 3. Khởi tạo cấu hình (Keystore & SDK/JDK)
        create_keystore(project_dir, name)
        create_local_properties(project_dir)

        # Lấy JDK path để ép vào lệnh build (đảm bảo không dùng JDK hệ thống)
        jdk_path = get_required_jdk(project_dir)
        jdk_clean = jdk_path.replace('\\', '/')

        # 4. Lệnh Build AAB (bundleRelease)
        # Ép Gradle sử dụng đúng JDK mong muốn qua tham số -D
        gradle_exe = "gradlew" if os.name == "nt" else "./gradlew"
        cmd = f'{gradle_exe} bundleRelease -Dorg.gradle.java.home="{jdk_clean}"'

        await bot.send_message(chat_id, f"🛠 Đang thực thi Build với JDK: {jdk_path}")

        success = True
        logs = []
        async for line in run_cmd(cmd, project_dir):
            logs.append(line)
            # In log ra console để bạn dễ theo dõi tiến độ
            print(f"[{name}] {line}")
            if len(logs) > 200: logs.pop(0)
            if "FAILURE" in line or "FAILED" in line: success = False

        if not success:
            # Gửi 40 dòng log cuối nếu lỗi
            await bot.send_message(chat_id, "❌ Build thất bại. Chi tiết lỗi:\n\n" + "\n".join(logs[-40:]))
            return

        # 5. Tìm và gửi file .aab
        aab_path = None
        for root, _, files in os.walk(os.path.join(project_dir, "app", "build", "outputs", "bundle", "release")):
            for f in files:
                if f.endswith(".aab"):
                    aab_path = os.path.join(root, f)
                    break

        # Nếu tìm ở thư mục chuẩn không thấy, quét toàn bộ project (dự phòng)
        if not aab_path:
            for root, _, files in os.walk(project_dir):
                if "build" in root and f.endswith(".aab"):
                    for f in files:
                        aab_path = os.path.join(root, f)
                        break

        if aab_path:
            with open(aab_path, "rb") as document:
                await bot.send_document(
                    chat_id=chat_id,
                    document=document,
                    caption=f"✅ Build AAB thành công: {version}\nProject: {name}",
                    read_timeout=900,
                    write_timeout=900,
                    connect_timeout=90
                )
        else:
            await bot.send_message(chat_id, "❌ Build báo SUCCESS nhưng không tìm thấy file .aab trong thư mục output.")

    except Exception as e:
        await bot.send_message(chat_id, f"⚠️ Có lỗi xảy ra trong quá trình Build: {str(e)}")

