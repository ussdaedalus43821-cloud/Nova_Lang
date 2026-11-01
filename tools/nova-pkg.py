#!/usr/bin/env python3
"""
nova-pkg - NovaLang's package manager (just-in-time: resolve, lock, install).

    python3 tools/nova-pkg.py install            resolve, lock and install
    python3 tools/nova-pkg.py install --frozen   install exactly nova.lock (CI)
    python3 tools/nova-pkg.py verify             check .nova_modules is intact

Run inside a project (any directory under the one holding nova.json), or
pass --project DIR.

nova.json
    {
      "name": "my-project",
      "version": "1.0.0",
      "registry": "../registry",                  optional; else $NOVA_REGISTRY
      "main": "main.nova",                        for a package: its entry file
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

Exit status: 0 on success, 1 on any problem (the message says what to do).
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

MANIFEST = "nova.json"
LOCKFILE = "nova.lock"
MODULES = ".nova_modules"
INSTALLED = ".installed.lock"
LOCK_VERSION = 1
NAME = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
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


def read_manifest(directory, what):
    path = os.path.join(directory, MANIFEST)
    if not os.path.isfile(path):
        raise PkgError("{} has no {}".format(what, MANIFEST))
    manifest = read_json(path, "the manifest")
    if not isinstance(manifest, dict):
        raise PkgError("{} must be a JSON object".format(path))
    name = manifest.get("name")
    if not isinstance(name, str) or not NAME.match(name):
        raise PkgError('{}: "name" must be a lowercase package name such as "math-utils", '
                       "not {!r}".format(path, name))
    manifest["_version"] = parse_version(manifest.get("version"), path + ' "version"')
    dependencies = manifest.get("dependencies", {})
    if not isinstance(dependencies, dict):
        raise PkgError('{}: "dependencies" must be an object'.format(path))
    for dep_name, spec in dependencies.items():
        if not NAME.match(dep_name):
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

    def __init__(self, name, version, directory, source, manifest):
        self.name = name
        self.version = version
        self.directory = directory      # where its files are, right now
        self.source = source            # what nova.lock records
        self.manifest = manifest


class Sources:
    def __init__(self, project_dir, manifest):
        self.project_dir = project_dir
        registry = manifest.get("registry") or os.environ.get("NOVA_REGISTRY")
        self.registry = None
        self.registry_text = registry
        if registry:
            self.registry = os.path.normpath(os.path.join(project_dir, registry))
        self.scratch = tempfile.mkdtemp(prefix="nova-pkg-")
        self.git_cache = {}

    def close(self):
        shutil.rmtree(self.scratch, ignore_errors=True)

    def available(self, name, wanted_by):
        """Every registry version of `name`, newest first."""
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

    def from_registry(self, name, version):
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
# The lockfile
# ---------------------------------------------------------------------------

def lock_text(manifest, resolved):
    packages = {}
    for name, candidate in sorted(resolved.items()):
        packages[name] = {
            "version": show(candidate.version),
            "source": candidate.source,
            "integrity": integrity(candidate.directory),
            "dependencies": candidate.manifest["dependencies"],
        }
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
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    try:
        lock = json.loads(text)
    except ValueError as problem:
        raise PkgError("{} is not valid JSON ({}) - delete it and run install".format(
            LOCKFILE, problem))
    if not isinstance(lock, dict) or lock.get("lockfile_version") != LOCK_VERSION:
        raise PkgError("{} is not a version-{} lockfile - delete it and run install".format(
            LOCKFILE, LOCK_VERSION))
    return lock, text


def lock_matches(lock, manifest):
    """Does nova.lock still describe what nova.json asks for?"""
    return lock.get("requires") == manifest["dependencies"]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def install(project_dir, frozen=False, out=print):
    manifest = read_manifest(project_dir, "the project " + project_dir)
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
            new_text = text
            out("installing {} package(s) from {}".format(len(resolved), LOCKFILE))
        else:
            if lock is None:
                out("no {} yet - resolving {}".format(LOCKFILE, MANIFEST))
            else:
                out("{} changed since {} was written - resolving again".format(
                    MANIFEST, LOCKFILE))
            resolved = resolve(project_dir, manifest, sources)
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
        copy_package(candidate.directory, os.path.join(modules, name))


def verify(project_dir, out=print):
    """Problems with the installed packages, as a list of messages."""
    read_manifest(project_dir, "the project " + project_dir)
    lock, text = read_lock(project_dir)
    if lock is None:
        return ["there is no {} - run install".format(LOCKFILE)]
    problems = []
    manifest = read_manifest(project_dir, "the project")
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
        directory = os.path.join(modules, name)
        if not os.path.isdir(directory):
            problems.append('package "{}" is missing from {}'.format(name, MODULES))
        elif integrity(directory) != entry.get("integrity"):
            problems.append('package "{}" was changed after it was installed - run install '
                            "to restore it".format(name))
    expected = set(lock.get("packages", {})) | {INSTALLED, ".gitignore"}
    if os.path.isdir(modules):
        for extra in sorted(set(os.listdir(modules)) - expected):
            problems.append("{}/{} is not in {}".format(MODULES, extra, LOCKFILE))
    return problems


USAGE = "usage: nova-pkg.py [--project DIR] (install [--frozen] | verify)"


def main(argv, out=print):
    args = argv[1:]
    project = None
    if args[:1] == ["--project"] and len(args) >= 2:
        project, args = args[1], args[2:]
    if args not in (["install"], ["install", "--frozen"], ["verify"]):
        print(USAGE, file=sys.stderr)
        return 2
    try:
        project_dir = find_project(project or os.getcwd())
        if args[0] == "install":
            install(project_dir, frozen="--frozen" in args, out=out)
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
