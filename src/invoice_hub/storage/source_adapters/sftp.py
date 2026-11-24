"""Minimal SFTP v3 read-only transport over system OpenSSH and SSH Agent.

No shell, user SSH config, password prompt, port forward or remote mutation is exposed.
"""
import base64
import hashlib
import os
import shutil
import stat
import struct
import subprocess
from pathlib import PurePosixPath

from . import MAX_ENTRIES, MAX_FILE, SourceError, relative, safe_name


def u32(n):
    return struct.pack(">I", n)


def string(value):
    data = value.encode() if isinstance(value, str) else value
    return u32(len(data)) + data


class Cursor:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, size):
        result = self.data[self.pos:self.pos + size]
        if len(result) != size:
            raise SourceError("SFTP 响应被截断。", "protocol_error")
        self.pos += size
        return result

    def number(self):
        return struct.unpack(">I", self.take(4))[0]

    def text(self):
        size = self.number()
        if size > 1024 * 1024:
            raise SourceError("SFTP 字段超过限制。", "protocol_error")
        return self.take(size)

    def attrs(self):
        flags, result = self.number(), {}
        if flags & ~0x8000000F:
            raise SourceError("SFTP 属性不受支持。", "protocol_error")
        if flags & 1:
            result["size"] = struct.unpack(">Q", self.take(8))[0]
        if flags & 2:
            result.update(uid=self.number(), gid=self.number())
        if flags & 4:
            result["mode"] = self.number()
        if flags & 8:
            self.number()
            result["mtime"] = self.number()
        if flags & 0x80000000:
            count = self.number()
            if count > 100:
                raise SourceError("SFTP 扩展属性过多。")
            for _ in range(count):
                self.text()
                self.text()
        return result


