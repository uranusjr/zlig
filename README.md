# CPython Extension Module Support for Flit

This is a PEP 517 build backend piggybacking (and hacking) Flit to support
building C extensions.

Mostly a proof-of-concept, but could be further developed into something more
generally useful if Flit can better support hooking into the build system.

## Features

* Can build C extensions.
* Does not require a user to pre-install a compiler.
* Very good caching; incremental compilation performs much better than
  setuptools from my totally non-scientific observation.
* Produces a wheel with appropriate-ish tag for distribution.

## Limitations

* Since Flit only supports one single top-level Python module/package, and
  enforces the existence of that file/directory, this can only build extensions
  as a *submodule* of a package right now.
* Since Flit's automatic metadata introspection (read version and description
  from module) needs to import the top-level module/package, you either need
  to jump through some hooks to make those work without the extension being
  available, or only write metadata in `pyproject.toml`.
* Slower "cold" compilation time compared to setuptools and platform-provided
  compilers.
* Does not allow custom compiler flags (possible to implement).
* Only handles C for now. I believe it's possible to support C++ (and Zig).
* Probably more, setuptools has so many years behind it and can therefore cover
  many edge cases I've never dreamt of.


## Characteristics

* Compiles extension modules directly into the top-level Python package. This
  makes it possible to run the extension "in-place" without installing, which
  I find useful. But it makes the source tree a bit messy (you probably need
  to run `git clean` once in a while to keep things sane).


## How-To

There's a minimal example in `examples/demo` that has all the needed parts.

```toml
[build-system]
requires = ["zlig"]
build-backend = "zlig"

# ... Project metadata declaration.

[tool.flit.sdist]
# Exclude extension modules from sdist.
exclude = ["src/demo/*.so"]

[tool.zlig]
# Declare extensions and its sources.
extensions = [{name = "demo.demo", sources = ["src/**/*.c"]}]
```

Add the following entries to your `.gitignore`:

```
/build.zig
/zig-cache/
/zig-out/
# Flit builds things to /dist so add it too.
# Also *.pyd and *.so files but you should've already ignored them.
```


## Details

As a PEP 517 backend, this module simply bridges most of Flit's build API, but
re-implements `build_wheel` to do some additional things:

* Compile extension modules before handing the package to Flit, which would add
  all the files (including compiled extensions) into the wheel.
* When adding a file to the wheel, first check whether the file is an
  extension's source and exclude it.
* Override Flit's logic deciding a wheel's file name to use a platform-specific
  wheel tag instead.

Compilation magic is provided by [Zig]'s build system. A working Zig compiler
is installed as a [PEP 517 build dependency](https://pypi.org/project/ziglang).
During compilation, the backend generates a build script (`build.zig`) from
`pyproject.toml`, and call the Zig compiler to do the rest. After compilation,
those binaries are copied to the location Flit expects to fine modules.


[Zig]: https://ziglang.org/
