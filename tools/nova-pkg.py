#!/usr/bin/env python3
"""
nova-pkg - NovaLang's package manager (just-in-time: resolve, lock, install).

    python3 tools/nova-pkg.py install            resolve, lock and install
    python3 tools/nova-pkg.py install --frozen   install exactly nova.lock (CI)
    python3 tools/nova-pkg.py verify             check .nova_modules is intact
    python3 tools/nova-pkg.py init [NAME]        write a nova.json (version 2) here
    python3 tools/nova-pkg.py capabilities [PACKAGE]
                                                 what each installed package declares and uses
    python3 tools/nova-pkg.py keygen --out FILE     make a signing key for a registry
    python3 tools/nova-pkg.py pack [--out DIR]      build this package's deterministic archive
    python3 tools/nova-pkg.py publish --registry DIR --key FILE   sign and write it into a registry folder
    python3 tools/nova-pkg.py yank VERSION | unyank VERSION | revoke ...   (docs/spec/18-packages.md)
    python3 tools/nova-pkg.py install --accept-capabilities LIST
                                                 allow a locked package to move to a version that
                                                 declares more capabilities (LIST: names, comma-separated)

Run inside a project (any directory under the one holding nova.json), or
pass --project DIR.

nova.json (version 2; docs/spec/18-packages.md)
    {
      "name": "my-project",                       "owner/name" for anything to be published
      "version": "1.0.0",
      "description", "license", "authors", "repository"      optional text
      "nova": "^2.2.0",                           the NovaLang versions it works with
      "registry": "../registry",                  optional; else $NOVA_REGISTRY
      "main": "main.nova",                        for a package: its entry file
      "files": ["main.nova", "src/**/*.nova"],    what publishing will pack
      "capabilities": ["files.read"],             what the package's own code uses
      "policy": {"capabilities": ["files.read"]}, project only: the most any dependency may need
      "dependencies": {
        "math-utils": "^1.0.0",                   a version range, from the registry
        "local-lib": {"path": "../local-lib"},    a directory
        "remote-lib": {"git": "<url>", "ref": "v1.2.0"}   a tag, branch or commit
      }
    }

Ranges: "1.2.3" exactly, "^1.2.3" (same major; for 0.x the same minor),
"~1.2.3" (same minor), "*" (any). A registry is a directory laid out as
<registry>/<name>/<version>/, each holding that version's nova.json.

Install is flat: one version of each package, side by side in
.nova_modules/, which is what lets `import "name"` find it from anywhere in
the project. If two packages need versions no single version satisfies,
install stops and names them - the conflict is resolved upstream, never
hidden by installing two copies.

nova.lock records exactly what was installed: version, source (a git
commit, not just a ref) and a SHA-256 of every file. `install` reuses it
while it still matches nova.json, so everyone gets identical packages;
`install --frozen` refuses to do anything else. Installing copies
nova.lock into .nova_modules/.installed.lock, last; the interpreter
refuses to import a package while those two differ, so a project whose
nova.json or nova.lock changed after the last install cannot run on stale
packages. .nova_modules/.gitignore keeps the installed packages out of git.

Capabilities: a package lists in "capabilities" the gated functions its code uses (read, write,
time, regex, ... - docs/spec/16-sandbox.md). install parses every .nova file of a package and
refuses one that refers to a gated name whose capability is not listed; the interpreter makes the
same check when the file is imported, and refuses a package whose listed capabilities the run did
not grant. Unknown keys of nova.json are an error unless they start with "x-"; there is no key for
scripts or hooks, and nothing is ever run at install.

Exit status: 0 on success, 1 on any problem (the message says what to do), 2 on usage.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nova_registry as registry_protocol      # noqa: E402  (the registry protocol: signatures, archives, the fetch core)
from nova_registry import RegistryError         # noqa: E402

MANIFEST = "nova.json"
LOCKFILE = "nova.lock"
MODULES = ".nova_modules"
INSTALLED = ".installed.lock"
LOCK_VERSION = 2
READABLE_LOCK_VERSIONS = (1, 2)
NAME = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
SCOPED_NAME = re.compile(r"([a-z0-9][a-z0-9._-]*)/([a-z0-9][a-z0-9._-]*)\Z")
RESERVED_OWNERS = ("std", "nova")
CAPABILITIES = ("files.read", "files.write", "env", "clock", "random", "stdin", "process", "regex", "python", "net")
MANIFEST_KEYS = ("name", "version", "description", "license", "authors", "repository", "nova", "main", "files",
                 "capabilities", "dependencies", "policy", "registry", "registryKeys", "registryThreshold")
FILE_PATTERN = re.compile(r"[A-Za-z0-9._*/-]+\Z")
VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")


class PkgError(Exception):
    """A problem the user must fix; the message says how."""


# ---------------------------------------------------------------------------
# Versions and ranges
# ---------------------------------------------------------------------------

def parse_version(text, where):
    match = VERSION.match(text) if isinstance(text, str) else None
    if not match:
        raise PkgError("{}: {!r} is not a version - write it as MAJOR.MINOR.PATCH, "
                       "e.g. 1.0.0".format(where, text))
    return tuple(int(part) for part in match.groups())


def show(version):
    return "{}.{}.{}".format(*version)


class Range:
    """A version requirement: '*', '1.2.3', '^1.2.3' or '~1.2.3'."""

    def __init__(self, text, where):
        self.text = text
        if text == "*":
            self.low, self.high = (0, 0, 0), None
            return
        operator = text[0] if text[:1] in "^~" else ""
        low = parse_version(text[len(operator):], where)
        major, minor, patch = low
        if operator == "":
            high = (major, minor, patch + 1)
        elif operator == "~":
            high = (major, minor + 1, 0)
        elif major > 0:
            high = (major + 1, 0, 0)
        elif minor > 0:
            high = (0, minor + 1, 0)
        else:
            high = (0, 0, patch + 1)
        self.low, self.high = low, high

    def allows(self, version):
        return self.low <= version and (self.high is None or version < self.high)


# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------

def read_json(path, what):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as problem:
        raise PkgError("cannot read {} {}: {}".format(what, path, problem.strerror))
    except ValueError as problem:
        raise PkgError("{} {} is not valid JSON: {}".format(what, path, problem))


def running_version():
    """The version of the NovaLang beside this tool (novalang.py), as a tuple."""
    try:
        text = open(os.path.join(os.path.dirname(HERE), "novalang.py"), encoding="utf-8").read(8000)
        found = re.search(r'^__version__ = "(\d+)\.(\d+)\.(\d+)"', text, re.M)
    except OSError:
        found = None
    return tuple(int(part) for part in found.groups()) if found else None


def string_list(value, where, field):
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PkgError('{}: "{}" must be a list of text'.format(where, field))
    return value


def capability_list(value, where, field):
    names = string_list(value, where, field)
    for name in names:
        if name not in CAPABILITIES:
            raise PkgError('{}: "{}" lists "{}", which is not a capability (the capabilities are: {})'.format(
                where, field, name, ", ".join(CAPABILITIES)))
    if len(set(names)) != len(names):
        raise PkgError('{}: "{}" lists a capability twice'.format(where, field))
    return sorted(names)


def check_relative(value, where, field, allow_glob):
    bad = (not isinstance(value, str) or not value or value.startswith("/") or "\\" in value or "\0" in value
           or ".." in value.split("/") or ":" in value or (not allow_glob and "*" in value))
    if bad or (allow_glob and not FILE_PATTERN.match(value)):
        raise PkgError('{}: "{}" has {!r}, which is not a path inside the package (a relative path with "/", no "..", '
                       'no drive letter)'.format(where, field, value))


def read_manifest(directory, what, root=False):
    """The manifest of `directory`, checked against the rules of docs/spec/18-packages.md [pkg.manifest].
    `root` is the project being installed (it alone may name a scoped name, a policy and a registry)."""
    path = os.path.join(directory, MANIFEST)
    if not os.path.isfile(path):
        raise PkgError("{} has no {}".format(what, MANIFEST))
    manifest = read_json(path, "the manifest")
    if not isinstance(manifest, dict):
        raise PkgError("{} must be a JSON object".format(path))
    for key in manifest:
        if key not in MANIFEST_KEYS and not key.startswith("x-"):
            raise PkgError('{}: unknown key "{}" - the keys are {}, and any key may start with "x-" '
                           "(there is no key for scripts or hooks: nothing is run at install)".format(
                               path, key, ", ".join(MANIFEST_KEYS)))
    name = manifest.get("name")
    scoped = SCOPED_NAME.match(name) if isinstance(name, str) else None
    if not isinstance(name, str) or not (NAME.match(name) or scoped):
        raise PkgError('{}: "name" must be a lowercase package name such as "math-utils" or "owner/name", '
                       "not {!r}".format(path, name))
    if scoped:
        if scoped.group(1) in RESERVED_OWNERS:
            raise PkgError('{}: "{}" is a reserved owner'.format(path, scoped.group(1)))
    manifest["_version"] = parse_version(manifest.get("version"), path + ' "version"')
    for field in ("description", "license", "repository", "registry"):
        if field in manifest and not isinstance(manifest[field], str):
            raise PkgError('{}: "{}" must be text'.format(path, field))
    if "authors" in manifest:
        string_list(manifest["authors"], path, "authors")
    if "registryKeys" in manifest:
        keys = string_list(manifest["registryKeys"], path, "registryKeys")
        if not keys or not all(re.fullmatch(r"[0-9a-f]{64}", key) for key in keys):
            raise PkgError('{}: "registryKeys" lists the public keys the registry is signed with, each 64 lower-case '
                           'hexadecimal digits, as "nova-pkg keygen" prints them'.format(path))
    if "registryThreshold" in manifest:
        threshold = manifest["registryThreshold"]
        if not isinstance(threshold, int) or isinstance(threshold, bool) or not 1 <= threshold <= len(manifest.get("registryKeys", [])):
            raise PkgError('{}: "registryThreshold" is how many of "registryKeys" must sign, from 1 to their number'.format(path))
    if "nova" in manifest:
        if not isinstance(manifest["nova"], str):
            raise PkgError('{}: "nova" must be a version range such as "^2.2.0"'.format(path))
        manifest["_nova"] = Range(manifest["nova"], path + ' "nova"')
    if "main" in manifest:
        check_relative(manifest["main"], path, "main", False)
        if not manifest["main"].endswith(".nova"):
            raise PkgError('{}: "main" must name a .nova file, not {!r}'.format(path, manifest["main"]))
    if "files" in manifest:
        for entry in string_list(manifest["files"], path, "files"):
            check_relative(entry, path, "files", True)
            last = entry.split("/")[-1]
            if not (last in ("LICENSE", "NOTICE") or last.endswith((".nova", ".json", ".md"))):
                raise PkgError('{}: "files" has {!r}; a package holds only .nova, .json and .md files, '
                               "LICENSE and NOTICE".format(path, entry))
    manifest["capabilities"] = capability_list(manifest.get("capabilities", []), path, "capabilities")
    if "policy" in manifest:
        policy = manifest["policy"]
        if not isinstance(policy, dict) or set(policy) - {"capabilities"}:
            raise PkgError('{}: "policy" has one key, "capabilities" (the most a dependency may need)'.format(path))
        policy["capabilities"] = capability_list(policy.get("capabilities", []), path, "policy.capabilities")
    dependencies = manifest.get("dependencies", {})
    if not isinstance(dependencies, dict):
        raise PkgError('{}: "dependencies" must be an object'.format(path))
    for dep_name, spec in dependencies.items():
        scoped_dep = SCOPED_NAME.match(dep_name)
        if scoped_dep and scoped_dep.group(1) in RESERVED_OWNERS:
            raise PkgError('{}: "{}" is a reserved owner'.format(path, scoped_dep.group(1)))
        if not NAME.match(dep_name) and not scoped_dep:
            raise PkgError("{}: {!r} is not a valid package name".format(path, dep_name))
        check_spec(spec, "{} dependency {!r}".format(path, dep_name))
    manifest["dependencies"] = dependencies
    return manifest


def check_spec(spec, where):
    if isinstance(spec, str):
        Range(spec, where)
        return
    if isinstance(spec, dict):
        if set(spec) == {"path"} and isinstance(spec["path"], str):
            return
        if set(spec) <= {"git", "ref"} and isinstance(spec.get("git"), str) and isinstance(
                spec.get("ref", "HEAD"), str):
            return
    raise PkgError('{}: write a version range such as "^1.0.0", {{"path": "..."}} or '
                   '{{"git": "<url>", "ref": "<tag, branch or commit>"}}, not {}'.format(
                       where, json.dumps(spec)))


def find_project(start):
    directory = os.path.abspath(start)
    while True:
        if os.path.isfile(os.path.join(directory, MANIFEST)) and os.path.basename(
                os.path.dirname(directory)) != MODULES:
            return directory
        parent = os.path.dirname(directory)
        if parent == directory:
            raise PkgError("no {} here or in any directory above {}".format(MANIFEST, start))
        directory = parent


# ---------------------------------------------------------------------------
# Package contents
# ---------------------------------------------------------------------------

def package_files(directory):
    """Every file of a package, as sorted relative paths ('/'-separated);
    version-control and installed-package directories are not part of it."""
    found = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if d not in (".git", MODULES))
        for name in files:
            found.append(os.path.relpath(os.path.join(root, name), directory).replace(os.sep, "/"))
    return sorted(found)


def integrity(directory):
    """SHA-256 over every file's path and bytes: any edit, addition or
    removal changes it."""
    digest = hashlib.sha256()
    for relative in package_files(directory):
        with open(os.path.join(directory, relative), "rb") as handle:
            data = handle.read()
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(str(len(data)).encode("ascii") + b"\0")
        digest.update(data)
    return "sha256-" + digest.hexdigest()


def copy_package(source, destination):
    os.makedirs(destination)
    for relative in package_files(source):
        target = os.path.join(destination, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(os.path.join(source, relative), target)


def git(args, cwd=None):
    try:
        done = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    except OSError as problem:
        raise PkgError("cannot run git: {}".format(problem))
    if done.returncode != 0:
        raise PkgError("git {} failed: {}".format(" ".join(args), done.stderr.strip()))
    return done.stdout.strip()


# ---------------------------------------------------------------------------
# Sources: where one version of one package comes from
# ---------------------------------------------------------------------------

class Candidate:
    """One concrete version of a package that could be installed."""

    def __init__(self, name, version, directory, source, manifest, lock_extra=None):
        self.name = name
        self.version = version
        self.directory = directory      # where its files are, right now
        self.source = source            # what nova.lock records
        self.manifest = manifest
        self.lock_extra = lock_extra or {}      # more of its nova.lock entry: resolved, archive, signedBy


class Sources:
    def __init__(self, project_dir, manifest):
        self.project_dir = project_dir
        registry = manifest.get("registry") or os.environ.get("NOVA_REGISTRY")
        self.registry = None
        self.registry_text = registry
        if registry:
            self.registry = registry if registry_protocol.is_url(registry) and not registry.lower().startswith("file://") \
                else os.path.normpath(os.path.join(project_dir, registry[len("file://"):] if registry.lower().startswith("file://") else registry))
        self.keys = manifest.get("registryKeys", [])
        self.threshold = manifest.get("registryThreshold", 1)
        self._signed = None
        self._candidates = {}
        self.scratch = tempfile.mkdtemp(prefix="nova-pkg-")
        self.git_cache = {}

    def close(self):
        shutil.rmtree(self.scratch, ignore_errors=True)

    def is_signed(self):
        """A signed registry has a registry.json (an https registry must: only a local folder may be the older, unsigned layout)."""
        if self.registry is None:
            return False
        if registry_protocol.is_url(self.registry):
            return True
        return os.path.isfile(os.path.join(self.registry, registry_protocol.REGISTRY_FILE))

    def signed(self, wanted_by):
        if self._signed is None:
            if self.registry is None:
                raise PkgError('{} needs a package from a registry, but none is set - add "registry" to {} or set '
                               "$NOVA_REGISTRY".format(wanted_by, MANIFEST))
            try:
                self._signed = registry_protocol.Registry(self.registry, self.keys, self.threshold).load()
            except RegistryError as problem:
                raise PkgError(str(problem))
        return self._signed

    def signed_index(self, name, wanted_by):
        registry = self.signed(wanted_by)
        try:
            versions, signers = registry.index(name)
        except RegistryError as problem:
            raise PkgError(str(problem))
        if versions is None:
            raise PkgError('package "{}" (needed by {}) is not in the registry {}'.format(name, wanted_by, self.registry))
        return versions, signers

    def available(self, name, wanted_by):
        """Every registry version of `name`, newest first."""
        if SCOPED_NAME.match(name):
            versions, _ = self.signed_index(name, wanted_by)
            usable = [parse_version(v, name) for v, entry in versions.items() if not entry["yanked"]]
            if not usable:
                raise PkgError('every version of "{}" (needed by {}) is yanked'.format(name, wanted_by))
            return sorted(usable, reverse=True)
        if self.is_signed():
            raise PkgError('"{}" (needed by {}) has no owner: a signed registry holds only "owner/name" packages'.format(
                name, wanted_by))
        if self.registry is None:
            raise PkgError('{} needs "{}" from a registry, but none is set - add "registry" to '
                           "{} or set $NOVA_REGISTRY".format(wanted_by, name, MANIFEST))
        folder = os.path.join(self.registry, name)
        versions = []
        if os.path.isdir(folder):
            for entry in os.listdir(folder):
                if VERSION.match(entry) and os.path.isfile(os.path.join(folder, entry, MANIFEST)):
                    versions.append(parse_version(entry, folder))
        if not versions:
            raise PkgError('package "{}" (needed by {}) is not in the registry {}'.format(
                name, wanted_by, self.registry))
        return sorted(versions, reverse=True)

    def from_signed(self, name, version, pin=None):
        """One version from a signed registry: the archive is checked against the hash its signed index records (and
        against `pin`, the hash nova.lock recorded), unpacked by the hardened reader into a scratch folder, and read."""
        key = (name, show(version), pin)
        if key in self._candidates:
            return self._candidates[key]
        versions, signers = self.signed_index(name, "the project")
        entry = versions.get(show(version))
        if entry is None:
            raise PkgError("{} has no version {} in the registry {}".format(name, show(version), self.registry))
        if pin is not None and pin != "sha256-" + entry["sha256"]:
            raise PkgError('{} {} is not the archive {} recorded (the registry now holds {}) - it changed after it was locked'.format(
                name, show(version), LOCKFILE, "sha256-" + entry["sha256"]))
        try:
            data = self.signed("the project").archive(name, show(version), entry)
            directory = os.path.join(self.scratch, "reg-{}-{}".format(name.replace("/", "--"), show(version)))
            registry_protocol.extract_archive(data, directory)
        except RegistryError as problem:
            raise PkgError("{} {}: {}".format(name, show(version), problem))
        manifest = read_manifest(directory, "registry package {}@{}".format(name, show(version)))
        self.check_identity(manifest, name, version, directory)
        if manifest["capabilities"] != sorted(entry.get("capabilities", [])):
            raise PkgError("{} {}: the index says it declares {} and its nova.json declares {} - the registry is inconsistent".format(
                name, show(version), entry.get("capabilities") or "nothing", manifest["capabilities"] or "nothing"))
        candidate = Candidate(name, version, directory, {"registry": self.registry_text}, manifest, {
            "resolved": registry_protocol.archive_path(name, show(version)), "archive": "sha256-" + entry["sha256"],
            "signedBy": signers})
        self._candidates[key] = candidate
        return candidate

    def from_registry(self, name, version):
        if SCOPED_NAME.match(name):
            return self.from_signed(name, version)
        directory = os.path.join(self.registry, name, show(version))
        manifest = read_manifest(directory, "registry package {}@{}".format(name, show(version)))
        self.check_identity(manifest, name, version, directory)
        return Candidate(name, version, directory, {"registry": self.registry_text}, manifest)

    def from_path(self, name, path, base_dir):
        directory = os.path.normpath(os.path.join(base_dir, path))
        if not os.path.isdir(directory):
            raise PkgError('package "{}": path {} does not exist'.format(name, directory))
        manifest = read_manifest(directory, 'package "{}" at {}'.format(name, directory))
        self.check_identity(manifest, name, None, directory)
        relative = os.path.relpath(directory, self.project_dir).replace(os.sep, "/")
        return Candidate(name, manifest["_version"], directory, {"path": relative}, manifest)

    def from_git(self, name, url, ref, base_dir):
        if not re.match(r"[a-z][a-z0-9+.-]*://", url) and not url.startswith("git@"):
            url_to_use = os.path.normpath(os.path.join(base_dir, url))
        else:
            url_to_use = url
        key = (url_to_use, ref)
        if key not in self.git_cache:
            checkout = os.path.join(self.scratch, "git-{}".format(len(self.git_cache)))
            git(["clone", "--quiet", url_to_use, checkout])
            git(["-c", "advice.detachedHead=false", "checkout", "--quiet", ref], cwd=checkout)
            commit = git(["rev-parse", "HEAD"], cwd=checkout)
            self.git_cache[key] = (checkout, commit)
        checkout, commit = self.git_cache[key]
        manifest = read_manifest(checkout, 'package "{}" from {} at {}'.format(name, url, ref))
        self.check_identity(manifest, name, None, url)
        return Candidate(name, manifest["_version"], checkout, {"git": url, "commit": commit},
                         manifest)

    def check_identity(self, manifest, name, version, where):
        if manifest["name"] != name:
            raise PkgError("{} is package {!r}, not {!r}".format(where, manifest["name"], name))
        if version is not None and manifest["_version"] != version:
            raise PkgError("{} says it is version {}, but it is filed as {}".format(
                where, show(manifest["_version"]), show(version)))

    def from_lock(self, name, entry):
        """The candidate a nova.lock entry describes, from its exact source."""
        source = entry.get("source", {})
        version = parse_version(entry.get("version"), "{} entry {!r}".format(LOCKFILE, name))
        if "registry" in source:
            if self.registry is None:
                raise PkgError("{} installs {!r} from a registry, but no registry is "
                               "set".format(LOCKFILE, name))
            if SCOPED_NAME.match(name):
                return self.from_signed(name, version, pin=entry.get("archive"))
            return self.from_registry(name, version)
        if "path" in source:
            return self.from_path(name, source["path"], self.project_dir)
        if "git" in source:
            return self.from_git(name, source["git"], source["commit"], self.project_dir)
        raise PkgError("{} entry {!r} has no source".format(LOCKFILE, name))


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def requirements(root_name, root_manifest, project_dir, chosen):
    """name -> [(requirer, spec, base dir)] from the project and every chosen
    package. Dependencies of versions no longer chosen drop out."""
    needs = {}
    owners = [(root_name, root_manifest, project_dir)]
    owners += [("{}@{}".format(c.name, show(c.version)), c.manifest, c.directory)
               for c in chosen.values()]
    for index, (requirer, manifest, base_dir) in enumerate(owners):
        for name, spec in sorted(manifest["dependencies"].items()):
            if name == root_name:
                raise PkgError("{} depends on {!r}, the project itself".format(requirer, name))
            if index > 0 and isinstance(spec, dict) and "path" in spec:
                # A path inside a published package would point into wherever
                # that package happened to be fetched - not reproducible.
                raise PkgError("{} has a path dependency on {!r}; only the project's own {} "
                               "may use paths".format(requirer, name, MANIFEST))
            needs.setdefault(name, []).append((requirer, spec, base_dir))
    return needs


def pick(name, wants, sources):
    """The one version of `name` that satisfies every requirement on it."""
    pinned = [(who, spec, base) for who, spec, base in wants if isinstance(spec, dict)]
    ranges = [(who, Range(spec, who)) for who, spec, _ in wants if isinstance(spec, str)]
    described = "; ".join("{} wants {}".format(
        who, spec if isinstance(spec, str) else json.dumps(spec)) for who, spec, _ in wants)

    if pinned:
        distinct = {json.dumps(spec, sort_keys=True) for _, spec, _ in pinned}
        if len(distinct) > 1:
            raise PkgError('conflicting sources for "{}": {}'.format(name, described))
        who, spec, base = pinned[0]
        if "path" in spec:
            candidate = sources.from_path(name, spec["path"], base)
        else:
            candidate = sources.from_git(name, spec["git"], spec.get("ref", "HEAD"), base)
        for requirer, wanted in ranges:
            if not wanted.allows(candidate.version):
                raise PkgError('conflicting requirements for "{}": {} (it is pinned to {})'.format(
                    name, described, show(candidate.version)))
        return candidate

    wanted_by = ", ".join(sorted({who for who, _, _ in wants}))
    versions = sources.available(name, wanted_by)
    for version in versions:
        if all(wanted.allows(version) for _, wanted in ranges):
            return sources.from_registry(name, version)
    raise PkgError('conflicting requirements for "{}": {} - no version satisfies them all '
                   "(available: {})".format(name, described, ", ".join(
                       show(v) for v in sorted(versions))))


def resolve(project_dir, manifest, sources):
    """name -> Candidate, settled by repeating: for each name, pick the
    highest version every current requirement allows, until nothing
    changes. One version per name keeps this finite, cycles included."""
    chosen = {}
    for _ in range(100):
        needs = requirements(manifest["name"], manifest, project_dir, chosen)
        settled = {name: pick(name, needs[name], sources) for name in sorted(needs)}
        if {n: (c.version, json.dumps(c.source, sort_keys=True)) for n, c in settled.items()} == \
           {n: (c.version, json.dumps(c.source, sort_keys=True)) for n, c in chosen.items()}:
            return settled
        chosen = settled
    raise PkgError("the dependency versions never settled - check for packages that require "
                   "each other's versions back and forth")


# ---------------------------------------------------------------------------
# Capabilities: what a package declares, and what its code can refer to (decision D9)
# ---------------------------------------------------------------------------

_interpreter = None


def interpreter():
    """novalang.py, from the folder above tools/: the scan uses the interpreter's own lexer and parser, so it
    cannot disagree with the interpreter about what a file refers to."""
    global _interpreter
    if _interpreter is None:
        sys.path.insert(0, os.path.dirname(HERE))
        try:
            import novalang
        except ImportError as problem:
            raise PkgError("cannot load novalang.py from {} to read packages: {}".format(os.path.dirname(HERE), problem))
        _interpreter = novalang
    return _interpreter


def scan_package(directory):
    """{capability: [(file, name), ...]}: every gated name each .nova file of the package refers to, found in its
    syntax tree (a field name, a dictionary key and a declared name are not references)."""
    nl = interpreter()
    used = {}
    for relative in package_files(directory):
        if not relative.endswith(".nova"):
            continue
        try:
            with open(os.path.join(directory, relative), "r", encoding="utf-8") as handle:
                source = handle.read()
            tree = nl.Parser(nl.Lexer(source).tokenize()).parse()
        except (OSError, UnicodeDecodeError) as problem:
            raise PkgError("cannot read {}: {}".format(relative, problem))
        except nl.NovaError as problem:
            raise PkgError("{} cannot be parsed: {}".format(relative, problem.message))
        except RecursionError:
            raise PkgError("{} is nested too deeply to read".format(relative))
        for name, capability in sorted(nl.gated_references(tree).items()):
            used.setdefault(capability, []).append((relative, name))
    return used


def check_capabilities(label, directory, manifest, out):
    """Refuse a package that uses a gated name its manifest does not declare; warn about one it declares and never uses."""
    used = scan_package(directory)
    declared = manifest["capabilities"]
    for capability in sorted(used):
        if capability not in declared:
            relative, name = used[capability][0]
            raise PkgError("{}/{} uses {}, which needs {}, which its {} does not declare - add it to \"capabilities\" "
                           "or stop using it".format(label, relative, name, capability, MANIFEST))
    for capability in declared:
        if capability not in used:
            out("nova-pkg: warning: {} declares {}, which none of its files uses - declare only what is needed".format(
                label, capability))
    return used


def check_graph(manifest, resolved, old_lock, accepted, out):
    """The checks a resolved graph must pass before anything is installed ([pkg.install])."""
    running = running_version()
    allowed = manifest.get("policy", {}).get("capabilities")
    old_packages = (old_lock or {}).get("packages", {})
    for name, candidate in sorted(resolved.items()):
        label = "{} {}".format(name, show(candidate.version))
        wanted = candidate.manifest.get("_nova")
        if wanted is not None and running is not None and not wanted.allows(running):
            raise PkgError('package {} works with NovaLang {}, but this is NovaLang {} - choose another version '
                           "of it".format(label, wanted.text, show(running)))
        check_capabilities(name, candidate.directory, candidate.manifest, out)
        declared = candidate.manifest["capabilities"]
        if allowed is not None:
            extra = [c for c in declared if c not in allowed]
            if extra:
                raise PkgError('package {} needs {}, which "policy" in {} does not allow (it allows: {}) - '
                               "choose another version or package, or widen the policy deliberately".format(
                                   label, ", ".join(extra), MANIFEST, ", ".join(allowed) or "nothing"))
        previous = old_packages.get(name, {})
        if "capabilities" in previous:
            gained = [c for c in declared if c not in previous["capabilities"] and c not in accepted]
            if gained:
                raise PkgError("package {} declares {}, which the locked {} {} did not - read what it does, then "
                               "run install --accept-capabilities {}".format(
                                   label, ", ".join(gained), name, previous.get("version"), ",".join(gained)))


# ---------------------------------------------------------------------------
# The lockfile
# ---------------------------------------------------------------------------

def lock_text(manifest, resolved):
    packages = {}
    for name, candidate in sorted(resolved.items()):
        packages[name] = {
            "version": show(candidate.version),
            "source": candidate.source,
            "integrity": integrity(candidate.directory),
            "capabilities": candidate.manifest["capabilities"],
            "dependencies": candidate.manifest["dependencies"],
        }
        packages[name].update(candidate.lock_extra)
    lock = {
        "lockfile_version": LOCK_VERSION,
        "requires": manifest["dependencies"],
        "packages": packages,
    }
    return json.dumps(lock, indent=2, sort_keys=True) + "\n"


def read_lock(project_dir):
    path = os.path.join(project_dir, LOCKFILE)
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as problem:
        raise PkgError("cannot read {}: {}".format(path, problem)) from None
    try:
        lock = json.loads(text)
    except ValueError as problem:
        raise PkgError("{} is not valid JSON ({}) - delete it and run install".format(
            LOCKFILE, problem))
    if not isinstance(lock, dict) or lock.get("lockfile_version") not in READABLE_LOCK_VERSIONS:
        raise PkgError("{} is not a version-1 or version-{} lockfile - delete it and run install".format(
            LOCKFILE, LOCK_VERSION))
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        raise PkgError('{}: "packages" must be an object'.format(LOCKFILE))
    for name, entry in packages.items():
        if not NAME.fullmatch(name) and not SCOPED_NAME.fullmatch(name):
            raise PkgError("{}: invalid package name {!r}".format(LOCKFILE, name))
        where = "{} entry {!r}".format(LOCKFILE, name)
        if not isinstance(entry, dict):
            raise PkgError("{} must be an object".format(where))
        source = entry.get("source")
        if not isinstance(source, dict):
            raise PkgError('{}: "source" must be an object'.format(where))
        if "capabilities" in entry and (not isinstance(entry["capabilities"], list) or any(
                c not in CAPABILITIES for c in entry["capabilities"])):
            raise PkgError('{}: "capabilities" must be a list of capability names'.format(where))
        # Validate the same source fields the installer will use.
        for fields in (("registry",), ("path",), ("git", "commit")):
            if fields[0] in source:
                if not all(isinstance(source.get(field), str) for field in fields):
                    raise PkgError("{}: invalid source fields".format(where))
                break
        else:
            raise PkgError("{} has no source".format(where))
    return lock, text


def lock_matches(lock, manifest):
    """Does nova.lock still describe what nova.json asks for?"""
    return lock.get("requires") == manifest["dependencies"]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def install(project_dir, frozen=False, out=print, accepted=()):
    manifest = read_manifest(project_dir, "the project " + project_dir, root=True)
    lock, text = read_lock(project_dir)
    if frozen:
        if lock is None:
            raise PkgError("--frozen: there is no {} - run install without --frozen to "
                           "create it, and commit it".format(LOCKFILE))
        if not lock_matches(lock, manifest):
            raise PkgError("--frozen: {} is out of date with {} - run install without "
                           "--frozen to update it, and commit it".format(LOCKFILE, MANIFEST))

    sources = Sources(project_dir, manifest)
    try:
        if lock is not None and lock_matches(lock, manifest):
            resolved = {name: sources.from_lock(name, entry)
                        for name, entry in sorted(lock.get("packages", {}).items())}
            for name, candidate in resolved.items():
                expected = lock["packages"][name].get("integrity")
                actual = integrity(candidate.directory)
                if actual != expected:
                    raise PkgError(
                        'package "{}" {} no longer matches {} (integrity {} expected, found '
                        "{}) - its source changed after it was locked".format(
                            name, show(candidate.version), LOCKFILE, expected, actual))
            check_graph(manifest, resolved, lock, accepted, out)
            for name, candidate in resolved.items():
                recorded = lock["packages"][name].get("capabilities")
                if recorded is not None and recorded != candidate.manifest["capabilities"]:
                    raise PkgError('package "{}" declares {} now, and {} recorded {} - run install without --frozen '
                                   "to review the change".format(name, candidate.manifest["capabilities"] or "nothing",
                                                                 LOCKFILE, recorded or "nothing"))
            new_text = text
            if lock.get("lockfile_version") != LOCK_VERSION and not frozen:
                new_text = lock_text(manifest, resolved)        # a version-1 lock is read, and written as version 2
            out("installing {} package(s) from {}".format(len(resolved), LOCKFILE))
        else:
            if lock is None:
                out("no {} yet - resolving {}".format(LOCKFILE, MANIFEST))
            else:
                out("{} changed since {} was written - resolving again".format(
                    MANIFEST, LOCKFILE))
            resolved = resolve(project_dir, manifest, sources)
            check_graph(manifest, resolved, lock, accepted, out)
            new_text = lock_text(manifest, resolved)

        place(project_dir, resolved, new_text)
        if new_text != text:
            with open(os.path.join(project_dir, LOCKFILE), "w", encoding="utf-8") as handle:
                handle.write(new_text)
            out("wrote " + LOCKFILE)
        # Last: until this exists and matches nova.lock, the interpreter
        # refuses to import from .nova_modules, so an interrupted install
        # can never be mistaken for a finished one.
        with open(os.path.join(project_dir, MODULES, INSTALLED), "w", encoding="utf-8") as handle:
            handle.write(new_text)
        for name, candidate in sorted(resolved.items()):
            out("  {} {}".format(name, show(candidate.version)))
    finally:
        sources.close()


def place(project_dir, resolved, text):
    modules = os.path.join(project_dir, MODULES)
    if os.path.isdir(modules):
        shutil.rmtree(modules)
    os.makedirs(modules)
    with open(os.path.join(modules, ".gitignore"), "w", encoding="utf-8") as handle:
        handle.write("# Installed by nova-pkg from nova.lock - never commit these.\n*\n")
    for name, candidate in sorted(resolved.items()):
        copy_package(candidate.directory, os.path.join(modules, *name.split("/")))


def verify(project_dir, out=print):
    """Problems with the installed packages, as a list of messages."""
    read_manifest(project_dir, "the project " + project_dir, root=True)
    lock, text = read_lock(project_dir)
    if lock is None:
        return ["there is no {} - run install".format(LOCKFILE)]
    problems = []
    manifest = read_manifest(project_dir, "the project", root=True)
    if not lock_matches(lock, manifest):
        problems.append("{} is out of date with {} - run install".format(LOCKFILE, MANIFEST))
    modules = os.path.join(project_dir, MODULES)
    installed = os.path.join(modules, INSTALLED)
    if not os.path.isfile(installed):
        problems.append("{} has not been installed - run install".format(LOCKFILE))
    else:
        with open(installed, "r", encoding="utf-8") as handle:
            if handle.read() != text:
                problems.append("{} changed since the last install - run install".format(
                    LOCKFILE))
    for name, entry in sorted(lock.get("packages", {}).items()):
        directory = os.path.join(modules, *name.split("/"))
        if not os.path.isdir(directory):
            problems.append('package "{}" is missing from {}'.format(name, MODULES))
        elif integrity(directory) != entry.get("integrity"):
            problems.append('package "{}" was changed after it was installed - run install '
                            "to restore it".format(name))
    expected = {name.split("/")[0] for name in lock.get("packages", {})} | {INSTALLED, ".gitignore"}
    if os.path.isdir(modules):
        for extra in sorted(set(os.listdir(modules)) - expected):
            problems.append("{}/{} is not in {}".format(MODULES, extra, LOCKFILE))
        owners = {}
        for name in lock.get("packages", {}):
            if "/" in name:
                owners.setdefault(name.split("/")[0], set()).add(name.split("/")[1])
        for owner, names in sorted(owners.items()):
            folder = os.path.join(modules, owner)
            if os.path.isdir(folder):
                for extra in sorted(set(os.listdir(folder)) - names):
                    problems.append("{}/{}/{} is not in {}".format(MODULES, owner, extra, LOCKFILE))
    return problems


def init(directory, name, out=print):
    """Write a version-2 nova.json for a new project or package here."""
    path = os.path.join(directory, MANIFEST)
    if os.path.exists(path):
        raise PkgError("{} already exists - edit it instead".format(path))
    name = name or re.sub(r"[^a-z0-9._-]+", "-", os.path.basename(os.path.abspath(directory)).lower()).strip("-._")
    if not (NAME.match(name) or SCOPED_NAME.match(name)):
        raise PkgError('"{}" is not a package name - write lowercase letters, digits, ".", "_" and "-", as '
                       '"math-utils" or "owner/name"'.format(name))
    running = running_version()
    manifest = {"name": name, "version": "0.1.0"}
    if running:
        manifest["nova"] = "^{}.{}.0".format(running[0], running[1])
    manifest.update({"main": "main.nova", "capabilities": [], "dependencies": {}})
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, indent=2) + "\n")
    out("wrote {} for {}".format(path, name))


def capabilities(project_dir, only, out=print):
    """What each installed package declares and what its files can refer to ([pkg.capabilities])."""
    manifest = read_manifest(project_dir, "the project " + project_dir, root=True)
    lock, _ = read_lock(project_dir)
    if lock is None:
        raise PkgError("there is no {} - run install".format(LOCKFILE))
    names = sorted(lock.get("packages", {}))
    if only is not None:
        if only not in names:
            raise PkgError('"{}" is not an installed package (installed: {})'.format(only, ", ".join(names) or "none"))
        names = [only]
    needed = set()
    for name in names:
        directory = os.path.join(project_dir, MODULES, *name.split("/"))
        if not os.path.isdir(directory):
            raise PkgError('package "{}" is not installed - run install'.format(name))
        package = read_manifest(directory, 'package "{}"'.format(name))
        used = scan_package(directory)
        needed.update(package["capabilities"])
        out("{} {}".format(name, lock["packages"][name].get("version")))
        out("  declares: {}".format(", ".join(package["capabilities"]) or "nothing"))
        if used:
            for capability in sorted(used):
                files = sorted({"{} in {}".format(n, f) for f, n in used[capability]})
                out("  uses:     {} ({})".format(capability, "; ".join(files)))
        else:
            out("  uses:     nothing")
        for capability in sorted(set(used) - set(package["capabilities"])):
            out("  NOT DECLARED: {}".format(capability))
    policy = manifest.get("policy", {}).get("capabilities")
    out("the packages need: {}".format(", ".join(sorted(needed)) or "nothing"))
    out("policy: {}".format("no limit" if policy is None else ", ".join(policy) or "nothing is allowed"))


# ---------------------------------------------------------------------------
# Packing and publishing ([pkg.registry])
# ---------------------------------------------------------------------------

def glob_regex(pattern):
    """A `files` pattern as a regular expression: `*` is within one folder level, `**` is any depth."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def package_members(directory, manifest):
    """{path: bytes} of the files a package is made of: those the manifest's "files" list names (every .nova, .json and
    .md file, LICENSE and NOTICE if it has none), nova.json always, and its entry file; nothing else is in the package."""
    patterns = [glob_regex(entry) for entry in manifest.get("files", [])]
    members = {}
    for relative in package_files(directory):
        if registry_protocol.safe_member_name(relative) is not None:
            continue                                     # not a kind of file a package holds
        if relative != MANIFEST and patterns and not any(pattern.match(relative) for pattern in patterns):
            continue
        if registry_protocol.SECRET_NAMES.match(relative.split("/")[-1]):
            raise PkgError("{} looks like a secret (a key, a credential or an .env file) and would be packed - remove it, "
                           "or leave it out of \"files\"".format(relative))
        with open(os.path.join(directory, relative), "rb") as handle:
            members[relative] = handle.read(registry_protocol.MAX_FILE_BYTES + 1)
    members[MANIFEST] = open(os.path.join(directory, MANIFEST), "rb").read()
    main = manifest.get("main", "main.nova")
    if main not in members:
        raise PkgError('the entry file "{}" ("main" in {}) is not among the files to pack'.format(main, MANIFEST))
    return members


