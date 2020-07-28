#
# -------------------------------------------------------------------------
#
#  Part of the CodeChecker project, under the Apache License v2.0 with
#  LLVM Exceptions. See LICENSE for license information.
#  SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# -------------------------------------------------------------------------
""" CTU function test."""


import json
import os
import shutil
import unittest
import zipfile

from codechecker_analyzer import host_check

from libtest import env
from libtest import project
from libtest.codechecker import call_command

NO_CTU_MESSAGE = "CTU is not supported"
NO_DISPLAY_CTU_PROGRESS = "-analyzer-display-ctu-progress is not supported"
NO_CTU_ON_DEMAND_MESSAGE = "CTU-on-demand is not supported"


def makeSkipUnlessAttributeFound(attribute, message):
    def deco(f):
        def wrapper(self, *args, **kwargs):
            if not getattr(self, attribute):
                self.skipTest(message)
            else:
                f(self, *args, **kwargs)
        return wrapper
    return deco


skipUnlessCTUCapable = makeSkipUnlessAttributeFound(
    'ctu_capable', NO_CTU_MESSAGE)
skipUnlessCTUDisplayCapable = makeSkipUnlessAttributeFound(
    'ctu_display_progress_capable', NO_DISPLAY_CTU_PROGRESS)
skipUnlessCTUOnDemandCapable = makeSkipUnlessAttributeFound(
    'ctu_on_demand_capable', NO_CTU_ON_DEMAND_MESSAGE)


