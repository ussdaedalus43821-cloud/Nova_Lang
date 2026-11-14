"""
nova_registry - the registry protocol of NovaForge, for nova-pkg (docs/spec/18-packages.md [pkg.registry]).

A registry is a tree of files (decision D7: no service, nothing to operate or attack at publish time):

    registry.json                    signed by the root keys the client trusts: the registry's name, a serial,
                                     an expiry, the keys that sign the rest, and the hash of every other file
    revoked.json                     signed: key ids and archive hashes that must not be used
    index/<owner>/<name>.json        signed: every version of a package (archive hash, size, nova range,
                                     capabilities, yanked)
    archive/<owner>/<name>/<version>.tar     a deterministic ustar archive

Everything in this module is written with the standard library only: an Ed25519 verifier and signer (RFC 8032),
canonical JSON, a ustar archive writer and a hardened reader, and a fetch core that reads a directory, a file:// URL
or an HTTPS URL under size and time limits. The fetch core is an internal part of nova-pkg: it is not reachable from a
NovaLang program (decision D6 and the owner's ruling: no `net` capability before M14).
"""

import datetime
import hashlib
import io
import json
import os
import re
import secrets
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request


class RegistryError(Exception):
    """A problem with a registry or an archive; the message says what and what to do."""


# ---------------------------------------------------------------------------
# Ed25519 (RFC 8032, section 5.1), pure Python. Slow (a few milliseconds a signature at best) and that does not
# matter: an install verifies a handful. Tested against the RFC's vectors and, where it exists, `cryptography`.
# ---------------------------------------------------------------------------

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493


def _inv(x):
    return pow(x, _P - 2, _P)