def pack(project_dir, out=print, scan=True):
    """(archive bytes, manifest, files): the deterministic archive of this package, after the checks of publishing: the
    manifest is valid, and the capability check of [pkg.capabilities] passes on the very files that are packed."""
    manifest = read_manifest(project_dir, "the package " + project_dir, root=True)
    members = package_members(project_dir, manifest)
    try:
        archive = registry_protocol.build_archive(members)
    except RegistryError as problem:
        raise PkgError(str(problem))
    if scan:
        scratch = tempfile.mkdtemp(prefix="nova-pack-")
        try:
            target = os.path.join(scratch, "package")
            registry_protocol.extract_archive(archive, target)
            check_capabilities(manifest["name"], target, manifest, out)
        except RegistryError as problem:
            raise PkgError(str(problem))
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    return archive, manifest, members


def archive_file_name(manifest):
    return "{}-{}.tar".format(manifest["name"].replace("/", "-"), show(manifest["_version"]))


def read_keys(paths):
    if not paths:
        raise PkgError("this needs a signing key: --key FILE (make one with: nova-pkg keygen --out FILE)")
    try:
        return [registry_protocol.read_key_file(path) for path in paths]
    except RegistryError as problem:
        raise PkgError(str(problem))


def command_pack(project_dir, options, out=print):
    archive, manifest, members = pack(project_dir, out=out)
    folder = options.get("out") or os.getcwd()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, archive_file_name(manifest))
    with open(path, "wb") as handle:
        handle.write(archive)
    out("packed {} files into {}".format(len(members), path))
    out("sha256-" + registry_protocol.sha256_hex(archive))


