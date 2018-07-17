#!/usr/bin/env python
# Copyright 2018 Bert Belder <bertbelder@gmail.com>
# All rights reserved. MIT License.

import sys
import os
from os import path
import subprocess
import tempfile


def capture_args(argsfile_path):
    with open(argsfile_path, "wb") as argsfile:
        argsfile.write("\n".join(sys.argv[1:]))


def main():
    # If ARGSFILE_PATH is set, we're recursively being invoked by ourselves
    # through rustc; write program arguments to the specified file and exit.
    argsfile_path = os.getenv("ARGSFILE_PATH")
    if argsfile_path is not None:
        return capture_args(argsfile_path)

    # Prepare the environment for rustc.
    rustc_env = os.environ.copy()

    # Make sure that when rustc invokes this script it uses the same version
    # of the python interpreter as we're currently using. On Posix systems this
    # is done making the python binary directory the first element in PATH.
    # On Windows, the wrapper script uses the PYTHON_EXE environment variable.
    if os.name == "nt":
        rustc_env["PYTHON_EXE"] = sys.executable
    else:
        python_dir = path.dirname(sys.executable)
        rustc_env["PATH"] = python_dir + path.pathsep + os.environ["PATH"]

    # On posix systems, this file itself is executable courtesy of it's shebang
    # line. On Windows, use a .cmd wrapper file.
    if os.name == "nt":
        rustc_linker_base, rustc_linker_ext = path.splitext(__file__)
        rustc_linker = rustc_linker_base + ".cmd"
    else:
        rustc_linker = __file__

    # Create a temporary file to write captured rust linker arguments to.
    # Unfortunately we can't use tempfile.NamedTemporaryFile here, because the
    # file it creates can't be open in two processes at the same time.
    argsfile_fd, argsfile_path = tempfile.mkstemp()
    rustc_env["ARGSFILE_PATH"] = argsfile_path

    try:
        # Spawn rustc and make it use this very script as its "linker".
        rustc_args = ["-Clinker=" + rustc_linker, "-Csave-temps"
                      ] + sys.argv[1:]
        subprocess.check_call(["rustc"] + rustc_args, env=rustc_env)

        # Read captured linker arguments from argsfile.
        argsfile_size = os.fstat(argsfile_fd).st_size
        argsfile_content = os.read(argsfile_fd, argsfile_size)
        args = argsfile_content.split("\n")

    finally:
        # Close and delete the temporary file.
        os.close(argsfile_fd)
        os.unlink(argsfile_path)

    # From the list of captured linker arguments, build a list of ldflags that
    # we actually need.
    ldflags = []
    next_arg_is_flag_value = False
    for arg in args:
        # Note that within the following if/elif blocks, `pass` means `arg`
        # gets included in `ldflags`. The final `else` clause filters out
        # unrecognized/unwanted flags.
        if next_arg_is_flag_value:
            # We're looking at a value that follows certain parametric flags,
            # e.g. the path in '-L <path>'.
            next_arg_is_flag_value = False
        elif arg.endswith(".rlib"):
            # Built-in Rust library, e.g. `libstd-8524caae8408aac2.rlib`.
            pass
        elif arg.endswith(".crate.allocator.rcgu.o"):
            # This file is needed because it contains certain allocator
            # related symbols (e.g. `__rust_alloc`, `__rust_oom`).
            # The Rust compiler normally generates this file just before
            # linking an executable. We pass `-Csave-temps` to rustc so it
            # doesn't delete the file when it's done linking.
            pass
        elif arg.endswith(".lib") and not arg.startswith("msvcrt"):
            # Include most Windows static/import libraries (e.g. `ws2_32.lib`).
            # However we exclude Rusts choice of C runtime (mvcrt*.lib), since
            # it makes poor choices.
            pass
        elif arg == "-l" or arg == "-L":
            # `-l <name>`: Link with library (GCC style).
            # `-L <path>`: Linker search path (GCC style).
            next_arg_is_flag_value = True  # Ensure flag argument is captured.
        elif arg == "-Wl,--start-group" or arg == "-Wl,--end-group":
            # Start or end of an archive group (GCC style).
            pass
        elif arg.upper().startswith("/LIBPATH:"):
            # `/LIBPATH:<path>`: Linker search path (Microsoft style).
            pass
        else:
            # No matches -- don't add this flag to ldflags.
            continue

        ldflags += [arg]

    # Write the filtered ldflags to stdout, separated by newline characters.
    sys.stdout.write("\n".join(ldflags))


if __name__ == '__main__':
    sys.exit(main())
