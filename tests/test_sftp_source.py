"""SFTP v3 wire contract, with synthetic packets and no network or credentials."""
import io
import stat
import struct

import pytest

from invoice_hub.storage.source_adapters import SourceError
from invoice_hub.storage.source_adapters.sftp import Cursor, SFTP, string, u32


def attrs(mode, size=0, mtime=100):
    return u32(13) + struct.pack('>Q', size) + u32(mode) + u32(0) + u32(mtime)


class Process:
    def __init__(self, command, **kwargs):
        self.command, self.data, self.offset, self.requests = command, bytearray(), 0, []
        self.stdout, self.stdin, self.stderr = self, self, io.BytesIO()
        self.name = b'invoice with spaces.xml'
        self.body = b'<Invoice>synthetic</Invoice>'
        self.changed = False

    def write(self, packet):
        cur = Cursor(packet[4:])
        kind = cur.take(1)[0]
        if kind == 1:
            payload = b'\x02' + u32(3)
        else:
            seq = cur.number()
            self.requests.append(kind)
            if kind == 7:
                path = cur.text().decode()
                directory = path == '/invoices'
                payload = b'\x69' + u32(seq) + attrs(stat.S_IFDIR | 0o700 if directory else stat.S_IFREG | 0o600, 0 if directory else len(self.body), 101 if self.changed else 100)
            elif kind == 16:
                path = cur.text()
                payload = b'\x68' + u32(seq) + u32(1) + string(path) + string(path) + attrs(stat.S_IFDIR | 0o700)
            elif kind in (3, 11):
                cur.text()
                if kind == 3:
                    assert cur.number() == 1  # SSH_FXF_READ, no create/truncate/write flags.
                payload = b'\x66' + u32(seq) + string(b'file' if kind == 3 else b'dir')
            elif kind == 12:
                if self.offset:
                    payload = b'\x65' + u32(seq) + u32(1) + string('eof') + string('')
                else:
                    self.offset = 1
                    payload = b'\x68' + u32(seq) + u32(1) + string(self.name) + string('') + attrs(stat.S_IFREG | 0o600, len(self.body))
            elif kind == 5:
                cur.text()
                offset = struct.unpack('>Q', cur.take(8))[0]
                assert cur.number() <= 32768
                payload = (b'\x67' + u32(seq) + string(self.body)) if offset == 0 else b'\x65' + u32(seq) + u32(1)
            else:
                assert kind == 4
                payload = b'\x65' + u32(seq) + u32(0)
        self.data.extend(u32(len(payload)) + payload)

    def read(self, count):
        data = bytes(self.data[:count])
        del self.data[:count]
        return data

    def flush(self):
        pass

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0


def client(tmp_path, monkeypatch):
    processes = []
    def popen(command, **kwargs):
        result = Process(command, **kwargs)
        processes.append(result)
        return result
    monkeypatch.setattr('invoice_hub.storage.source_adapters.sftp.subprocess.Popen', popen)
    monkeypatch.setattr('invoice_hub.storage.source_adapters.sftp.shutil.which', lambda _: '/synthetic/ssh')
    adapter = SFTP({'host': 'server.invalid', 'port': 2222, 'username': 'reader', 'root': '/invoices',
                    'host_key': 'ssh-ed25519 c3ludGhldGlj'}, tmp_path)
    return adapter, processes[0]


def test_sftp_wire_names_read_only_and_fixed_subsystem(tmp_path, monkeypatch):
    adapter, process = client(tmp_path, monkeypatch)
    entries = adapter.entries(lambda _: None)
    assert entries[0]['relative'] == 'invoice with spaces.xml'
    target = tmp_path / 'copy.part'
    adapter.copy(entries[0], target, lambda _: None)
    assert target.read_bytes() == process.body
    assert set(process.requests) <= {3, 4, 5, 7, 11, 12, 16}
    assert process.command[-3:] == ['-s', 'server.invalid', 'sftp']
    assert '-oProxyCommand=none' in process.command and '-oBatchMode=yes' in process.command
    assert '-oStrictHostKeyChecking=yes' in process.command and '-oPasswordAuthentication=no' in process.command
    assert adapter.strength.endswith('no_stable_file_id')
    adapter.close()


