"""Build a wheel."""

from __future__ import annotations

import contextlib
import filecmp
import importlib.resources
import io
import os
import pathlib
import shutil
import subprocess
import sys
import sysconfig
import typing

import flit_core.common
import flit_core.wheel
import jinja2
import packaging.tags
import toml

from ._version import __version__ as zlig_version

# CPython puts the linkable library in "lib" on POSIX, but "libs" on Windows.
LIBDIRNAMES = {"nt": "libs", "posix": "lib"}

# Zig uses different naming schemes on Windows and other places (same formats
# on Mac and Linux when building an unversioned dynamic library).
ZIG_LIB_NAME_TEMPLATES = {"nt": "{name}.dll", "posix": "lib{name}.so"}

INTERPRETER_SHORT_NAMES = {
    "python": "py",
    "cpython": "cp",
    "pypy": "pp",
    "ironpython": "ip",
    "jython": "jy",
}

WHEEL_TEMPLATE = """\
Wheel-Version: 1.0
Generator: zlig {version}
Root-Is-Purelib: false
Tag: {tag}
"""


def _get_config_var(name: str) -> str:
    value = sysconfig.get_config_var(name)
    if value is None:
        raise NotImplementedError(f"Missing config var {name!r}")
    return value


class _VersionInfo(typing.Protocol):
    major: int
    minor: int


class _Platform(typing.NamedTuple):
    os_name: str = os.name
    py_version: _VersionInfo = sys.version_info

    @property
    def includepy(self) -> pathlib.Path:
        """Include path to Python API."""
        return pathlib.Path(_get_config_var("INCLUDEPY"))

    @property
    def libpy(self) -> pathlib.Path:
        """Linker path to Python API."""
        return pathlib.Path(sys.base_exec_prefix, LIBDIRNAMES[self.os_name])

    @property
    def python_lib_name(self) -> str:
        """The Python lib to dynamically link to.

        On Windows, we need to tell the compiler to link a pythonXY.lib file,
        so this tries to format that name. This is not needed on POSIX, so we
        simply return an empty string for it.
        """
        if os.name != "nt":
            return ""
        return f"python{self.py_version.major}{self.py_version.minor}"

    @property
    def ext_suffix(self) -> str:
        """The suffix used for an extension module."""
        return _get_config_var("EXT_SUFFIX")

    @property
    def tag(self) -> packaging.tags.Tag:
        return next(packaging.tags.sys_tags())

    @property
    def zig_lib_name_template(self) -> str:
        """The format Zig names compiles unversioned dynamic libraries."""
        return ZIG_LIB_NAME_TEMPLATES[self.os_name]


class _Extension(typing.NamedTuple):
    name: str
    patterns: typing.Sequence[str]

    @property
    def modname(self) -> str:
        """The bare (non-qualified) module name of this extension.

        For example, if an extension's full name is ``foo.bar``, this would be
        ``bar``.
        """
        return self.name.rsplit(".", 1)[-1]

    @property
    def directory_in_package(self) -> pathlib.Path:
        """The directory that contains this extension's artifact.

        For example, if an extension's full name is ``foo.bar.rex``, this would
        be ``foo/bar``.
        """
        return pathlib.Path(*self.name.split(".")[:-1])

    @property
    def varname(self) -> str:
        """Generate a Zig-safe unique identifier to use in the script.

        This is based on the extension's name, but adding a deterministic
        suffix to keep names unique.
        """
        prefix = self.name.replace(".", "_")
        suffix = self.name.count(".")
        return f"{prefix}_{suffix}"

    def get_target_path(self, platform: _Platform) -> pathlib.Path:
        """Where the extension should end up being placed."""
        tag = platform.tag
        filename = (
            f"{self.modname}."
            f"{tag.interpreter}-"
            f"{tag.platform}"
            f"{platform.ext_suffix}"
        )
        return self.directory_in_package.joinpath(filename)

    def iter_sources(self) -> typing.Iterator[pathlib.Path]:
        for pattern in self.patterns:
            yield from pathlib.Path.cwd().glob(pattern)