def command_publish(project_dir, options, out=print):
    registry_dir = options.get("registry")
    if not registry_dir or registry_protocol.is_url(registry_dir):
        raise PkgError("publish writes to a registry folder: --registry DIR (an https registry is written by whoever runs it)")
    archive, manifest, members = pack(project_dir, out=out)
    if not SCOPED_NAME.match(manifest["name"]):
        raise PkgError('a published package needs a name with an owner, "owner/name" (it is "{}")'.format(manifest["name"]))
    if "license" not in manifest:
        out('nova-pkg: warning: {} has no "license" - say how it may be used'.format(MANIFEST))
    keys = read_keys(options.get("key", []))
    try:
        publisher = registry_protocol.Publisher(registry_dir, keys, name=options.get("registry-name"),
                                                expires_days=int(options.get("expires-days", 365)))
        publisher.add_version(manifest["name"], show(manifest["_version"]), archive, manifest)
        files = publisher.files() if options.get("dry-run") else publisher.write()
    except RegistryError as problem:
        raise PkgError(str(problem))
    verb = "would write" if options.get("dry-run") else "wrote"
    out("{} {} {}".format("publishing" if not options.get("dry-run") else "dry run:", manifest["name"], show(manifest["_version"])))
    for relative in sorted(files):
        out("  {} {} ({} bytes)".format(verb, relative, len(files[relative])))
    out("sha256-" + registry_protocol.sha256_hex(archive))
    out("files packed: " + ", ".join(sorted(members)))


