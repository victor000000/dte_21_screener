"""Execute the test recipe with Make's shell settings and a controlled runner."""
import os
import pathlib
import re
import shlex
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestTestRecipe(unittest.TestCase):
    def run_recipe(self, exit_code):
        source = (ROOT / "Makefile").read_text()
        settings = dict(re.findall(r"^(SHELL|\.SHELLFLAGS)\s*:?=\s*(.+)$", source, re.M))
        lines = source.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("test:")) + 1
        recipe = []
        while start < len(lines) and lines[start].startswith("\t"):
            recipe.append(lines[start][1:])
            start += 1
        self.assertTrue(recipe, "the test target no longer has a recipe")
        with tempfile.TemporaryDirectory() as temp:
            runner = pathlib.Path(temp) / "uv"
            runner.write_text(f'#!/bin/sh\necho "controlled test result" >&2\nexit {exit_code}\n')
            runner.chmod(0o755)
            command = [settings.get("SHELL", "/bin/sh"),
                       *shlex.split(settings.get(".SHELLFLAGS", "-c")), "\n".join(recipe)]
            return subprocess.run(command, capture_output=True, text=True,
                                  env=dict(os.environ, PATH=temp + os.pathsep + os.environ["PATH"]))

    def test_a_failing_runner_makes_the_recipe_fail(self):
        result = self.run_recipe(7)
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)

    def test_a_successful_runner_keeps_the_recipe_successful(self):
        self.assertEqual(self.run_recipe(0).returncode, 0)