_D = (-121665 * _inv(121666)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _recover_x(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _I % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s, p):
    q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _same(p, q):
    return (p[0] * q[2] - q[0] * p[2]) % _P == 0 and (p[1] * q[2] - q[1] * p[2]) % _P == 0


def _compress(p):
    zinv = _inv(p[2])
    x, y = p[0] * zinv % _P, p[1] * zinv % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decompress(data):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _expand(seed):
    digest = hashlib.sha512(seed).digest()
    a = int.from_bytes(digest[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, digest[32:]


def ed25519_public_key(seed):
    return _compress(_mul(_expand(seed)[0], _G))


def ed25519_sign(seed, message):
    a, prefix = _expand(seed)
    public = _compress(_mul(a, _G))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % _L
    point = _compress(_mul(r, _G))
    h = int.from_bytes(hashlib.sha512(point + public + message).digest(), "little") % _L
    return point + ((r + h * a) % _L).to_bytes(32, "little")


def ed25519_verify(public, message, signature):
    if len(public) != 32 or len(signature) != 64:
        return False
    a = _decompress(public)
    r = _decompress(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public + message).digest(), "little") % _L
    return _same(_mul(s, _G), _add(r, _mul(h, a)))


# ---------------------------------------------------------------------------
# Keys, canonical JSON and signed envelopes
# ---------------------------------------------------------------------------

HEX = re.compile(r"[0-9a-f]+\Z")


def key_id(public_hex):
    return hashlib.sha256(bytes.fromhex(public_hex)).hexdigest()[:16]


def generate_key():
    """A new signing key as {"type", "seed", "public"} (hex). The seed is the secret."""
    seed = secrets.token_bytes(32)
    return {"type": "ed25519", "seed": seed.hex(), "public": ed25519_public_key(seed).hex()}


def read_key_file(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            key = json.load(handle)
    except (OSError, ValueError) as problem:
        raise RegistryError("cannot read the key file {}: {}".format(path, problem))
    if (not isinstance(key, dict) or key.get("type") != "ed25519" or not isinstance(key.get("seed"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", key["seed"])):
        raise RegistryError('{} is not a key file made by "nova-pkg keygen"'.format(path))
    key["public"] = ed25519_public_key(bytes.fromhex(key["seed"])).hex()
    return key


def write_key_file(path, key):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        raise RegistryError("{} already exists - choose another name, a key is never overwritten".format(path))
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(key, indent=2) + "\n")


def canonical(value):
    """The bytes that are signed: JSON with sorted keys, no spaces and ASCII only."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sign_envelope(signed, keys):
    """{"signed": ..., "signatures": [...]} signed with each of `keys` (key files read by read_key_file)."""
    message = canonical(signed)
    signatures = [{"keyid": key_id(key["public"]), "sig": ed25519_sign(bytes.fromhex(key["seed"]), message).hex()}
                  for key in keys]
    return {"signed": signed, "signatures": sorted(signatures, key=lambda item: item["keyid"])}


def dump_envelope(envelope):
    return (json.dumps(envelope, sort_keys=True, indent=1, ensure_ascii=True) + "\n").encode("ascii")


def verify_envelope(envelope, trusted, threshold, what):
    """The key ids that validly signed `envelope`, which must be at least `threshold` distinct ones of `trusted`
    ({key id: public key hex}). Anything malformed is refused."""
    if (not isinstance(envelope, dict) or set(envelope) != {"signed", "signatures"} or not isinstance(envelope["signed"], dict)
            or not isinstance(envelope["signatures"], list) or len(envelope["signatures"]) > 16):
        raise RegistryError("{} is not a signed file (it must hold exactly \"signed\" and \"signatures\")".format(what))
    message = canonical(envelope["signed"])
    good = set()
    for item in envelope["signatures"]:
        if (not isinstance(item, dict) or set(item) != {"keyid", "sig"} or not isinstance(item["keyid"], str)
                or not isinstance(item["sig"], str) or not re.fullmatch(r"[0-9a-f]{128}", item["sig"])):
            raise RegistryError("{} has a malformed signature".format(what))
        public = trusted.get(item["keyid"])
        if public is not None and ed25519_verify(bytes.fromhex(public), message, bytes.fromhex(item["sig"])):
            good.add(item["keyid"])
    if len(good) < threshold:
        raise RegistryError("{} is not signed by enough trusted keys ({} valid of the {} required) - it was altered, or "
                            "this is not the registry whose keys the project trusts".format(what, len(good), threshold))
    return sorted(good)


# ---------------------------------------------------------------------------
# Archives: deterministic ustar, written and read here (the tarfile module is never used on untrusted data)
# ---------------------------------------------------------------------------

MAX_FILES = 2000
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_PATH_BYTES = 255
MAX_ARCHIVE_BYTES = MAX_TOTAL_BYTES + 2 * 512 * (MAX_FILES + 1) + 1024
ALLOWED_SUFFIXES = (".nova", ".json", ".md")
ALLOWED_NAMES = ("LICENSE", "NOTICE")
SECRET_NAMES = re.compile(r"(\.env(\..*)?|.*\.pem|.*\.key|.*\.p12|.*\.pfx|id_rsa.*|id_ed25519.*|credentials\.json|"
                          r"secrets?\.json|.*\.secret\.json|.*\.keyfile)\Z", re.I)


def safe_member_name(name):
    """The reason `name` may not be a file of a package, or None. Applies to what pack writes and what the extractor reads."""
    if not name or len(name.encode("utf-8", "surrogatepass")) > MAX_PATH_BYTES:
        return "its path is empty or longer than {} bytes".format(MAX_PATH_BYTES)
    if "\0" in name or "\\" in name or name.startswith("/") or re.match(r"[A-Za-z]:", name):
        return "its path is absolute, has a backslash, a drive letter or a NUL"
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return "its path has an empty, . or .. part"
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        return "its path has a control character"
    if name != "nova.json" and not (parts[-1] in ALLOWED_NAMES or parts[-1].endswith(ALLOWED_SUFFIXES)):
        return "a package holds only .nova, .json and .md files, LICENSE and NOTICE"
    return None


def _field(data, width):
    return data.ljust(width, b"\0")[:width]


def _octal(value, width):
    return ("%0*o" % (width - 1, value)).encode("ascii") + b"\0"


def _header(name, size):
    encoded = name.encode("utf-8")
    prefix = b""
    if len(encoded) > 100:
        cut = encoded.rfind(b"/", 0, 156)
        while cut != -1 and len(encoded) - cut - 1 > 100:
            cut = encoded.rfind(b"/", 0, cut)
        if cut == -1:
            raise RegistryError("{}: this path cannot be written in a ustar archive".format(name))
        prefix, encoded = encoded[:cut], encoded[cut + 1:]
    block = bytearray(512)
    block[0:100] = _field(encoded, 100)
    block[100:108] = _octal(0o644, 8)
    block[108:116] = _octal(0, 8)
    block[116:124] = _octal(0, 8)
    block[124:136] = _octal(size, 12)
    block[136:148] = _octal(0, 12)
    block[148:156] = b"        "
    block[156:157] = b"0"
    block[257:263] = b"ustar\0"
    block[263:265] = b"00"
    block[345:500] = _field(prefix, 155)
    block[148:156] = ("%06o" % sum(block)).encode("ascii") + b"\0 "
    return bytes(block)


def build_archive(files):
    """The deterministic archive of {path: bytes}: entries sorted by path, time 0, mode 0644, owner 0, no directories,
    no links. The same files give the same bytes."""
    if len(files) > MAX_FILES:
        raise RegistryError("a package has at most {} files".format(MAX_FILES))
    out = io.BytesIO()
    total = 0
    for name in sorted(files, key=lambda item: item.encode("utf-8")):
        problem = safe_member_name(name)
        if problem:
            raise RegistryError("{} cannot be packed: {}".format(name, problem))
        data = files[name]
        if len(data) > MAX_FILE_BYTES:
            raise RegistryError("{} is {} bytes; a file of a package is at most {}".format(name, len(data), MAX_FILE_BYTES))
        total += len(data)
        out.write(_header(name, len(data)))
        out.write(data)
        out.write(b"\0" * (-len(data) % 512))
    if total > MAX_TOTAL_BYTES:
        raise RegistryError("the package is {} bytes; at most {} are allowed".format(total, MAX_TOTAL_BYTES))
    out.write(b"\0" * 1024)
    return out.getvalue()


def read_archive(data):
    """{path: bytes} from an archive written by build_archive, refusing anything else: regular files only (no directory
    entries, links, devices, pax or GNU extensions), clean relative names, no duplicates (also by case), the limits of
    MAX_*, the checksum of every header and zeros after the last entry. Nothing is written to disk here."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise RegistryError("the archive is larger than the {} bytes a package may take".format(MAX_ARCHIVE_BYTES))
    files, seen, total, position = {}, set(), 0, 0
    while True:
        if position + 512 > len(data):
            raise RegistryError("the archive ends in the middle of an entry or has no end marker")
        header = data[position:position + 512]
        position += 512
        if header == b"\0" * 512:
            if data[position:position + 512] != b"\0" * 512 or any(data[position:]):
                raise RegistryError("the archive has data after its end marker")
            return files
        if len(files) >= MAX_FILES:
            raise RegistryError("the archive has more than {} files".format(MAX_FILES))
        if header[257:263] != b"ustar\0" or header[263:265] != b"00":
            raise RegistryError("an entry is not a ustar entry")
        try:
            declared = int(header[148:154].decode("ascii"), 8)
        except ValueError:
            raise RegistryError("an entry has a damaged checksum")
        if declared != sum(header[:148]) + 8 * 32 + sum(header[156:]):
            raise RegistryError("an entry has a damaged checksum")
        kind = header[156:157]
        if kind not in (b"0", b"\0"):
            raise RegistryError("an entry is not a regular file (links, devices, directories and extensions are refused)")
        try:
            name = header[0:100].split(b"\0", 1)[0].decode("utf-8")
            prefix = header[345:500].split(b"\0", 1)[0].decode("utf-8")
            size = int(header[124:135].split(b"\0", 1)[0].strip().decode("ascii") or "0", 8)
        except (UnicodeDecodeError, ValueError):
            raise RegistryError("an entry has a name or size that cannot be read")
        name = prefix + "/" + name if prefix else name
        problem = safe_member_name(name)
        if problem:
            raise RegistryError("the archive holds {!r}: {}".format(name, problem))
        folded = name.lower()
        if name in files or folded in seen:
            raise RegistryError("the archive holds {!r} twice (names are compared without regard to case)".format(name))
        if size < 0 or size > MAX_FILE_BYTES:
            raise RegistryError("{} is larger than the {} bytes a file of a package may be".format(name, MAX_FILE_BYTES))
        total += size
        if total > MAX_TOTAL_BYTES:
            raise RegistryError("the archive holds more than {} bytes".format(MAX_TOTAL_BYTES))
        end = position + size
        if end + (-size % 512) > len(data):
            raise RegistryError("the archive ends in the middle of {}".format(name))
        if any(data[end:end + (-size % 512)]):
            raise RegistryError("the padding after {} is not zero".format(name))
        seen.add(folded)
        files[name] = data[position:end]
        position = end + (-size % 512)


def extract_archive(data, destination):
    """Read the archive (read_archive) and write its files into `destination`, which must not exist: they are written to
    a fresh sibling folder and renamed into place, so a failure leaves nothing behind. Nothing is executed."""
    files = read_archive(data)
    parent = os.path.dirname(os.path.abspath(destination))
    os.makedirs(parent, exist_ok=True)
    if os.path.lexists(destination):
        raise RegistryError("{} already exists".format(destination))
    staging = destination + ".part-" + secrets.token_hex(4)
    os.mkdir(staging)
    try:
        for name, content in files.items():
            target = os.path.join(staging, *name.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "xb") as handle:          # "x": never through an existing file or link
                handle.write(content)
        os.rename(staging, destination)
    except BaseException:
        import shutil
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return files


# ---------------------------------------------------------------------------
# The fetch core: a directory, a file:// URL or HTTPS, under limits. Internal to nova-pkg.
# ---------------------------------------------------------------------------

FETCH_TIMEOUT = 15.0
FETCH_DEADLINE = 60.0
MAX_REDIRECTS = 3
CA_ENV = "NOVA_PKG_CA_FILE"        # an extra file of trusted certificate authorities, for a registry behind a private CA


class _SameHostHttps(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to https and to the same host: a registry cannot hand a client to somewhere else."""
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if new.scheme != "https" or new.netloc.lower() != old.netloc.lower():
            raise RegistryError("{} redirected to {}, which is not https on the same host".format(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def is_url(location):
    return re.match(r"[A-Za-z][A-Za-z0-9+.-]*://", location) is not None


def fetch(location, relative, limit):
    """The bytes of `relative` under `location` (a folder, a file:// URL or an https:// URL), at most `limit` of them.
    HTTPS only, with certificate verification and no switch to turn it off; no proxy; a timeout and a deadline; a
    redirect only to the same host over https."""
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", relative) or ".." in relative.split("/") or relative.startswith("/"):
        raise RegistryError("{!r} is not a path inside a registry".format(relative))
    if not is_url(location) or location.lower().startswith("file://"):
        base = location[len("file://"):] if location.lower().startswith("file://") else location
        path = os.path.join(base, *relative.split("/"))
        try:
            with open(path, "rb") as handle:
                data = handle.read(limit + 1)
        except FileNotFoundError:
            raise RegistryError("the registry {} has no {}".format(location, relative))
        except OSError as problem:
            raise RegistryError("cannot read {}: {}".format(path, problem.strerror or problem))
    else:
        parts = urllib.parse.urlsplit(location)
        if parts.scheme.lower() != "https":
            raise RegistryError("the registry {} is not https: a registry is fetched over HTTPS only".format(location))
        if parts.username or parts.password:
            raise RegistryError("a registry address cannot carry a user name or password")
        context = ssl.create_default_context()
        extra = os.environ.get(CA_ENV)
        if extra:
            context.load_verify_locations(cafile=extra)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context),
                                             _SameHostHttps())
        url = location.rstrip("/") + "/" + relative
        request = urllib.request.Request(url, headers={"User-Agent": "nova-pkg", "Accept-Encoding": "identity"})
        started = time.monotonic()
        try:
            with opener.open(request, timeout=FETCH_TIMEOUT) as response:
                if response.status != 200:
                    raise RegistryError("{} answered {}".format(url, response.status))
                declared = response.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > limit:
                    raise RegistryError("{} is {} bytes; the most nova-pkg reads for it is {}".format(url, declared, limit))
                chunks, size = [], 0
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        break
                    if time.monotonic() - started > FETCH_DEADLINE:
                        raise RegistryError("{} took longer than {} seconds".format(url, int(FETCH_DEADLINE)))
                    chunks.append(chunk)
                data = b"".join(chunks) if size <= limit else b"x" * (limit + 1)
        except RegistryError:
            raise
        except urllib.error.HTTPError as problem:
            raise RegistryError("{} answered {}".format(url, problem.code))
        except (urllib.error.URLError, ssl.SSLError, OSError, ValueError) as problem:
            raise RegistryError("cannot fetch {}: {}".format(url, getattr(problem, "reason", problem)))
    if len(data) > limit:
        raise RegistryError("{} is larger than the {} bytes nova-pkg reads for it".format(relative, limit))
    return data


# ---------------------------------------------------------------------------
# The protocol: registry.json, revoked.json, index files
# ---------------------------------------------------------------------------

REGISTRY_FILE = "registry.json"
REVOKED_FILE = "revoked.json"
MAX_METADATA_BYTES = 4 * 1024 * 1024
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
SCOPED = re.compile(r"([a-z0-9][a-z0-9._-]*)/([a-z0-9][a-z0-9._-]*)\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)


def parse_time(text, what):
    try:
        return datetime.datetime.strptime(text, TIME_FORMAT)
    except (TypeError, ValueError):
        raise RegistryError("{} has the time {!r}, which is not written as 2027-01-31T00:00:00Z".format(what, text))


def index_path(name):
    owner, short = SCOPED.match(name).groups()
    return "index/{}/{}.json".format(owner, short)


def archive_path(name, version):
    owner, short = SCOPED.match(name).groups()
    return "archive/{}/{}/{}.tar".format(owner, short, version)


def load_json(data, what):
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as problem:
        raise RegistryError("{} is not valid JSON: {}".format(what, problem))


def state_file():
    return os.environ.get("NOVA_PKG_STATE") or os.path.join(os.path.expanduser("~"), ".nova", "pkg-state.json")


def read_state():
    try:
        with open(state_file(), "r", encoding="utf-8") as handle:
            state = json.load(handle)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(state):
    path = state_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=1, sort_keys=True)
        os.replace(path + ".tmp", path)
    except OSError:
        pass            # a client with no place to remember loses rollback protection, and still has every other check


class Registry:
    """A registry as a client sees it, after every check: `load()` fetches and verifies registry.json (signed by the
    trusted root keys, not expired, a serial no lower than the highest ever seen) and revoked.json (pinned by the
    registry.json that names its hash); `versions(name)` and `archive(name, version)` then answer from signed, pinned files."""

    def __init__(self, location, trusted_keys, threshold=1, now=None):
        self.location = location
        self.roots = {key_id(public): public for public in trusted_keys}
        self.threshold = threshold
        self.now = now or now_utc()
        self.meta = None
        self.keys = {}
        self.revoked_archives = {}
        self.revoked_keys = {}
        self.signed_by = []

    def get(self, relative, limit=MAX_METADATA_BYTES):
        return fetch(self.location, relative, limit)

    def load(self):
        if not self.roots:
            raise RegistryError('the registry {} is signed, and this project trusts no keys for it - add "registryKeys" '
                                "(the public keys of the registry, as nova-pkg keygen prints them) to nova.json".format(self.location))
        raw = self.get(REGISTRY_FILE)
        envelope = load_json(raw, REGISTRY_FILE)
        self.signed_by = verify_envelope(envelope, self.roots, self.threshold, REGISTRY_FILE)
        meta = envelope["signed"]
        if meta.get("_type") != "registry" or not isinstance(meta.get("serial"), int) or isinstance(meta.get("serial"), bool):
            raise RegistryError("{} is not a registry file".format(REGISTRY_FILE))
        expires = parse_time(meta.get("expires"), REGISTRY_FILE)
        if expires < self.now:
            raise RegistryError("the registry {} expired on {} - its operator has stopped updating it, so it is no longer "
                                "trusted (a stale registry could hide a fix or a revocation)".format(self.location, meta["expires"]))
        state = read_state()
        seen = state.get(self.location, {}).get("serial", 0)
        if meta["serial"] < seen:
            raise RegistryError("the registry {} is at serial {}, but this machine has seen serial {} - it is serving an older "
                                "state than it did (a rollback); nothing is installed from it".format(self.location, meta["serial"], seen))
        keys = meta.get("keys")
        if (not isinstance(keys, list) or not keys or not all(isinstance(k, str) and re.fullmatch(r"[0-9a-f]{64}", k) for k in keys)
                or not isinstance(meta.get("threshold"), int) or not 1 <= meta["threshold"] <= len(keys)
                or not isinstance(meta.get("snapshot"), dict)):
            raise RegistryError("{} is malformed".format(REGISTRY_FILE))
        self.meta = meta
        self.keys = {key_id(public): public for public in keys}
        self.revoked_keys = {}
        raw_revoked = self.get(REVOKED_FILE)
        self.pinned(REVOKED_FILE, raw_revoked)
        revoked = load_json(raw_revoked, REVOKED_FILE)
        verify_envelope(revoked, self.keys, meta["threshold"], REVOKED_FILE)
        body = revoked["signed"]
        if body.get("_type") != "revoked" or not isinstance(body.get("keys", []), list) or not isinstance(body.get("archives", []), list):
            raise RegistryError("{} is malformed".format(REVOKED_FILE))
        self.revoked_keys = {item["keyid"]: item.get("reason", "") for item in body.get("keys", []) if isinstance(item, dict)}
        self.revoked_archives = {item["sha256"]: item.get("reason", "") for item in body.get("archives", [])
                                 if isinstance(item, dict) and isinstance(item.get("sha256"), str)}
        state[self.location] = {"serial": meta["serial"]}
        write_state(state)
        return self

    def pinned(self, relative, raw):
        expected = self.meta["snapshot"].get(relative)
        if expected is None:
            raise RegistryError("{} is not part of the registry snapshot of {} (serial {})".format(
                relative, REGISTRY_FILE, self.meta["serial"]))
        if sha256_hex(raw) != expected:
            raise RegistryError("{} does not match the hash that {} (serial {}) pins for it - the registry's files come from "
                                "different times, or were altered".format(relative, REGISTRY_FILE, self.meta["serial"]))

    def usable_keys(self):
        return {kid: public for kid, public in self.keys.items() if kid not in self.revoked_keys}

    def index(self, name):
        """(versions, signing key ids): {version: entry} of the signed index of `name`, or None if the registry has none."""
        relative = index_path(name)
        if relative not in self.meta["snapshot"]:
            return None, []
        raw = self.get(relative)
        self.pinned(relative, raw)
        envelope = load_json(raw, relative)
        signers = verify_envelope(envelope, self.usable_keys(), self.meta["threshold"], relative)
        body = envelope["signed"]
        if body.get("_type") != "index" or body.get("name") != name or not isinstance(body.get("versions"), dict):
            raise RegistryError("{} is not the index of {}".format(relative, name))
        for version, entry in body["versions"].items():
            if (not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version) or not isinstance(entry, dict)
                    or not SHA.match(str(entry.get("sha256", ""))) or not isinstance(entry.get("size"), int)
                    or not isinstance(entry.get("yanked"), bool)):
                raise RegistryError("{} has a malformed entry for version {}".format(relative, version))
        return body["versions"], signers

    def archive(self, name, version, entry):
        """The archive of `name` at `version`, checked against the hash and size of its signed index entry and the revocations."""
        if entry["sha256"] in self.revoked_archives:
            raise RegistryError("{} {} was revoked: {}".format(name, version, self.revoked_archives[entry["sha256"]] or "no reason given"))
        data = self.get(archive_path(name, version), MAX_ARCHIVE_BYTES)
        if len(data) != entry["size"] or sha256_hex(data) != entry["sha256"]:
            raise RegistryError("the archive of {} {} does not match the hash and size that the signed index records for it - it "
                                "was altered after it was published".format(name, version))
        return data


# ---------------------------------------------------------------------------
# Publishing (writing a directory registry)
# ---------------------------------------------------------------------------

def edit_distance_one(a, b):
    """Are the two names the same, or one insertion, deletion, substitution or adjacent swap apart?"""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diffs = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diffs) == 1:
            return True
        return len(diffs) == 2 and diffs[1] == diffs[0] + 1 and a[diffs[0]] == b[diffs[1]] and a[diffs[1]] == b[diffs[0]]
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(short) and short[i] == long_[i]:
        i += 1
    return short[i:] == long_[i + 1:]


def normalised(name):
    """The name with case and the separators - _ . taken out: two names that agree here are one name to a reader."""
    return re.sub(r"[-_.]+", "", name.lower())


def check_name_against(registry_dir, name):
    """R1: refuse a name that could be mistaken for another owner's package. Existing versions of the same name are fine."""
    owner, short = SCOPED.match(name).groups()
    base = os.path.join(registry_dir, "index")
    if not os.path.isdir(base):
        return
    for other_owner in sorted(os.listdir(base)):
        folder = os.path.join(base, other_owner)
        if not os.path.isdir(folder):
            continue
        for entry in sorted(os.listdir(folder)):
            if not entry.endswith(".json"):
                continue
            other = entry[:-5]
            if other_owner == owner and other == short:
                continue
            if normalised(other) == normalised(short) and (other_owner != owner or other != short):
                raise RegistryError("{} is too like {}/{} (they differ only in case or in - _ .) - choose a clearly different name".format(
                    name, other_owner, other))
            if other_owner != owner and len(short) >= 4 and edit_distance_one(short, other):
                raise RegistryError("{} is one letter away from {}/{}, which belongs to another owner - a name like that is how a "
                                    "typing mistake installs the wrong package; choose a clearly different name".format(
                                        name, other_owner, other))


def write_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp-" + secrets.token_hex(4)
    with open(temporary, "wb") as handle:
        handle.write(data)
    os.replace(temporary, path)


class Publisher:
    """Writes a directory registry. Every change is a new snapshot: the files that change are written first and
    registry.json, which pins them all, last, with the next serial."""

    def __init__(self, directory, keys, name=None, expires_days=365, now=None):
        self.directory = os.path.abspath(directory)
        self.keys = keys
        self.now = now or now_utc()
        self.expires_days = expires_days
        self.name = name
        self.snapshot, self.serial, self.root_public, self.threshold = {}, 0, [], 1
        self.pending = {}
        path = os.path.join(self.directory, REGISTRY_FILE)
        if os.path.isfile(path):
            with open(path, "rb") as handle:
                envelope = load_json(handle.read(), REGISTRY_FILE)
            body = envelope["signed"]
            trusted = {key_id(k["public"]): k["public"] for k in keys}
            verify_envelope(envelope, trusted, 1, REGISTRY_FILE)
            self.name, self.serial, self.snapshot = body["name"], body["serial"], dict(body["snapshot"])
            self.signing_keys, self.threshold = list(body["keys"]), body["threshold"]
            usable = {k["public"] for k in keys}
            if len([p for p in self.signing_keys if p in usable]) < self.threshold:
                raise RegistryError("these keys cannot sign this registry: it needs {} of its signing keys".format(self.threshold))
        else:
            self.name = name or os.path.basename(self.directory) or "registry"
            self.signing_keys = [k["public"] for k in keys]
            self.threshold = 1
            self.pending[REVOKED_FILE] = dump_envelope(sign_envelope({"_type": "revoked", "keys": [], "archives": []}, keys))

    def index_entries(self, name):
        relative = index_path(name)
        path = os.path.join(self.directory, *relative.split("/"))
        if not os.path.isfile(path):
            return {}
        with open(path, "rb") as handle:
            body = load_json(handle.read(), relative)["signed"]
        return dict(body.get("versions", {}))

    def add_version(self, name, version, archive, manifest):
        check_name_against(self.directory, name)
        entries = self.index_entries(name)
        if version in entries:
            raise RegistryError("{} {} is already published; a published version is never changed - publish a new version".format(name, version))
        entries[version] = {"sha256": sha256_hex(archive), "size": len(archive), "nova": manifest.get("nova", "*"),
                            "capabilities": manifest["capabilities"], "yanked": False}
        self.pending[archive_path(name, version)] = archive
        self.write_index(name, entries)

    def write_index(self, name, entries):
        relative = index_path(name)
        self.pending[relative] = dump_envelope(sign_envelope({"_type": "index", "name": name, "versions": entries}, self.keys))

    def yank(self, name, version, yanked=True):
        entries = self.index_entries(name)
        if version not in entries:
            raise RegistryError("{} has no version {} to {}".format(name, version, "yank" if yanked else "restore"))
        entries[version] = dict(entries[version], yanked=yanked)
        self.write_index(name, entries)

    def revoke(self, archive_hash=None, keyid=None, reason=""):
        path = os.path.join(self.directory, REVOKED_FILE)
        current = {"_type": "revoked", "keys": [], "archives": []}
        if REVOKED_FILE in self.pending:
            current = load_json(self.pending[REVOKED_FILE], REVOKED_FILE)["signed"]
        elif os.path.isfile(path):
            with open(path, "rb") as handle:
                current = load_json(handle.read(), REVOKED_FILE)["signed"]
        if archive_hash:
            current["archives"] = [a for a in current["archives"] if a["sha256"] != archive_hash] + [{"sha256": archive_hash, "reason": reason}]
        if keyid:
            current["keys"] = [k for k in current["keys"] if k["keyid"] != keyid] + [{"keyid": keyid, "reason": reason}]
        self.pending[REVOKED_FILE] = dump_envelope(sign_envelope(current, self.keys))

    def files(self):
        """{relative path: bytes} of everything this change writes, registry.json last (and so listed last)."""
        snapshot = dict(self.snapshot)
        for relative, data in self.pending.items():
            if relative != REGISTRY_FILE and not relative.startswith("archive/"):
                snapshot[relative] = sha256_hex(data)
        expires = (self.now + datetime.timedelta(days=self.expires_days)).strftime(TIME_FORMAT)
        meta = {"_type": "registry", "name": self.name, "serial": self.serial + 1, "expires": expires,
                "keys": self.signing_keys, "threshold": self.threshold, "snapshot": snapshot}
        out = dict(self.pending)
        out[REGISTRY_FILE] = dump_envelope(sign_envelope(meta, self.keys))
        return out

    def write(self):
        files = self.files()
        for relative in sorted(files, key=lambda item: (item == REGISTRY_FILE, item)):
            write_atomic(os.path.join(self.directory, *relative.split("/")), files[relative])
        return files
