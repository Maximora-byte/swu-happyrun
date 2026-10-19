"""Synthetic checkout import precedence only; no APKs, certificates or devices."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS_COMMIT = "0cea241776c0233cd222213c475dec25aaf04be9"


class MumuCheckoutEntryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.product = base / "product checkout"
        self.tools = base / "tools checkout" / "scripts"
        self.runner = base / "runner checkout" / "scripts"
        product_package = self.product / "src" / "swu_happyrun"
        for directory in (self.tools, self.runner, product_package):
            directory.mkdir(parents=True)
        product_package.joinpath("__init__.py").write_text("", encoding="utf-8")
        self.tools.joinpath("check_local_https_delivery.py").write_text(
            "import check_remote_qa_packaging as packaging\n", encoding="utf-8"
        )
        self.tools.joinpath("check_remote_qa_packaging.py").write_text(
            "SUPPORTS_ADAPTER = True\n", encoding="utf-8"
        )
        self.runner.joinpath("check_remote_qa_packaging.py").write_text(
            "SUPPORTS_ADAPTER = False\n", encoding="utf-8"
        )
        self.runner.joinpath("mumu_https_fixture.py").write_text("", encoding="utf-8")
        self.runner.joinpath("check_mumu_https.py").write_text(
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n"
            "import check_local_https_delivery as delivery\n"
            "import mumu_https_fixture as fixture\n"
            "import swu_happyrun as product\n"
            "sources = {\n"
            "    'entry': __file__, 'delivery': delivery.__file__,\n"
            "    'packaging': delivery.packaging.__file__,\n"
            "    'fixture': fixture.__file__, 'product': product.__file__,\n"
            "}\n"
            "sources = {name: str(Path(path).resolve()) for name, path in sources.items()}\n"
            "sources['cwd'] = str(Path.cwd().resolve())\n"
            "print(json.dumps(sources))\n"
            "sys.exit(0 if delivery.packaging.SUPPORTS_ADAPTER else 2)\n",
            encoding="utf-8",
        )

    def invoke(self, *arguments):
        environment = os.environ.copy()
        environment.pop("PYTHONSAFEPATH", None)
        environment["PYTHONPATH"] = os.pathsep.join(
            str(path) for path in (self.tools, self.runner, self.product / "src")
        )
        environment["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, *arguments],
            cwd=self.product,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        self.assertEqual(result.stderr, "")
        return result.returncode, json.loads(result.stdout)

    def expected_sources(self, packaging_directory):
        return {
            "entry": str((self.runner / "check_mumu_https.py").resolve()),
            "delivery": str((self.tools / "check_local_https_delivery.py").resolve()),
            "packaging": str((packaging_directory / "check_remote_qa_packaging.py").resolve()),
            "fixture": str((self.runner / "mumu_https_fixture.py").resolve()),
            "product": str((self.product / "src/swu_happyrun/__init__.py").resolve()),
            "cwd": str(self.product.resolve()),
        }

    def test_direct_script_shadows_new_tool_helper_despite_pythonpath_order(self):
        code, sources = self.invoke(str(self.runner / "check_mumu_https.py"))
        self.assertEqual(code, 2, "old runner helper must reproduce the synthetic RED")
        self.assertEqual(sources, self.expected_sources(self.runner))

    def test_module_entry_preserves_tools_runner_product_precedence(self):
        code, sources = self.invoke("-m", "check_mumu_https")
        self.assertEqual(code, 0)
        self.assertEqual(sources, self.expected_sources(self.tools))

    def test_documented_commands_preserve_the_verified_checkout_recipe(self):
        guide = (ROOT / "docs/mumu-https-qa.md").read_text(encoding="utf-8")
        self.assertIn(TOOLS_COMMIT, guide)
        self.assertIn("Set-Location -LiteralPath $product", guide)
        self.assertIn('$env:PYTHONPATH = "$tools/scripts;$runner/scripts;$product/src"', guide)
        commands = [line for line in guide.splitlines() if line.startswith("python ")]
        self.assertEqual(len(commands), 2)
        self.assertTrue(all(line.startswith("python -m check_mumu_https ") for line in commands))
