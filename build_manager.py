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
    # 1. Tạo folder 'key' nằm trong project_dir/app theo sơ đồ mong muốn
    # Cấu trúc: [Project_Dir]\app\key
    key_dir = os.path.join(project_dir, "app", "key")
    os.makedirs(key_dir, exist_ok=True)

    # 2. Định nghĩa tên file dựa trên 5 chữ cái đầu
    prefix = name[:5]
    path_jks = os.path.join(key_dir, f"{prefix}_keystore.jks")
    path_no_ext = os.path.join(key_dir, f"{prefix}_keystore")

    # ✅ Kiểm tra nếu tồn tại file .jks -> dùng luôn
    if os.path.exists(path_jks):
        print(f"✅ Đã tìm thấy keystore: {path_jks}")
        return path_jks

    # ✅ Kiểm tra nếu tồn tại file không có extension -> dùng luôn
    if os.path.exists(path_no_ext):
        print(f"✅ Đã tìm thấy keystore (no ext): {path_no_ext}")
        return path_no_ext

    # 3. Lệnh tạo keystore mới (viết trên 1 dòng để tránh lỗi lệnh cmd)
    print(f"🔑 Không tìm thấy key, đang tạo mới tại: {path_jks}")

    # Lấy đường dẫn JDK để gọi keytool chính xác (tránh lỗi keytool not recognized)
    jdk_path = get_required_jdk(project_dir)
    keytool_exe = os.path.join(jdk_path, "bin", "keytool.exe") if os.name == "nt" else "keytool"

    cmd = (
        f'"{keytool_exe}" -genkey -v -keystore "{path_jks}" '
        f'-storepass {KEYSTORE_PASSWORD} '
        f'-alias {KEY_ALIAS} '
        f'-keypass {KEY_PASSWORD} '
        f'-keyalg RSA -keysize 2048 -validity 10000 '
        f'-dname "CN=Android,O=Dev,C=VN" -storetype JKS'
    )

    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Lỗi thực thi keytool: {result.stderr}")
        else:
            print(f"✨ Tạo Keystore mới thành công!")
    except Exception as e:
        print(f"❌ Exception tạo key: {str(e)}")

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
        async for _ in run_cmd("git fetch --all --prune", project_dir): pass

        checkout_cmd = f"git checkout -B {version} origin/{version}"
        async for _ in run_cmd(checkout_cmd, project_dir): pass

        pull_cmd = f"git pull origin {version}"
        async for _ in run_cmd(pull_cmd, project_dir): pass

        # 3. Khởi tạo cấu hình (Keystore & SDK/JDK)
        create_keystore(project_dir, name)
        create_local_properties(project_dir)

        # 4. Dọn dẹp thủ công thư mục build cũ (Fix lỗi FileUtils lock trên Windows)
        # Quét và xóa thư mục build trong module app
        app_build_dir = os.path.join(project_dir, "app", "build")
        if os.path.exists(app_build_dir):
            try:
                shutil.rmtree(app_build_dir)
                print(f"🧹 Đã xóa thủ công: {app_build_dir}")
            except Exception as e:
                print(f"⚠️ Cảnh báo: Không thể xóa build folder (file đang bị lock): {e}")

        # Lấy JDK path để ép vào lệnh build
        jdk_path = get_required_jdk(project_dir)
        jdk_clean = jdk_path.replace('\\', '/')

        # 5. Lệnh Build AAB (Thêm clean và --no-daemon)
        gradle_exe = "gradlew" if os.name == "nt" else "./gradlew"
        # Thêm task 'clean' trước 'bundleRelease' để Gradle tự dọn dẹp lại lần nữa
        cmd = f'{gradle_exe} clean bundleRelease -Dorg.gradle.java.home="{jdk_clean}" --no-daemon --stacktrace'

        await bot.send_message(chat_id, f"🛠 Đang thực thi Build với JDK: {jdk_path}")

        success = True
        logs = []
        async for line in run_cmd(cmd, project_dir):
            logs.append(line)
            print(f"[{name}] {line}")
            if len(logs) > 200: logs.pop(0)
            # Kiểm tra lỗi fail
            if "BUILD FAILED" in line.upper() or "FAILURE" in line.upper():
                success = False

        if not success:
            error_log = "\n".join(logs[-30:]) # Lấy 30 dòng để có thêm thông tin
            await bot.send_message(chat_id, f"❌ Build thất bại. Chi tiết lỗi:\n\n{error_log}")
            return

        # 6. Tìm và gửi file .aab
        aab_path = None
        # Ưu tiên tìm trong thư mục output chuẩn
        target_output = os.path.join(project_dir, "app", "build", "outputs", "bundle", "release")
        if os.path.exists(target_output):
            for f in os.listdir(target_output):
                if f.endswith(".aab"):
                    aab_path = os.path.join(target_output, f)
                    break

        # Dự phòng: Quét toàn bộ nếu không thấy ở thư mục chuẩn
        if not aab_path:
            for root, _, files in os.walk(project_dir):
                if "build" in root and "outputs" in root:
                    for f in files:
                        if f.endswith(".aab"):
                            aab_path = os.path.join(root, f)
                            break

        if aab_path:
            with open(aab_path, "rb") as document:
                await bot.send_document(
                    chat_id=chat_id,
                    document=document,
                    caption=f"✅ Build AAB thành công: {version}\nProject: {name}",
                    read_timeout=1000,
                    write_timeout=1000
                )
        else:
            await bot.send_message(chat_id, "❌ Build SUCCESS nhưng không tìm thấy file .aab.")

    except Exception as e:
        await bot.send_message(chat_id, f"⚠️ Có lỗi xảy ra: {str(e)}")

