"""测试隔离：每次运行用临时的 vault 密钥，并固定时区（断言里的时间戳按 +08:00 写）。

各测试模块在 import app 之前自己把 PORTAL_DATA_DIR 指到临时目录。
"""
import os
import tempfile

_VAULT_DIR = tempfile.TemporaryDirectory()
os.environ["PORTAL_VAULT_KEY"] = os.path.join(_VAULT_DIR.name, "vault.key")
os.environ["PAPER_DESK_TZ"] = "Asia/Shanghai"
os.environ.setdefault("PAPER_DESK_ADMIN_PASSWORD", "test-admin-password")