class TestCtuFailure(unittest.TestCase):
    """ Test CTU functionality. """

    def setUp(self):
        """ Set up workspace."""

        # TEST_WORKSPACE is automatically set by test package __init__.py .
        self.test_workspace = os.environ['TEST_WORKSPACE']

        test_class = self.__class__.__name__
        print('Running ' + test_class + ' tests in ' + self.test_workspace)

        # Get the CodeChecker cmd if needed for the tests.
        self._codechecker_cmd = env.codechecker_cmd()
        self.env = env.codechecker_env()
        self.report_dir = os.path.join(self.test_workspace, 'reports')
        os.makedirs(self.report_dir)

    def __set_up_test_dir(self, project_path):
        self.test_dir = project.path(project_path)

        # Get if clang is CTU-capable or not.
        cmd = [self._codechecker_cmd, 'analyze', '-h']
        output, _ = call_command(cmd, cwd=self.test_dir, env=self.env)
        self.ctu_capable = '--ctu-' in output
        print("'analyze' reported CTU-compatibility? " + str(self.ctu_capable))

        self.ctu_on_demand_capable = '--ctu-ast-mode' in output
        print("'analyze' reported CTU-on-demand-compatibility? "
              + str(self.ctu_on_demand_capable))

        self.ctu_display_progress_capable = \
            host_check.has_analyzer_config_option(self.__getClangSaPath(),
                                                  'display-ctu-progress',
                                                  self.env)

        print("Has display-ctu-progress=true? " +
              str(self.ctu_display_progress_capable))

        # Fix the "template" build JSONs to contain a proper directory
        # so the tests work.
        raw_buildlog = os.path.join(self.test_dir, 'buildlog.json')
        with open(raw_buildlog,
                  encoding="utf-8", errors="ignore") as log_file:
            build_json = json.load(log_file)
            for command in build_json:
                command['directory'] = self.test_dir

        self.__old_pwd = os.getcwd()
        os.chdir(self.test_workspace)
        self.buildlog = os.path.join(self.test_workspace, 'buildlog.json')
        with open(self.buildlog, 'w',
                  encoding="utf-8", errors="ignore") as log_file:
            json.dump(build_json, log_file)

    def tearDown(self):
        """ Tear down workspace."""

        shutil.rmtree(self.report_dir, ignore_errors=True)
        os.chdir(self.__old_pwd)

    @skipUnlessCTUCapable
    @skipUnlessCTUDisplayCapable
    def test_ctu_logs_ast_import(self):
        """ Test that Clang indeed logs the AST import events.
        """
        self.__set_up_test_dir('ctu_failure')

        output = self.__do_ctu_all(on_demand=False,
                                   extra_args=["--verbose", "debug"])
        self.assertIn("CTU loaded AST file", output)

    @skipUnlessCTUCapable
    @skipUnlessCTUDisplayCapable
    @skipUnlessCTUOnDemandCapable
    def test_ctu_on_demand_logs_ast_import(self):
        """ Test that Clang indeed logs the AST import events when using
        on-demand mode.
        """
        self.__set_up_test_dir('ctu_on_demand_failure')

        output = self.__do_ctu_all(on_demand=True,
                                   extra_args=["--verbose", "debug"])
        self.assertIn("CTU loaded AST file", output)

    @skipUnlessCTUCapable
    @skipUnlessCTUDisplayCapable
    def test_ctu_failure_zip(self):
        """ Test the failure zip contains the source of imported TU
        """
        self.__set_up_test_dir('ctu_failure')

        # The below special checker `ExprInspection` crashes when a function
        # with a specified name is analyzed.
        output = self.__do_ctu_all(on_demand=False,
                                   extra_args=[
                                       "--verbose", "debug",
                                       "-e", "debug.ExprInspection"
                                   ])

        # lib.c should be logged as its AST is loaded by Clang
        self.assertRegex(output, r"CTU loaded AST file: .*lib\.c.ast")

        # We expect a failure archive to be in the failed directory.
        failed_dir = os.path.join(self.report_dir, "failed")
        failed_files = os.listdir(failed_dir)

        self.assertEqual(len(failed_files), 1)
        # Ctu should fail during analysis of main.c
        self.assertIn("main.c", failed_files[0])

        fail_zip = os.path.join(failed_dir, failed_files[0])

        with zipfile.ZipFile(fail_zip, 'r') as archive:
            files = archive.namelist()
            self.assertIn("build-action", files)
            self.assertIn("analyzer-command", files)

            def check_source_in_archive(source_in_archive):
                source_file = os.path.join(self.test_dir, source_in_archive)
                source_in_archive = os.path.join("sources-root",
                                                 source_file.lstrip('/'))
                self.assertIn(source_in_archive, files)
                # Check file content.
                with archive.open(source_in_archive, 'r') as archived_code:
                    with open(source_file, 'r',
                              encoding="utf-8",
                              errors="ignore") as source_code:
                        self.assertEqual(archived_code.read().decode("utf-8"),
                                         source_code.read())

            check_source_in_archive("main.c")
            check_source_in_archive("lib.c")

    @skipUnlessCTUCapable
    @skipUnlessCTUDisplayCapable
    @skipUnlessCTUOnDemandCapable
    def test_ctu_on_demand_failure_zip(self):
        """ Test the failure zip contains the source of imported TU when using
        on-demand mode.
        """
        self.__set_up_test_dir('ctu_on_demand_failure')

        # The below special checker `ExprInspection` crashes when a function
        # with a specified name is analyzed.
        output = self.__do_ctu_all(on_demand=True,
                                   extra_args=[
                                       "--verbose", "debug",
                                       "-e", "debug.ExprInspection"
                                   ])

        # lib.c should be logged as its AST is loaded by Clang
        self.assertRegex(output, r"CTU loaded AST file: .*lib\.c")

        # We expect a failure archive to be in the failed directory.
        failed_dir = os.path.join(self.report_dir, "failed")
        failed_files = os.listdir(failed_dir)

        self.assertEqual(len(failed_files), 1)
        # Ctu should fail during analysis of main.c
        self.assertIn("main.c", failed_files[0])

        fail_zip = os.path.join(failed_dir, failed_files[0])

        with zipfile.ZipFile(fail_zip, 'r') as archive:
            files = archive.namelist()
            self.assertIn("build-action", files)
            self.assertIn("analyzer-command", files)

            def check_source_in_archive(source_in_archive):
                source_file = os.path.join(self.test_dir, source_in_archive)
                source_in_archive = os.path.join("sources-root",
                                                 source_file.lstrip('/'))
                self.assertIn(source_in_archive, files)
                # Check file content.
                with archive.open(source_in_archive, 'r') as archived_code:
                    with open(source_file, 'r',
                              encoding="utf-8",
                              errors="ignore") as source_code:
                        self.assertEqual(archived_code.read().decode("utf-8"),
                                         source_code.read())

            check_source_in_archive("main.c")
            check_source_in_archive("lib.c")

    @skipUnlessCTUCapable
    @skipUnlessCTUDisplayCapable
    def test_ctu_failure_zip_with_headers(self):
        """
        Test the failure zip contains the source of imported TU and all the
        headers on which the TU depends.
        """
        self.__set_up_test_dir('ctu_failure_with_headers')

        # The below special checker `ExprInspection` crashes when a function
        # with a specified name is analyzed.
        output = self.__do_ctu_all(on_demand=False,
                                   extra_args=[
                                       "--verbose", "debug",
                                       "-e", "debug.ExprInspection"
                                   ])

        # lib.c should be logged as its AST is loaded by Clang
        self.assertRegex(output, r"CTU loaded AST file: .*lib\.c.ast")

        # We expect a failure archive to be in the failed directory.
        failed_dir = os.path.join(self.report_dir, "failed")
        failed_files = os.listdir(failed_dir)
        self.assertEqual(len(failed_files), 1)
        # Ctu should fail during analysis of main.c
        self.assertIn("main.c", failed_files[0])

        fail_zip = os.path.join(failed_dir, failed_files[0])

        with zipfile.ZipFile(fail_zip, 'r') as archive:
            files = archive.namelist()

            self.assertIn("build-action", files)
            self.assertIn("analyzer-command", files)

            def check_source_in_archive(source_in_archive):
                source_file = os.path.join(self.test_dir, source_in_archive)
                source_in_archive = os.path.join("sources-root",
                                                 source_file.lstrip('/'))
                self.assertIn(source_in_archive, files)
                # Check file content.
                with archive.open(source_in_archive, 'r') as archived_code:
                    with open(source_file, 'r',
                              encoding="utf-8",
                              errors="ignore") as source_code:
                        self.assertEqual(archived_code.read().decode("utf-8"),
                                         source_code.read())

            check_source_in_archive("main.c")
            check_source_in_archive("lib.c")
            check_source_in_archive("lib.h")

    @skipUnlessCTUCapable
    @skipUnlessCTUDisplayCapable
    @skipUnlessCTUOnDemandCapable
    def test_ctu_on_demand_failure_zip_with_headers(self):
        """
        Test the failure zip contains the source of imported TU and all the
        headers on which the TU depends when using on-demand mode.
        """
        self.__set_up_test_dir('ctu_on_demand_failure_with_headers')

        # The below special checker `ExprInspection` crashes when a function
        # with a specified name is analyzed.
        output = self.__do_ctu_all(on_demand=True,
                                   extra_args=[
                                       "--verbose", "debug",
                                       "-e", "debug.ExprInspection"
                                   ])

        # lib.c should be logged as its AST is loaded by Clang
        self.assertRegex(output, r"CTU loaded AST file: .*lib\.c")

        # We expect a failure archive to be in the failed directory.
        failed_dir = os.path.join(self.report_dir, "failed")
        failed_files = os.listdir(failed_dir)
        self.assertEqual(len(failed_files), 1)
        # Ctu should fail during analysis of main.c
        self.assertIn("main.c", failed_files[0])

        fail_zip = os.path.join(failed_dir, failed_files[0])

        with zipfile.ZipFile(fail_zip, 'r') as archive:
            files = archive.namelist()

            self.assertIn("build-action", files)
            self.assertIn("analyzer-command", files)

            def check_source_in_archive(source_in_archive):
                source_file = os.path.join(self.test_dir, source_in_archive)
                source_in_archive = os.path.join("sources-root",
                                                 source_file.lstrip('/'))
                self.assertIn(source_in_archive, files)
                # Check file content.
                with archive.open(source_in_archive, 'r') as archived_code:
                    with open(source_file, 'r',
                              encoding="utf-8",
                              errors="ignore") as source_code:
                        self.assertEqual(archived_code.read().decode("utf-8"),
                                         source_code.read())

            check_source_in_archive("main.c")
            check_source_in_archive("lib.c")
            check_source_in_archive("lib.h")

    @skipUnlessCTUCapable
    @skipUnlessCTUDisplayCapable
    def test_ctu_fallback(self):
        """ In case of ctu failure the non ctu analysis will be triggered.
        """
        self.__set_up_test_dir('ctu_failure')

        output = self.__do_ctu_all(on_demand=False,
                                   extra_args=[
                                       "--verbose", "debug",
                                       "-e", "debug.ExprInspection",
                                       "--ctu-reanalyze-on-failure"
                                   ])

        # lib.c should be logged as its AST is loaded by Clang
        self.assertRegex(output, r"CTU loaded AST file: .*lib\.c.ast")

        # We expect two failure archives to be in the failed directory.
        # One failure archive is produced by the CTU analysis and the
        # other archive is produced by the non CTU analysis.
        failed_dir = os.path.join(self.report_dir, "failed")
        failed_files = os.listdir(failed_dir)
        print(failed_files)
        self.assertEqual(len(failed_files), 2)
        # Ctu should fail during analysis of main.c
        self.assertIn("main.c", failed_files[0])

    @skipUnlessCTUCapable
    @skipUnlessCTUDisplayCapable
    @skipUnlessCTUOnDemandCapable
    def test_ctu_on_demand_fallback(self):
        """ In case of ctu failure the non ctu analysis will be triggered when
        using on-demand-mode.
        """
        self.__set_up_test_dir('ctu_on_demand_failure')

        output = self.__do_ctu_all(on_demand=True,
                                   extra_args=[
                                       "--verbose", "debug",
                                       "-e", "debug.ExprInspection",
                                       "--ctu-reanalyze-on-failure"
                                   ])

        # lib.c should be logged as its AST is loaded by Clang
        self.assertRegex(output, r"CTU loaded AST file: .*lib\.c")

        # We expect two failure archives to be in the failed directory.
        # One failure archive is produced by the CTU analysis and the
        # other archive is produced by the non CTU analysis.
        failed_dir = os.path.join(self.report_dir, "failed")
        failed_files = os.listdir(failed_dir)
        print(failed_files)
        self.assertEqual(len(failed_files), 2)
        # Ctu should fail during analysis of main.c
        self.assertIn("main.c", failed_files[0])

    def __do_ctu_all(self, on_demand, extra_args=None):
        """
        Execute a full CTU run.
        @param extra_args: list of additional arguments
        """

        cmd = [self._codechecker_cmd, 'analyze', '-o', self.report_dir,
               '--analyzers', 'clangsa', '--ctu-all']
        cmd.extend(['--ctu-ast-mode',
                    'parse-on-demand' if on_demand else 'load-from-pch'])
        if extra_args is not None:
            cmd.extend(extra_args)
        cmd.append(self.buildlog)

        out, _ = call_command(cmd, cwd=self.test_dir, env=self.env)
        return out

    def __getClangSaPath(self):
        cmd = [self._codechecker_cmd, 'analyzers', '--details', '-o', 'json']
        output, _ = call_command(cmd, cwd=self.test_dir, env=self.env)
        json_data = json.loads(output)
        if json_data[0]["name"] == "clangsa":
            return json_data[0]["path"]
        if json_data[1]["name"] == "clangsa":
            return json_data[1]["path"]