def command_yank(project_dir, version, options, out=print, restore=False):
    manifest = read_manifest(project_dir, "the package " + project_dir, root=True)
    if not options.get("registry"):
        raise PkgError("--registry DIR is needed")
    parse_version(version, "the version to yank")
    keys = read_keys(options.get("key", []))
    try:
        publisher = registry_protocol.Publisher(options["registry"], keys)
        publisher.yank(manifest["name"], version, yanked=not restore)
        publisher.write()
    except RegistryError as problem:
        raise PkgError(str(problem))
    out("{} {} {}: ranges no longer choose it; a lockfile that names it still installs it".format(
        "restored" if restore else "yanked", manifest["name"], version))


def command_revoke(options, out=print):
    if not options.get("registry"):
        raise PkgError("--registry DIR is needed")
    if not options.get("archive") and not options.get("keyid"):
        raise PkgError("name what to revoke: --archive SHA256 or --keyid ID")
    keys = read_keys(options.get("key", []))
    archive_hash = (options.get("archive") or "").replace("sha256-", "") or None
    if archive_hash and not registry_protocol.SHA.match(archive_hash):
        raise PkgError("--archive is the 64-digit SHA-256 of the archive (as pack and publish print it)")
    try:
        publisher = registry_protocol.Publisher(options["registry"], keys)
        publisher.revoke(archive_hash=archive_hash, keyid=options.get("keyid"), reason=options.get("reason", ""))
        publisher.write()
    except RegistryError as problem:
        raise PkgError(str(problem))
    out("revoked: nothing signed or packed as that is installed from this registry any more")


