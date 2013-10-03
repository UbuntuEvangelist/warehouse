# Copyright 2013 Donald Stufft
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import datetime
import functools
import os
import os.path
import shutil
import textwrap
import tempfile

import invoke


def _out(name, message):
    print("[\033[1;37m{}\033[0m] {}".format(name, message))


@invoke.task(name="test")
def release_test(database=None, verbose=False, **kwargs):
    out = functools.partial(_out, "release.test")

    hide = "out" if not verbose else None

    if database:
        os.environ["WAREHOUSE_DATABASE_URL"] = database

    out("Creating a temporary directory to export Warehouse to")
    curdir = os.getcwd()
    tmpdir = tempfile.mkdtemp()
    tmpdir = tmpdir if tmpdir.endswith("/") else tmpdir + "/"

    try:
        invoke.run("git checkout-index -f -a --prefix={}".format(tmpdir),
            hide=hide,
        )
        os.chdir(tmpdir)

        # Run all our various tests one last time before
        envs = set(invoke.run("tox -l", hide=hide).stdout.split())
        envs -= {"packaging"}  # Packaging tests require a git clone
        out("Running tests: {}".format(", ".join(envs)))

        for env in envs:
            out("Running the {} tests".format(env))
            invoke.run("tox -e {}".format(env), hide=hide)
    finally:
        os.chdir(curdir)
        shutil.rmtree(tmpdir, ignore_errors=True)


@invoke.task(name="build")
def release_build(verbose=False, **kwargs):
    """
    Builds the source distribution.
    """
    out = functools.partial(_out, "release.build")

    hide = "out" if not verbose else None

    # Determine the next version number using git tags
    version_series = datetime.datetime.utcnow().strftime("%y.%m")
    version_series = ".".join([str(int(x)) for x in version_series.split(".")])
    tags = invoke.run("git tag -l 'v{}.*'".format(version_series), hide=hide)
    versions = sorted(tags.stdout.split())
    version_num = int(versions[-1].rsplit(".")[-1]) + 1 if versions else 0
    version = ".".join([version_series, str(version_num)])
    version = ".".join([str(int(x)) for x in version.split(".")])
    out("New release will be version {}".format(version))

    # Determine our build number (It's equal to our current git revision)
    build_tag = invoke.run("git rev-parse HEAD", hide=hide).stdout[:7]
    out("Using build tag: '{}'".format(build_tag))

    # Create a template for the warehouse/__about__.py that we'll use
    about_template = textwrap.dedent("""
        # Copyright 2013 Donald Stufft
        #
        # Licensed under the Apache License, Version 2.0 (the "License");
        # you may not use this file except in compliance with the License.
        # You may obtain a copy of the License at
        #
        # http://www.apache.org/licenses/LICENSE-2.0
        #
        # Unless required by applicable law or agreed to in writing, software
        # distributed under the License is distributed on an "AS IS" BASIS,
        # WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
        # See the License for the specific language governing permissions and
        # limitations under the License.
        from __future__ import absolute_import, division, print_function
        from __future__ import unicode_literals

        # This file is automatically generated, do not edit it


        __all__ = [
            "__title__", "__summary__", "__uri__", "__version__",
            "__author__", "__email__", "__license__", "__copyright__",
        ]

        __title__ = "warehouse"
        __summary__ = "Next Generation Python Package Repository"
        __uri__ = "https://github.com/dstufft/warehouse"

        __version__ = "{version}"
        __build__ = "{build}"

        __author__ = "Donald Stufft"
        __email__ = "donald@stufft.io"

        __license__ = "Apache License, Version 2.0"
        __copyright__ = "Copyright 2013 Donald Stufft"
    """)
    about_path = os.path.join(
        os.path.abspath(os.path.dirname(__file__)),
        "warehouse",
        "__about__.py"
    )

    # Render warehouse/__about__.py with the release version
    with open(about_path, "w") as about:
        about.write(about_template.format(
            version=version,
            build=build_tag,
        ).lstrip())
    invoke.run("git add warehouse/__about__.py", hide=hide)
    invoke.run("git commit -m 'Generate the release __about__.py (version={} "
               "build={})'".format(version, build_tag),
        hide=hide,
    )
    out("warehouse/__about__.py generated with release values")

    # Create a tag
    invoke.run("git tag -s -m 'Released version v{0} ({1})' v{0}".format(
        version,
        build_tag,
    ), hide=True if not verbose else None)

    out("Creating a temporary directory to export Warehouse to")
    curdir = os.getcwd()
    tmpdir = tempfile.mkdtemp()
    tmpdir = tmpdir if tmpdir.endswith("/") else tmpdir + "/"
    try:
        # Store our current branch
        current_branch = invoke.run("git rev-parse --abbrev-ref HEAD",
            hide=hide,
        ).stdout.strip()

        # Checkout our tag
        invoke.run(
            "git checkout v{}".format(version),
            hide=True if not verbose else None,
        )

        # Export our repository into a temporary directory
        invoke.run("git checkout-index -f -a --prefix={}".format(tmpdir),
            hide=hide,
        )

        # Switch back to our original branch
        invoke.run(
            "git checkout {}".format(current_branch),
            hide=True if not verbose else None,
        )

        # Change to the temporary directory
        os.chdir(tmpdir)

        # Create our distributions
        os.makedirs("dist")
        for dist_type in ["sdist", "bdist_wheel"]:
            filenames = set(os.listdir("dist"))
            invoke.run("python setup.py {}".format(dist_type), hide=hide)
            filename = (set(os.listdir("dist")) - filenames).pop()
            out("Generated {} ({})".format(dist_type, filename))

        # Change back to our normal directory
        os.chdir(curdir)

        # Move the built distributions into our dist directory
        shutil.rmtree(os.path.abspath("dist"), ignore_errors=True)
        shutil.move(
            os.path.join(tmpdir, "dist"),
            os.path.abspath("dist"),
        )
    finally:
        os.chdir(curdir)
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Render warehouse/__about__.py with the development versions
    next_version = ".".join([version_series, str(version_num + 1)])
    next_version = ".".join([str(int(x)) for x in next_version.split(".")])
    next_version += ".dev0"
    build_tag = "<development>"
    with open(about_path, "w") as about:
        about.write(about_template.format(
            version=next_version,
            build=build_tag,
        ).lstrip())
    invoke.run("git add warehouse/__about__.py", hide=hide)
    invoke.run(
        "git commit -m 'Generate the development __about__.py'".format(
            next_version,
            build_tag,
        ),
        hide=hide,
    )
    out("warehouse/__about__.py generated with development values")


@invoke.task(name="upload")
def release_upload(repository=None, verbose=False, **kwargs):
    out = functools.partial(_out, "release.upload")

    out("Uploading to {}".format("PyPI" if repository is None else repository))
    invoke.run("twine upload --sign{} dist/*".format(
        "" if repository is None else " -r {}".format(repository)
    ), hide="both" if not verbose else None)
    out("Uploaded.")


@invoke.task(
    default=True,
    name="all",
    pre=["release.test", "release.build", "release.upload"],
)
def release_all(repository=None, database=None, verbose=False, **kwargs):
    pass


ns = invoke.Collection(
    release=invoke.Collection(
        release_test,
        release_build,
        release_upload,
        release_all,
    ),
)