def test_sftp_rejects_unsafe_server_names_and_changed_metadata(tmp_path, monkeypatch):
    adapter, process = client(tmp_path, monkeypatch)
    process.name = b'../escape.xml'
    with pytest.raises(SourceError, match='文件名'):
        adapter.entries(lambda _: None)
    process.name, process.offset = b'a.xml', 0
    entry = adapter.entries(lambda _: None)[0]
    process.changed = True
    with pytest.raises(SourceError, match='版本'):
        adapter.copy(entry, tmp_path / 'bad.part', lambda _: None)
    assert not (tmp_path / 'bad.part').exists()


def test_sftp_rejects_truncated_or_large_packets():
    with pytest.raises(SourceError):
        Cursor(b'\x00').number()
    with pytest.raises(SourceError):
        Cursor(u32(1024*1024+1)).text()


@pytest.mark.parametrize(
    ('stderr_text', 'ssh_add_rc', 'expected_code', 'expected_text'),
    [
        (b'Permission denied (publickey).', 1, 'auth_required', 'ssh-add'),
        (b'Permission denied (publickey).', 2, 'auth_required', '未连接到系统 SSH Agent'),
        (b'Permission denied (publickey).', 0, 'auth_required', '公钥认证'),
        (b'ssh: connect to host example.invalid port 22: Connection refused', 0, 'connection_failed', '拒绝'),
        (b'ssh: Could not resolve hostname example.invalid: nodename nor servname provided', 0, 'connection_failed', '解析主机名'),
        (b'ssh: connect to host example.invalid port 22: Operation timed out', 0, 'connection_failed', '超时'),
        (b'subsystem request failed on channel 0', 0, 'protocol_error', 'SFTP 子系统'),
        (b'Host key verification failed.', 0, 'host_key_changed', '指纹不匹配'),
    ],
)
def test_sftp_classifies_ssh_stderr_and_agent_states(tmp_path, monkeypatch, stderr_text, ssh_add_rc, expected_code, expected_text):
    import subprocess
    from invoice_hub.storage.source_adapters import sftp as sftp_mod

    class FailingProcess:
        def __init__(self, command, **kwargs):
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO(b'')
            self.stderr = io.BytesIO(stderr_text)

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 255

    monkeypatch.setattr(sftp_mod.subprocess, 'Popen', FailingProcess)
    monkeypatch.setattr(sftp_mod.shutil, 'which', lambda name: f'/synthetic/{name}')
    monkeypatch.setattr(
        sftp_mod.subprocess,
        'run',
        lambda *a, **kw: subprocess.CompletedProcess(a, ssh_add_rc, b'', b''),
    )
    with pytest.raises(SourceError) as exc_info:
        SFTP(
            {'host': 'server.invalid', 'port': 22, 'username': 'reader', 'root': '/invoices', 'host_key': 'ssh-ed25519 c3ludGhldGlj'},
            tmp_path,
        )
    assert exc_info.value.code == expected_code
    assert expected_text in str(exc_info.value)


def test_sftp_probe_accepts_key_lines_with_comment_and_validates_base64(monkeypatch):
    import base64
    import subprocess
    from invoice_hub.storage.source_adapters import sftp as sftp_mod

    key_b64 = base64.b64encode(b'synthetic-ed25519-key-material').decode('ascii')
    stdout = f'server.invalid ssh-ed25519 {key_b64} comment-text\nserver.invalid ssh-rsa not!valid\n'.encode('utf-8')
    monkeypatch.setattr(sftp_mod.shutil, 'which', lambda name: f'/synthetic/{name}')
    monkeypatch.setattr(
        sftp_mod.subprocess,
        'run',
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout, b''),
    )
    keys = sftp_mod.probe({'host': 'server.invalid', 'port': 22})
    assert len(keys) == 1
    assert next(iter(keys.values())) == f'ssh-ed25519 {key_b64}'