def command_keygen(options, out=print):
    path = options.get("out")
    if not path:
        raise PkgError("--out FILE says where to write the key (it is secret: keep it off the registry and out of git)")
    key = registry_protocol.generate_key()
    try:
        registry_protocol.write_key_file(path, key)
    except RegistryError as problem:
        raise PkgError(str(problem))
    out("wrote {} (keep it secret)".format(path))
    out('public key, for "registryKeys" in nova.json: {}'.format(key["public"]))
    out("key id: {}".format(registry_protocol.key_id(key["public"])))


USAGE = """usage: nova-pkg.py [--project DIR] COMMAND
  install [--frozen] [--accept-capabilities LIST]      resolve, lock and install
  verify                                               check .nova_modules against nova.lock
  init [NAME]                                          write a nova.json here
  capabilities [PACKAGE]                               what installed packages declare and use
  keygen --out FILE                                    make a signing key for a registry
  pack [--out DIR]                                     build this package's deterministic archive
  publish --registry DIR --key FILE [--key FILE ...] [--dry-run] [--expires-days N] [--registry-name NAME]
  yank VERSION --registry DIR --key FILE               ranges stop choosing a version
  revoke --registry DIR --key FILE (--archive SHA256 | --keyid ID) [--reason TEXT]"""

VALUE_OPTIONS = {"--registry": "registry", "--key": "key", "--out": "out", "--expires-days": "expires-days",
                 "--registry-name": "registry-name", "--archive": "archive", "--keyid": "keyid", "--reason": "reason",
                 "--accept-capabilities": "accept"}