def _ssh_agent_auth_message() -> str:
    """Distinguish missing agent, empty agent, and server key rejection without prompting."""
    tool = shutil.which("ssh-add")
    if not tool:
        return "SSH Agent 认证失败；请确认系统已安装 OpenSSH 并通过 ssh-add 加载私钥。"
    env = {**os.environ, "SSH_ASKPASS": "", "SSH_ASKPASS_REQUIRE": "never"}
    try:
        result = subprocess.run(
            [tool, "-l"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=2,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "无法查询系统 SSH Agent 状态；请确认 SSH Agent 已启动并加载私钥。"
    if result.returncode == 0:
        return "服务器拒绝了当前 SSH Agent 中的公钥认证，请确认该账号已配置对应公钥且允许 SFTP 登录。"
    if result.returncode == 1:
        return "SSH Agent 已运行但尚未加载私钥；请先在终端执行 ssh-add（macOS 可用 ssh-add --apple-use-keychain）后重试。"
    return "未连接到系统 SSH Agent；请先启动 SSH Agent 并通过 ssh-add 加载私钥（macOS 桌面端需先在终端完成 ssh-add --apple-use-keychain）。"


def probe(profile):
    tool = shutil.which("ssh-keyscan")
    if not tool or not shutil.which("ssh"):
        raise SourceError("系统未安装 OpenSSH 客户端（ssh / ssh-keyscan）。", "capability_unavailable")
    result = subprocess.run([tool, "-T", "8", "-p", str(profile["port"]), "-t", "ed25519,ecdsa,rsa", profile["host"]],
                            capture_output=True, timeout=12, check=False)
    keys = {}
    if len(result.stdout) > 65536:
        raise SourceError("主机密钥响应过大。")
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 3 or not parts[1].startswith(("ssh-", "ecdsa-")):
            continue
        try:
            raw = base64.b64decode(parts[2], validate=True)
        except ValueError:
            continue
        fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
        keys[fingerprint] = f"{parts[1]} {parts[2]}"
    if not keys:
        raise SourceError("无法取得主机密钥，请检查 DNS、端口和网络。", "connection_failed")
    return keys


class SFTP:
    strength = "sftp_v3_weak_size_mtime_client_hash_no_stable_file_id"

    def __init__(self, profile, private_dir):
        self.profile, self.sequence = profile, 0
        self.root = profile["root"]
        if not profile.get("host_key"):
            raise SourceError("请先核对并确认主机密钥指纹。", "auth_required")
        host = profile["host"]
        known = private_dir / "known_hosts"
        known.write_text(f"[{host}]:{profile['port']} {profile['host_key']}\n{host} {profile['host_key']}\n", encoding="ascii")
        os.chmod(known, 0o600)
        tool = shutil.which("ssh")
        if not tool:
            raise SourceError("系统未安装 OpenSSH 客户端。", "capability_unavailable")
        command = [tool, "-F", os.devnull, "-T", "-oBatchMode=yes", "-oConnectTimeout=10", "-oServerAliveInterval=10",
                   "-oServerAliveCountMax=2", "-oStrictHostKeyChecking=yes", "-oGlobalKnownHostsFile=" + os.devnull,
                   "-oUserKnownHostsFile=" + str(known), "-oUpdateHostKeys=no", "-oClearAllForwardings=yes",
                   "-oPermitLocalCommand=no", "-oProxyCommand=none", "-oProxyJump=none", "-oPreferredAuthentications=publickey",
                   "-oPasswordAuthentication=no", "-oKbdInteractiveAuthentication=no", "-oIdentityFile=none",
                   "-p", str(profile["port"]), "-l", profile["username"], "-s", host, "sftp"]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._send(b"\x01" + u32(3))
        kind, data = self._packet()
        if kind != 2 or Cursor(data).number() != 3:
            raise SourceError("服务器不支持 SFTP v3。", "protocol_error")
        self._directory(self.root)
        self.root_identity = [self.root, "weak_sftp_v3"]

    def _send(self, data):
        self.process.stdin.write(u32(len(data)) + data)
        self.process.stdin.flush()

    def _read(self, count):
        result = bytearray()
        while len(result) < count:
            block = self.process.stdout.read(count - len(result))
            if not block:
                error = self.process.stderr.read(65536).decode(errors="replace").casefold()
                if "host key verification failed" in error or "host identification has changed" in error:
                    raise SourceError("主机密钥与已确认指纹不匹配，连接已阻断。", "host_key_changed")
                if "permission denied" in error:
                    raise SourceError(_ssh_agent_auth_message(), "auth_required")
                if "could not resolve hostname" in error or "nodename nor servname" in error or "name or service not known" in error:
                    raise SourceError("无法解析主机名，请检查服务器地址和网络。", "connection_failed")
                if "connection refused" in error:
                    raise SourceError("连接被服务器拒绝，请检查 SSH 服务是否开启及端口号是否正确。", "connection_failed")
                if "timed out" in error:
                    raise SourceError("SSH/SFTP 连接超时，请检查网络、VPN 或防火墙配置。", "connection_failed")
                if "subsystem request failed" in error:
                    raise SourceError("服务器未启用 SFTP 子系统，请联系管理员开启 SFTP 服务。", "protocol_error")
                raise SourceError("SFTP 连接中断，请检查网络与服务。", "connection_failed")
            result.extend(block)
        return bytes(result)

    def _packet(self):
        size = struct.unpack(">I", self._read(4))[0]
        if not 1 <= size <= 4 * 1024 * 1024:
            raise SourceError("SFTP 包长度无效。", "protocol_error")
        packet = self._read(size)
        return packet[0], packet[1:]

    def request(self, kind, data):
        self.sequence += 1
        self._send(bytes([kind]) + u32(self.sequence) + data)
        answer, raw = self._packet()
        cur = Cursor(raw)
        if cur.number() != self.sequence:
            raise SourceError("SFTP 响应序号无效。", "protocol_error")
        if answer == 101:
            code = cur.number()
            if code in {0, 1}:
                cur.status = code
                return 101, cur
            if code == 2:
                raise SourceError("远端目录或文件不存在，请检查服务器根目录或刷新目录。", "source_unavailable")
            if code == 3:
                raise SourceError("账号无权访问该远端目录或文件，请检查服务器目录权限。", "auth_required")
            raise SourceError(f"SFTP 读取失败（状态码 {code}）。", "source_unavailable")
        return answer, cur

    def attrs(self, path):
        kind, cur = self.request(7, string(path))
        if kind != 105:
            raise SourceError("SFTP 未返回文件属性。")
        return cur.attrs()

    def _directory(self, path):
        attrs = self.attrs(path)
        if not stat.S_ISDIR(attrs.get("mode", 0)):
            raise SourceError("SFTP 根或子目录包含链接。", "unsafe_path")
        kind, cur = self.request(16, string(path))
        if kind != 104 or cur.number() != 1 or cur.text().decode() != path:
            raise SourceError("SFTP 路径经符号链接重定向或不是规范绝对路径，请改填服务器上的真实目录路径。", "unsafe_path")

    def entries(self, report):
        rows, pending = [], [(self.root, "", 0)]
        while pending:
            path, parent, depth = pending.pop()
            if depth > 64:
                raise SourceError("SFTP 目录层数超过限制。")
            self._directory(path)
            kind, cur = self.request(11, string(path))
            if kind != 102:
                raise SourceError("SFTP 目录无法打开。")
            handle = cur.text()
            seen = set()
            try:
                while True:
                    kind, cur = self.request(12, string(handle))
                    if kind == 101 and cur.status == 1:
                        break
                    if kind != 104:
                        raise SourceError("SFTP 目录页无效。")
                    count = cur.number()
                    if count > 10000:
                        raise SourceError("SFTP 目录页过大。")
                    for _ in range(count):
                        name = cur.text().decode("utf-8", errors="strict")
                        cur.text()
                        attrs = cur.attrs()
                        if name in {".", ".."}:
                            continue
                        safe_name(name)
                        if name in seen:
                            raise SourceError("SFTP 目录页重复，扫描不完整。")
                        seen.add(name)
                        mode = attrs.get("mode", 0)
                        if stat.S_ISLNK(mode):
                            raise SourceError("SFTP 目录包含链接。", "unsafe_path")
                        folder = stat.S_ISDIR(mode)
                        if not folder and not stat.S_ISREG(mode):
                            continue
                        rel = f"{parent}/{name}".lstrip("/")
                        rows.append({"relative": rel, "name": name, "kind": "directory" if folder else "file",
                                     "size": attrs.get("size", 0), "version": [attrs.get("size"), attrs.get("mtime"), mode]})
                        if len(rows) > MAX_ENTRIES:
                            raise SourceError("SFTP 清单超过 100000 项。")
                        if folder:
                            pending.append((str(PurePosixPath(path) / name), rel, depth + 1))
                    report({"phase": "scanning", "enumerated": len(rows)})
            finally:
                self.request(4, string(handle))
        return rows

    def copy(self, entry, output, report):
        rel = relative(entry["relative"])
        path = self.root.rstrip("/")
        for part in rel.split("/")[:-1]:
            path += "/" + part
            self._directory(path)
        path += "/" + rel.split("/")[-1]
        before = self.attrs(path)
        version = lambda a: [a.get("size"), a.get("mtime"), a.get("mode")]
        if version(before) != entry["version"] or not stat.S_ISREG(before.get("mode", 0)):
            raise SourceError("SFTP 文件版本已变化或为链接，请刷新。", "source_changed")
        kind, cur = self.request(3, string(path) + u32(1) + u32(0))
        if kind != 102:
            raise SourceError("SFTP 文件无法只读打开。")
        handle, count = cur.text(), 0
        try:
            with output.open("xb") as target:
                while True:
                    kind, cur = self.request(5, string(handle) + struct.pack(">Q", count) + u32(32768))
                    if kind == 101 and cur.status == 1:
                        break
                    if kind != 103:
                        raise SourceError("SFTP 数据包无效。")
                    block = cur.text()
                    if not block or len(block) > 32768 or count + len(block) > MAX_FILE:
                        raise SourceError("SFTP 文件超过限制或返回无效数据。", "too_large")
                    target.write(block)
                    count += len(block)
                    report({"phase": "downloading", "bytes": count, "total_bytes": before["size"]})
            if count != before["size"] or version(self.attrs(path)) != entry["version"]:
                raise SourceError("SFTP 下载期间文件变化，未使用副本。", "source_changed")
            self._directory(self.root)
        finally:
            self.request(4, string(handle))

    def close(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