def _load_extension(decl: dict, module: flit_core.common.Module) -> _Extension:
    root, name = decl["name"].split(".", 1)
    if root != module.name:
        raise NotImplementedError(f"Extensions must be under '{module.name}.'")
    return _Extension(name, decl["sources"])


class WheelBuilder(flit_core.wheel.WheelBuilder):
    _extensions: typing.Sequence[_Extension]
    _platform = _Platform()

    @classmethod
    def from_pyproject_toml(
        cls,
        path: pathlib.Path,
        stream: typing.BinaryIO,
    ) -> WheelBuilder:
        self = cls.from_ini_path(path, stream)
        with path.open(encoding="utf-8") as f:
            data = toml.load(f)
        # TODO: Validation?
        self._extensions = [
            _load_extension(decl, self.module)
            for decl in data["tool"]["zlig"]["extensions"]
        ]
        self._extension_sources = {
            source.resolve()
            for ext in self._extensions
            for source in ext.iter_sources()
        }
        return self

    @property
    def wheel_filename(self) -> str:
        pure_name = super().wheel_filename
        if not self._extensions:
            return pure_name
        *parts, _, _, _ = pure_name.split("-")
        tag = self._platform.tag
        parts += [tag.interpreter, tag.abi, tag.platform]
        return "-".join(parts) + ".whl"

    def _add_file(self, full_path: str, rel_path: str) -> None:
        # HACK: Do not add extension sources to wheel.
        if pathlib.Path(full_path).resolve() in self._extension_sources:
            return
        super()._add_file(full_path, rel_path)

    def _generate_build_zig(self) -> None:
        source = importlib.resources.read_text(
            __package__,
            "build.zig.jinja2",
            encoding="utf-8",
        )
        context = {
            "extensions": self._extensions,
            "includepy": self._platform.includepy,
            "libpy": self._platform.libpy,
            "pythonlib": self._platform.python_lib_name,
        }
        rendered = jinja2.Template(source).render(context)
        path = pathlib.Path("build.zig")
        if path.exists() and path.read_text(encoding="utf-8") == rendered:
            return
        path.write_text(rendered, encoding="utf-8")

    def _run_zig_build(self) -> None:
        args = [sys.executable, "-m", "ziglang", "build"]
        subprocess.run(args, check=True)

    def _copy_artifacts(self) -> None:
        for ext in self._extensions:
            compiled = pathlib.Path(
                "zig-out",
                "lib",
                ext.directory_in_package,
                self._platform.zig_lib_name_template.format(name=ext.modname),
            )
            target = pathlib.Path(
                self.module.path,
                ext.get_target_path(self._platform),
            )
            if target.exists() and filecmp.cmp(compiled, target):
                continue
            shutil.copy2(compiled, target)

    def _compile_binaries(self) -> None:
        self._generate_build_zig()
        self._run_zig_build()
        self._copy_artifacts()

    def copy_module(self) -> None:
        # HACK: Compile binaries before Flit starts adding files.
        self._compile_binaries()
        super().copy_module()

    @contextlib.contextmanager
    def _write_to_zip(
        self,
        relname: str,
        *,
        ignore_wheel: bool = True,
    ) -> typing.Iterator[typing.TextIO]:
        # HACK: Do not write the WHEEL file.
        if ignore_wheel and relname == f"{self.dist_info}/WHEEL":
            yield io.StringIO()
            return
        with super()._write_to_zip(relname) as f:
            yield f

    def _write_wheel(self) -> None:
        """Actually wwrite the WHEEL file and its entry in RECORD."""
        name = f"{self.dist_info}/WHEEL"
        content = WHEEL_TEMPLATE.format(
            version=zlig_version,
            tag=self._platform.tag,
        )
        with self._write_to_zip(name, ignore_wheel=False) as f:
            f.write(content)

    def write_metadata(self) -> None:
        super().write_metadata()
        self._write_wheel()