FLAG_OPTIONS = {"--dry-run": "dry-run", "--frozen": "frozen"}
COMMANDS = ("install", "verify", "init", "capabilities", "keygen", "pack", "publish", "yank", "unyank", "revoke")


def parse_options(args):
    """(positional arguments, options): `--key` may repeat; an unknown option or a missing value is None."""
    positional, options, i = [], {}, 0
    while i < len(args):
        arg = args[i]
        if arg in FLAG_OPTIONS:
            options[FLAG_OPTIONS[arg]] = True
        elif arg in VALUE_OPTIONS and i + 1 < len(args):
            name = VALUE_OPTIONS[arg]
            if name == "key":
                options.setdefault("key", []).append(args[i + 1])
            else:
                options[name] = args[i + 1]
            i += 1
        elif arg.startswith("--"):
            return None, None
        else:
            positional.append(arg)
        i += 1
    return positional, options


ALLOWED = {"install": {"frozen", "accept"}, "verify": set(), "init": set(), "capabilities": set(), "keygen": {"out"},
           "pack": {"out"}, "publish": {"registry", "key", "dry-run", "expires-days", "registry-name"},
           "yank": {"registry", "key"}, "unyank": {"registry", "key"}, "revoke": {"registry", "key", "archive", "keyid", "reason"}}
POSITIONAL = {"install": 0, "verify": 0, "init": 1, "capabilities": 1, "keygen": 0, "pack": 0, "publish": 0, "yank": 1,
              "unyank": 1, "revoke": 0}


def main(argv, out=print):
    args = argv[1:]
    project = None
    if args[:1] == ["--project"] and len(args) >= 2:
        project, args = args[1], args[2:]
    command, rest = (args[0], args[1:]) if args else (None, [])
    positional, options = parse_options(rest) if command in COMMANDS else (None, None)
    if (positional is None or set(options) - ALLOWED[command]
            or len(positional) > POSITIONAL[command] or (command in ("yank", "unyank") and not positional)):
        print(USAGE, file=sys.stderr)
        return 2
    try:
        if command == "init":
            init(os.path.abspath(project or os.getcwd()), positional[0] if positional else None, out=out)
            return 0
        if command == "keygen":
            command_keygen(options, out=out)
            return 0
        if command == "revoke":
            command_revoke(options, out=out)
            return 0
        project_dir = find_project(project or os.getcwd())
        if command == "install":
            accepted = [c for c in options.get("accept", "").split(",") if c]
            for name in accepted:
                if name not in CAPABILITIES:
                    raise PkgError('--accept-capabilities names "{}", which is not a capability (the capabilities '
                                   "are: {})".format(name, ", ".join(CAPABILITIES)))
            install(project_dir, frozen=bool(options.get("frozen")), out=out, accepted=accepted)
            return 0
        if command == "capabilities":
            capabilities(project_dir, positional[0] if positional else None, out=out)
            return 0
        if command == "pack":
            command_pack(project_dir, options, out=out)
            return 0
        if command == "publish":
            command_publish(project_dir, options, out=out)
            return 0
        if command in ("yank", "unyank"):
            command_yank(project_dir, positional[0], options, out=out, restore=command == "unyank")
            return 0
        problems = verify(project_dir)
        for problem in problems:
            out("nova-pkg: " + problem)
        if not problems:
            out("all packages match " + LOCKFILE)
        return 1 if problems else 0
    except PkgError as problem:
        print("nova-pkg: error: {}".format(problem), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
